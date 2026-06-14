# AutoScript Hub - 低代码自动化平台设计文档

> 日期：2026-05-31
> 状态：已确认
> 修订：2026-06-15 — 实现校准(追加功能保留 / 设计缺失补齐 / 离线模式新增)

## 修订摘要(2026-06-15)

本次修订将设计文档与实际实现对齐。三类变更:

1. **追加功能正式写入设计**(原本不在设计里但已实现):
   - `Environment` 表(本地运行环境配置:浏览器/Python/venv) — §4.9
   - `UserScript` 表(用户已安装脚本关联) — §4.10
   - `UserSettings` 表(用户客户端配置) — §4.11
   - 客户端→后端通信由 WebSocket 改为 **HTTP 轮询** — §5.9 / §6.4
   - UI 进程直连远程后端(经本地 UI server 代理),而非"仅连本地 Agent" — §5.11

2. **设计要求但缺失/做错的已补齐**:
   - `agents` 表补齐并明确与 `Environment` 的分工 — §4.4
   - `issues` 表补 `script_version` / `log_snapshot` / `resolved_version` 字段 — §4.6
   - 新增 `user_presets` 表(§5.3 个人预设持久化) — §4.12
   - 实时日志流改为 **SSE**(Server-Sent Events)而非 WS,理由:日志是单向服务器推送,SSE 更轻量 — §6.3
   - Agent 自动更新补完整流程(下载→替换→重启) — §5.8
   - 后端心跳超时看门狗 — §5.1
   - 日志清理定时任务 — §5.12

3. **新增能力:客户端离线执行**(用户新需求):
   - 客户端可执行已下载脚本,无需后端在线 — §5.13
   - 本地 Agent HTTP API(`/local/*`) — §6.8
   - 联网后自动同步本地 runs 到后端 — §5.13

---

## 1. 项目概述

### 1.1 背景
公司有多个 Python 自动化脚本（以 DrissionPage 浏览器自动化为主，涉及文件IO/Excel/TXT），需要统一管理和分发给员工在本地执行。

### 1.2 核心需求
- 开发者（1人）在本地编写 Python 脚本，通过 Web 平台上传管理
- 员工（5-20人）通过 pywebview2 桌面客户端选择脚本、填写参数、触发执行
- 脚本在员工本地电脑执行（DrissionPage 需要本地浏览器）
- 统一使用 Python 3.8.10，共用一个 venv

### 1.3 用户角色

| 角色 | 人数 | 权限 |
|------|------|------|
| admin | 少量 | 全部权限 + 用户管理 |
| developer | 1人 | 上传/管理脚本 + 执行 + 查看所有日志 |
| operator | 5-20人 | 执行被分配的脚本 + 查看自己的日志 + 上报问题 |

### 1.4 技术栈

| 层级 | 技术选型 | 理由 |
|------|---------|------|
| 前端 | React + Ant Design | 管理后台标准方案 |
| 后端 | FastAPI | 轻量，Python 生态，一个人好维护 |
| 数据库 | SQLite | 20人规模足够，后续可迁移 PostgreSQL |
| 客户端 | Python + pywebview2 | 复用系统 WebView2，内存约 100-150MB，纯 Python 开发 |
| 文件选择器 | pywebview2 原生对话框 / tkinter | pywebview2 自带文件选择 API，tkinter 兜底 |
| 通信 | HTTP + WebSocket | HTTP 管理接口，WebSocket 实时通信 |

---

## 2. 整体架构

```
┌──────────────────────────────────────────────────────┐
│           员工电脑 — Python 客户端应用                  │
│                                                      │
│  ┌─────────────────────────────────────────────────┐ │
│  │      UI 进程 — pywebview2 (系统 WebView2)         │ │
│  │  ┌────────────────────────────────────────────┐ │ │
│  │  │         React + Ant Design 管理界面          │ │ │
│  │  │  脚本列表 │ 参数表单 │ 日志监控 │ 仪表盘      │ │ │
│  │  └────────────────────────────────────────────┘ │ │
│  │  - 原生文件/目录选择对话框                         │ │
│  │  - 内存: ~100-150MB                              │ │
│  └────────────────────┬────────────────────────────┘ │
│                       │ 本地 HTTP (localhost)          │
│  ┌────────────────────┴────────────────────────────┐ │
│  │        Agent 进程 (独立 Python 子进程)             │ │
│  │  - WebSocket 长连接后端                           │ │
│  │  - 接收执行指令                                   │ │
│  │  - 调用 DrissionPage 执行脚本                     │ │
│  │  - 实时日志上报                                   │ │
│  │  - 看门狗防卡死                                   │ │
│  │  - 自动更新检查                                   │ │
│  │  - 内存: ~30-50MB                                │ │
│  └─────────────────────────────────────────────────┘ │
│  ┌─────────────────────────────────────────────────┐ │
│  │           系统托盘 (跟随 Agent 进程)               │ │
│  └─────────────────────────────────────────────────┘ │
└──────────────────────────┬───────────────────────────┘
                           │ HTTP / WebSocket
                           ▼
┌─────────────────────────────────────────────────────┐
│              服务器 (后端独立部署)                     │
│                                                     │
│  FastAPI                                            │
│  ├── 脚本上传/版本管理                               │
│  ├── 用户认证 / 权限 (JWT)                           │
│  ├── 参数解析 (import config())                      │
│  ├── 执行指令下发                                    │
│  ├── 日志存储/查询/清理                               │
│  ├── Agent 版本管理与更新分发                         │
│  └── 问题工单管理                                    │
│                                                     │
│  SQLite                                             │
│  ├── 用户表、角色表                                  │
│  ├── 脚本表、版本表                                  │
│  ├── 执行记录表、日志表                               │
│  ├── Agent注册表                                     │
│  └── 问题工单表                                      │
└─────────────────────────────────────────────────────┘
```

---

## 3. 脚本生命周期

```
开发者（你）                      服务器                         员工
   │                              │                             │
   │  1. 本地写脚本                │                             │
   │     my_script.py             │                             │
   │     def config(): ...        │                             │
   │     def main(): ...          │                             │
   │                              │                             │
   │  2. 客户端管理后台上传脚本──► │  3. 解析config()            │
   │     (填写changelog)          │     存储脚本文件             │
   │                              │     记录参数结构             │
   │                              │     创建版本记录             │
   │                              │                             │
   │                              │  4. 脚本出现在员工列表中     │
   │                              │ ◄─────── 5. 员工点击执行 ────│
   │                              │                             │
   │                              │  6. 检查Agent在线 + 无并发冲突│
   │                              │  7. 通知Agent拉取脚本 ──────►│
   │                              │                             │
   │                              │     8. Agent下载脚本+依赖    │
   │                              │     9. 参数校验              │
   │                              │    10. pywebview2渲染参数表单│
   │                              │    11. 员工填参数，选文件    │
   │                              │        (原生文件/目录选择器) │
   │                              │    12. Agent执行main()       │
   │                              │    13. 看门狗监控超时        │
   │                              │    14. 实时上报日志          │
   │                              │    15. 上传结果文件(如有)    │
   │                              │ ◄─────── 16. pywebview2展示  │
   │                              │ ◄─────── 17. 通知成功/失败 ─►│
```

### 3.1 脚本文件约定

每个脚本必须包含 `config()` 和 `main()` 两个函数：

```python
# my_script.py
def config():
    return {
        "name": "链接检查器",
        "version": "1.0.0",
        "description": "检查URL列表中每个链接的状态码",
        "category": "链接检查",
        "params": [
            {
                "key": "url_file",
                "type": "file",
                "label": "URL列表文件",
                "required": True,
                "help": "每行一个URL的txt文件"
            },
            {
                "key": "save_dir",
                "type": "folder",
                "label": "结果保存目录",
                "required": True,
                "auto_create": True
            },
            {
                "key": "timeout",
                "type": "number",
                "label": "超时时间(秒)",
                "default": 30,
                "min": 1,
                "max": 600
            },
            {
                "key": "method",
                "type": "select",
                "label": "检查方式",
                "options": ["GET", "HEAD"],
                "default": "HEAD"
            }
        ],
        "requirements": ["DrissionPage>=4.0", "openpyxl"],
        "timeout": 300,
        "presets": [
            {"name": "默认", "values": {"timeout": 30, "method": "HEAD"}},
            {"name": "深度检查", "values": {"timeout": 60, "method": "GET"}}
        ]
    }

def main(url_file, save_dir, timeout, method):
    from DrissionPage import ChromiumPage
    # 脚本逻辑...
    result_file = os.path.join(save_dir, "result.xlsx")
    # ...写入结果...
    return result_file  # 返回产出文件路径
```

### 3.2 参数类型与前端组件映射

| type | 前端组件 | Agent处理 | 校验规则 |
|------|---------|----------|---------|
| `text` | Input 输入框 | 直接传字符串 | required 时检查非空 |
| `number` | InputNumber 数字框 | 转为 int/float | 检查数字有效性，min/max 范围 |
| `file` | 路径显示 + "选择文件"按钮 | pywebview2 原生文件选择对话框 | 检查文件是否存在 |
| `folder` | 路径显示 + "选择目录"按钮 | pywebview2 原生目录选择对话框 | 检查目录是否存在，auto_create 时自动创建 |
| `select` | Select 下拉框 | 直接传选中的值 | 检查值在 options 中 |
| `checkbox` | Switch 开关 | 传 True/False | 无 |

### 3.3 上传类型

| 上传类型 | 说明 |
|---------|------|
| 单个 `.py` 文件 | 简单脚本，必须含 `config()` + `main()` |
| `.zip` 压缩包 | 多文件项目，根目录必须有 `main.py` 含 `config()` + `main()` |
| 公共模块 | 放到全局 `libs/` 目录，所有脚本可 import |

### 3.4 结果产出

`main()` 返回值决定是否有结果文件可下载：
- 返回字符串 → 单个文件路径，Agent 上传到后端
- 返回列表 → 多个文件路径，Agent 逐个上传
- 无返回值 → 只记录日志，无下载

---

## 4. 数据模型

### 4.1 users — 用户表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 唯一标识 |
| username | TEXT UNIQUE | 登录账号 |
| password_hash | TEXT | 加密密码 |
| display_name | TEXT | 显示名称 |
| role | TEXT | 角色：admin / developer / operator |
| status | TEXT | 状态：active / disabled |
| last_login_at | DATETIME | 最后登录时间 |
| created_at | DATETIME | 创建时间 |
| updated_at | DATETIME | 最后修改时间 |
| created_by | INTEGER FK→users | 谁创建的 |
| updated_by | INTEGER FK→users | 谁最后改的 |
| is_deleted | BOOLEAN | 软删除 |

### 4.2 scripts — 脚本表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 唯一标识 |
| name | TEXT | 脚本名称（从 config 读取） |
| description | TEXT | 脚本说明（从 config 读取） |
| category | TEXT | 分类标签 |
| type | TEXT | 上传类型：py / zip |
| latest_version | INTEGER | 最新版本号 |
| config_json | TEXT | 参数结构定义（JSON） |
| status | TEXT | 状态：active / disabled / draft |
| created_at | DATETIME | 创建时间 |
| updated_at | DATETIME | 最后修改时间 |
| created_by | INTEGER FK→users | 谁创建的 |
| updated_by | INTEGER FK→users | 谁最后改的 |
| is_deleted | BOOLEAN | 软删除 |

### 4.3 script_versions — 脚本版本表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 唯一标识 |
| script_id | INTEGER FK→scripts | 关联脚本 |
| version | INTEGER | 版本号 |
| changelog | TEXT | 版本说明 |
| file_path | TEXT | 该版本的文件存储路径 |
| config_json | TEXT | 该版本的参数结构快照 |
| created_by | INTEGER FK→users | 谁发布的 |
| created_at | DATETIME | 发布时间 |

### 4.4 agents — Agent 客户端表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 唯一标识 |
| machine_name | TEXT | 电脑名 |
| machine_ip | TEXT | IP 地址 |
| user_id | INTEGER FK→users | 属于哪个用户 |
| status | TEXT | 状态：online / offline |
| agent_version | TEXT | Agent 版本号 |
| last_heartbeat | DATETIME | 最后心跳时间 |
| created_at | DATETIME | 首次注册时间 |
| updated_at | DATETIME | 最后更新时间 |
| is_deleted | BOOLEAN | 软删除 |

> **实现说明(2026-06)**:`agents` 与 `environments`(§4.9)分工:
> - `agents` = 远程机器身份与在线状态(后端视角看「哪台机器在线」)
> - `environments` = 本地运行环境配置(浏览器路径 / Python 版本 / venv 路径,「怎么跑」)
> `runs` 表同时挂 `agent_id`(在哪跑)+ `environment_id`(用什么环境配置),两者均可空。

### 4.5 runs — 执行记录表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 唯一标识 |
| script_id | INTEGER FK→scripts | 哪个脚本 |
| script_version | INTEGER | 执行时的脚本版本号（快照） |
| user_id | INTEGER FK→users | 谁执行的 |
| agent_id | INTEGER FK→agents | 哪台电脑跑的 |
| status | TEXT | 状态：pending / running / success / failed / cancelled |
| params | TEXT | 本次执行的参数（JSON） |
| error_msg | TEXT | 失败时的错误信息 |
| result_files | TEXT | 产出文件路径列表（JSON） |
| started_at | DATETIME | 开始时间 |
| finished_at | DATETIME | 结束时间 |
| duration_sec | INTEGER | 执行耗时（秒） |
| log_path | TEXT | 日志文件路径 |
| created_at | DATETIME | 创建时间 |
| updated_at | DATETIME | 最后更新时间 |
| is_deleted | BOOLEAN | 软删除 |

### 4.6 issues — 问题工单表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 唯一标识 |
| title | TEXT | 问题标题 |
| description | TEXT | 问题描述 |
| reporter_id | INTEGER FK→users | 上报人 |
| run_id | INTEGER FK→runs | 关联的执行记录（可选） |
| log_snapshot | TEXT | 当时的日志快照 |
| script_id | INTEGER FK→scripts | 哪个脚本的问题 |
| script_version | INTEGER | 上报时的脚本版本号 |
| status | TEXT | 状态：open / resolved |
| resolved_by | INTEGER FK→users | 谁解决的 |
| resolved_at | DATETIME | 解决时间 |
| resolved_version | INTEGER | 用哪个脚本版本解决的 |
| resolve_note | TEXT | 解决说明 |
| created_at | DATETIME | 创建时间 |
| updated_at | DATETIME | 最后修改时间 |
| is_deleted | BOOLEAN | 软删除 |

### 4.7 audit_logs — 操作审计表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 唯一标识 |
| user_id | INTEGER FK→users | 谁操作的 |
| action | TEXT | 操作类型 |
| target_type | TEXT | 操作对象类型：script / user / agent / run / issue |
| target_id | INTEGER | 操作对象 ID |
| detail | TEXT | 操作详情（JSON） |
| ip_address | TEXT | 操作来源 IP |
| created_at | DATETIME | 操作时间 |

**记录的操作类型：**

| 操作 | action 值 |
|------|-----------|
| 上传脚本 | `script.upload` |
| 更新脚本 | `script.update` |
| 禁用/启用脚本 | `script.disable` / `script.enable` |
| 删除脚本 | `script.delete` |
| 创建用户 | `user.create` |
| 修改用户角色 | `user.role_change` |
| 禁用用户 | `user.disable` |
| 执行脚本 | `run.execute` |
| 取消执行 | `run.cancel` |
| Agent 上线/离线 | `agent.online` / `agent.offline` |
| 上报问题 | `issue.create` |
| 解决问题 | `issue.resolve` |

### 4.8 表关系图

```
users (开发者/员工)
  ├── 1:N → agents (每个用户可有多个Agent)
  ├── 1:N → runs (执行记录)
  ├── 1:N → issues.reporter_id (上报的问题)
  └── 1:N → issues.resolved_by (解决的问题)

scripts (脚本)
  ├── 1:N → script_versions (版本历史)
  └── 1:N → runs (执行记录)

agents (客户端)
  └── 1:N → runs (在哪台机器执行的)

audit_logs (独立，记录所有操作)
```

---

### 4.9 environments — 运行环境配置表(追加,2026-06)

存储每台客户端的本地执行环境配置。最初设计未列,实现过程中发现需要让用户为不同脚本场景配置不同浏览器/Python/代理,遂追加。

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 唯一标识 |
| user_id | INTEGER FK→users | 属于哪个用户 |
| name | TEXT | 环境名称(如「Chrome 120 + Python 3.10」) |
| browser_port | INTEGER | 浏览器调试端口(DrissionPage 用) |
| browser_path | TEXT | 浏览器可执行路径 |
| python_version | TEXT | Python 版本号 |
| venv_path | TEXT | venv 目录路径 |
| venv_status | TEXT | venv 状态:none / creating / ready / error |
| python_executable | TEXT | Python 解释器路径 |
| output_dir | TEXT | 默认结果输出目录 |
| proxy | TEXT | 代理地址 |
| extra_env | TEXT | 额外环境变量(JSON) |
| is_default | BOOLEAN | 是否默认环境 |
| created_at / updated_at | DATETIME | 创建/更新时间 |

### 4.10 user_scripts — 用户已安装脚本(追加,2026-06)

operator 角色用户需要先"安装"脚本才能看到并执行。admin 自动拥有全部脚本访问权。

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | |
| user_id | INTEGER FK→users | |
| script_id | INTEGER FK→scripts | |
| installed_at | DATETIME | 安装时间 |
| UNIQUE(user_id, script_id) | | 同一用户不重复安装 |

### 4.11 user_settings — 用户客户端设置(追加,2026-06)

存储每个用户的客户端偏好(默认服务器地址、默认浏览器、输出目录等)。Web 端可编辑,客户端同步到 `client_config.json`。

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | |
| user_id | INTEGER FK→users UNIQUE | 一对一 |
| settings_json | TEXT | 设置 JSON |

### 4.12 user_presets — 用户个人参数预设(追加,2026-06)

支持 §5.3 的「员工个人预设」持久化。开发者预设写在脚本 `config().presets` 中,所有用户可见但只读。

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | |
| user_id | INTEGER FK→users | 属于哪个用户 |
| script_id | INTEGER FK→scripts | 关联脚本 |
| name | TEXT | 预设名称 |
| values_json | TEXT | 参数值 JSON |
| created_at / updated_at | DATETIME | |
| UNIQUE(user_id, script_id, name) | | 同一用户同一脚本下名称唯一 |

---

## 5. 核心功能设计

### 5.1 运行管控

#### 禁止并发
Agent 同时只能执行一个脚本：
- 员工点击执行时，后端检查该 Agent 的 runs 表是否有 `status=running`
- 有 → 前端提示"当前有任务正在执行，请等待完成"
- 没有 → 下发执行指令

#### 看门狗防卡死
```
Agent 执行脚本时：
├── config() 中可声明超时："timeout": 300（秒），默认 600（10分钟）
├── Agent 启动子进程执行 main()
├── 主进程每 10 秒检查子进程状态
│   ├── 子进程还在跑，未超时 → 继续
│   ├── 子进程还在跑，已超时 → kill 子进程，标记 run 为 failed
│   └── 子进程已退出 → 记录结果
└── Agent 自身崩溃 → 后端心跳超时(>90秒无心跳) → 自动将所有 running 标记为 failed
```

#### 依赖自动安装
```python
# config() 中声明依赖
def config():
    return {
        "requirements": ["DrissionPage>=4.0", "openpyxl"]
    }
```
Agent 拉取脚本后：
1. 读取 `config().get("requirements", [])`
2. 检查 venv 中是否已安装
3. 缺失的 → `pip install` 安装
4. 安装失败 → 标记脚本为 `dependency_error`，通知员工联系开发者

### 5.2 执行前参数校验

Agent 收到执行指令后、调用 main() 之前先校验：

| 参数类型 | 校验规则 | 失败提示 |
|---------|---------|---------|
| `file` | 检查文件是否存在 | "文件不存在：D:\data\urls.txt" |
| `folder` | 检查目录是否存在；`auto_create=True` 时自动创建 | "目录不存在，是否创建？" |
| `text` + `required` | 检查非空 | "请填写 xxx" |
| `number` | 检查有效数字，min/max 范围 | "超时时间必须在1-600之间" |
| `select` | 检查值在 options 中 | "无效选项" |

校验不通过 → 暂停执行，错误信息回传 Web 端 → 员工修改后重新提交。

### 5.3 参数预设

config() 中可定义开发者预设，员工也可保存自己的预设：
- 开发者预设：写在 config() 的 `presets` 字段，所有人可见
- 员工个人预设：保存在后端（新增 `user_presets` 表），只有本人可见

### 5.4 结果产出与下载

- `main()` 返回文件路径（字符串或列表）→ Agent 上传到后端 → Web 上出现"下载结果"按钮
- `main()` 无返回值 → 只记录日志，无下载

### 5.5 消息通知

| 事件 | 系统气泡通知 | pywebview2 页面通知 |
|------|------------|---------|
| 执行成功 | "xxx 执行完成" | 页面内通知栏弹出 |
| 执行失败 | "xxx 执行失败：原因" | 页面内通知栏弹出 + 红色标记 |
| Agent 更新可用 | "发现新版本，点击更新" | — |

实现方式：
- 系统气泡：pywebview2 窗口内弹出通知 / tkinter messagebox
- Web 通知：pywebview2 内页面通过 JS 调用展示通知

### 5.6 脚本分类与搜索

- 脚本按 `category` 字段分组，左侧分类导航栏
- 顶部搜索框按脚本名称模糊搜索
- 分类由开发者上传时自定义，后端自动收集已有分类供下拉选择

### 5.7 脚本版本管理

- 每次上传必须填写 changelog
- 员工端显示当前版本号，可查看历史版本说明
- 只能执行最新版本，历史版本不可执行

### 5.8 Agent 自动更新

```
Agent 启动时：
1. 请求 GET /api/agent/check-update?version=x.x.x
2. 后端对比最新版本
   ├── 版本一致 → 正常连接
   └── 有新版本 → 弹窗提示"发现新版本 vx.x.x，是否更新？"
       ├── 员工点"更新" → 下载新版本包 → 替换文件 → 自动重启
       └── 员工点"跳过" → 本次不更新（下次启动仍提示）
```

### 5.9 Agent 断线重连

```
Agent WebSocket 连接逻辑：
1. 启动 → 连接后端 WebSocket
2. 断线后 → 每 5 秒尝试重连
3. 重连期间：
   ├── 本地正在执行的脚本 → 不受影响，继续执行
   │   └── 完成后本地缓存结果，重连后补报
   └── 后端暂存离线期间的指令 → 重连成功后立即拉取
4. 连续断线超过 30 分钟 → 弹系统通知"与服务端断开连接"
```

### 5.10 仪表盘

首页展示：
- 今日/本周执行次数、成功率
- 在线 Agent 数量
- 最近失败的任务列表（快速定位问题）
- 待处理的 open 状态问题工单

### 5.11 客户端架构说明

员工端由两个独立进程组成，通过本地 HTTP 接口通信：

**UI 进程（pywebview2）：**
- 使用系统 WebView2 渲染 React 前端页面
- 内存约 100-150MB
- 负责用户交互、表单渲染、日志展示
- 原生文件/目录选择对话框（`webview.windows[0].create_file_dialog()`）
- 崩溃后可重启，不影响 Agent

**Agent 进程（独立 Python 子进程）：**
- 内存约 30-50MB
- 负责脚本执行、WebSocket 通信、看门狗
- 作为后台服务常驻，系统托盘跟随此进程
- UI 进程崩溃不影响正在执行的脚本
- 开机自启，独立于 UI 运行

**两进程通信：**
- Agent 启动一个本地 HTTP 服务（如 `localhost:18080`）
- UI 进程通过 HTTP 调用 Agent 接口（获取状态、触发执行、获取日志等）
- Agent 通过 WebSocket 与远程后端通信
- UI 进程仅与本地 Agent 通信，不直接连接远程后端（除了认证）

```
React 前端 ──► pywebview2 JS-RPC ──► UI 进程 Python 侧
                                         │
                                         │ HTTP localhost:18080
                                         ▼
                                    Agent 进程 ──► WebSocket ──► 远程后端
```

### 5.12 问题上报系统

```
员工执行失败
  → 点"上报问题"，填写描述，自动附带本次日志和脚本版本
    → 问题进入 issues 列表（状态：open）
      → 开发者在后台看到问题，排查修复
        → 上传新版本脚本，在问题记录中点"标记已解决"
          → 填写解决说明，自动记录解决时间和修复版本号
```

### 5.12 日志清理策略

```python
LOG_RETENTION_DAYS = 30           # 日志保留天数
LOG_CLEANUP_HOUR = 3              # 每天凌晨 3 点执行清理
LOG_ARCHIVE_BEFORE_DELETE = True  # 删除前归档压缩
LOG_ARCHIVE_DIR = "/logs/archive" # 归档目录
LOG_ARCHIVE_RETENTION_DAYS = 90   # 归档保留 90 天后彻底删除
```

清理规则：
- 每天定时扫描 runs 表
- 超过 30 天且 status != running 的记录 → 删除对应日志文件
- runs 表记录本身保留，只清理物理日志文件
- 归档文件保留 90 天后自动删除

---

### 5.13 客户端离线执行能力(追加,2026-06)

**需求背景**:员工网络不稳定或后端维护时,客户端仍需可用 — 只要脚本已经下载到本地,就能执行,结果在恢复连接后自动同步回后端。

#### 工作流程

```
员工触发执行(后端不可达)
  → UI 检测到 /api/health 失败,自动切换"离线模式"
  → UI 显示离线横幅,调用 http://127.0.0.1:18080/local/* (本地 Agent)
  → POST /local/execute {script_id, params}
  → Agent 启动子进程,本地分配 local_run_id (如 "L1")
  → 执行完成,结果存到 .local_runs.json (持久化,跨进程重启)
  → 系统气泡通知员工"执行完成"
  → 主循环检测到后端可达 → _sync_local_runs_to_backend():
      ├── POST /api/runs/execute 创建后端 run 记录
      ├── PATCH /api/runs/{id}/status 回填最终状态 + 结果
      └── 标记本地 run synced + 记录 backend_run_id
```

#### 关键约束

- **本地脚本缓存**:Agent 已下载过的脚本保留在 `storage/scripts/{script_id}/{version}/`,离线模式直接复用
- **并发限制**:本地执行同样遵守"一次只跑一个"(与后端触发的任务共享 `_running_proc` 检查)
- **环境配置**:离线模式下 Environment 表不可用,UI 可在请求中直接传 `env_vars` 字典
- **依赖安装**:离线时 `pip install` 仍尝试执行(假设 PyPI 可达),失败则脚本失败
- **同步去重**:已 `synced` 的本地 run 不会重复同步,通过 `backend_run_id` 字段标识

#### 本地 HTTP API(详见 §6.8)

Agent 进程在 `127.0.0.1:18080` 提供 `/local/*` 端点供 UI 离线调用:
- `GET /local/scripts` — 列出本地缓存的脚本
- `POST /local/execute` — 触发本地执行
- `GET /local/runs` / `GET /local/runs/{id}` — 本地执行记录
- `GET /local/runs/{id}/log` — 本地执行日志
- `GET /local/connection` — 客户端连接状态(在线/待同步数)

### 5.14 通信模型说明(轮询替代 WebSocket,2026-06 校准)

**设计原文(§5.9 / §6.4)假设**:Agent ↔ 后端用 WebSocket 长连接。

**实现采用的方案**:Agent ↔ 后端用 **HTTP 轮询**(每 5 秒拉 `GET /api/runs?status=pending`)。

**变更理由**:
1. 轮询模式部署简单,不需要 WebSocket 状态管理
2. 20 人规模下,5 秒轮询的开销可忽略
3. 天然容错 — 网络抖动只是错过几次轮询,不会"断开连接"
4. 实时日志流仍然用 **SSE**(Server-Sent Events),前端体验无损

**前端实时日志流**:用 SSE 而非 WS,理由是日志是单向服务器推送,SSE 比 WS 更轻量、原生浏览器支持、不需要协议升级。详见 §6.3。

**Agent 心跳**:每次轮询周期发一次 `POST /api/agents/{id}/heartbeat`,后端定时扫描(每 30 秒)将 >90 秒无心跳的 Agent 标记 offline,并将其 running 的 runs 标记 failed(§5.1 后端看门狗)。

**离线容错(适配轮询)**:
- status 上报失败 → 写入本地 `.pending_reports.json`,下个周期重试
- 连续断线 30 分钟 → 弹系统通知(§5.9)
- 后端可达时自动 flush 所有 pending 上报

---

## 6. API 设计概要

### 6.1 认证
- `POST /api/auth/login` — 登录，返回 JWT
- `POST /api/auth/logout` — 登出

### 6.2 脚本管理
- `GET /api/scripts` — 脚本列表（支持分类筛选、搜索）
- `POST /api/scripts/upload` — 上传脚本（py/zip + changelog）
- `PUT /api/scripts/{id}` — 更新脚本信息
- `POST /api/scripts/{id}/disable` — 禁用脚本
- `POST /api/scripts/{id}/enable` — 启用脚本
- `GET /api/scripts/{id}/versions` — 版本历史
- `GET /api/scripts/{id}/config` — 获取参数结构

### 6.3 执行管理
- `POST /api/runs/execute` — 触发执行（script_id + params）
- `POST /api/runs/{id}/cancel` — 取消执行
- `GET /api/runs` — 执行记录列表
- `GET /api/runs/{id}` — 执行详情 + 日志
- `GET /api/runs/{id}/download` — 下载结果文件
- `GET /api/runs/{id}/log/stream` — 实时日志流（WebSocket）

### 6.4 Agent 通信
- `WS /api/agent/ws` — Agent WebSocket 长连接
- `GET /api/agent/check-update` — 检查更新
- `GET /api/agent/download/{version}` — 下载新版本

### 6.5 问题工单
- `POST /api/issues` — 上报问题
- `GET /api/issues` — 问题列表
- `POST /api/issues/{id}/resolve` — 标记已解决
- `GET /api/issues/{id}` — 问题详情

### 6.6 用户管理（admin）
- `GET /api/users` — 用户列表
- `POST /api/users` — 创建用户
- `PUT /api/users/{id}` — 修改用户
- `POST /api/users/{id}/disable` — 禁用用户

### 6.7 仪表盘
- `GET /api/dashboard/stats` — 统计数据

---

### 6.8 新增/校准端点(2026-06)

#### Agent 注册与心跳(§4.4 / §5.1)
- `POST /api/agents/register` — Agent 启动注册,返回 agent_id(同 user+machine 幂等)
- `POST /api/agents/{id}/heartbeat` — 心跳上报
- `GET /api/agents` — 列表(admin/developer)
- `GET /api/agents/mine` — 当前用户的 Agent
- `GET /api/agents/{id}` — 详情
- `DELETE /api/agents/{id}` — 软删除(admin)

#### 参数预设(§5.3)
- `GET /api/scripts/{id}/presets` — 返回 `{developer: [...], personal: [...]}`
- `POST /api/scripts/{id}/presets` — 创建个人预设
- `PUT /api/presets/{id}` — 更新个人预设
- `DELETE /api/presets/{id}` — 删除个人预设

#### Run 结果下载
- `GET /api/runs/{id}/download` — 单文件直接下载;多文件打包 zip 流式返回

#### Agent 自动更新(§5.8)
- `GET /api/agent/check-update?version=X.X.X` — 返回 `{latest_version, update_available, package_available}`
- `GET /api/agent/download/{version}` — 下载客户端安装包 zip(从 `client_dist/` 提供)

#### 实时日志流(§6.3 校准)
- `GET /api/runs/{id}/log/stream?token=...` — **SSE**(Server-Sent Events),非 WebSocket
- 数据格式:`data: {"log": "...片段..."}\n\n`,结束时发 `data: {"done": true}\n\n`
- token 通过 query string 传递(浏览器 EventSource API 不支持自定义 header)

#### 客户端本地 HTTP API(§5.13 离线模式)

Agent 进程在 `127.0.0.1:18080` 提供,UI 在后端不可达时使用:
- `GET /local/scripts` — 本地缓存脚本列表(扫描 `storage/scripts/` 并解析每个 main.py 的 config())
- `POST /local/execute` — 触发本地执行,请求体 `{script_id, params, env_vars?}`
- `GET /local/runs` — 本地执行记录列表
- `GET /local/runs/{local_run_id}` — 单个本地 run 详情
- `GET /local/runs/{local_run_id}/log` — 本地 run 日志
- `GET /local/connection` — 返回 `{online, last_online_at, pending_sync_count, agent_id}`

#### 既有但补充说明的端点
- `GET /api/scripts/{id}/versions` — 版本历史(已实现)
- `GET /api/scripts/{id}/download?version=X` — 脚本文件下载(已实现,区别于 `/api/runs/{id}/download`)
- `GET /api/scripts/{id}` — 返回 ScriptDetail 含 `config_json`,等价于设计 §6.2 的 `/config` 端点

---

## 7. 非功能性要求

### 7.1 安全
- 所有 API 需要 JWT 认证（登录接口除外）
- 按角色做接口级权限控制
- 脚本上传权限仅限 developer / admin
- 敏感参数（密码类）在日志和数据库中脱敏处理
- password 使用 bcrypt 哈希存储

### 7.2 性能
- 20人并发完全够用，无需特别优化
- WebSocket 心跳间隔 30 秒
- 日志实时推送，非批量轮询

### 7.3 部署
- 开发阶段后端跑在本地
- 后续迁移到公司服务器，只需改配置
- Agent 部署：每台员工电脑安装 Python 3.8.10 + venv + pywebview2 客户端
- 客户端后续通过平台自动更新

---

## 8. MVP 范围与优先级

### Phase 1 — 核心可用
- 用户认证与角色权限
- 脚本上传与管理（单文件 + zip）
- config() 解析与 UI 自动生成
- pywebview2 客户端基础功能（窗口渲染、连接后端、执行、日志上报）
- 原生文件/目录选择对话框
- 执行记录与日志查看
- 禁止并发

### Phase 2 — 运行稳定
- 看门狗防卡死
- 依赖自动安装
- 参数校验
- 断线重连
- Agent 自动更新
- 操作审计

### Phase 3 — 体验完善
- 结果产出与下载
- 消息通知（系统气泡 + Web 通知）
- 参数预设
- 脚本分类与搜索
- 版本 changelog 展示
- 日志清理策略

### Phase 4 — 管理闭环
- 仪表盘
- 问题上报系统
- 公共模块管理
