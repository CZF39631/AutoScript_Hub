# AutoScript Hub

AutoScript Hub 是面向团队和企业局域网的 Python 自动化脚本管理与执行平台。它把散落在个人电脑上的脚本变成可发布、可授权、可追踪的团队能力，同时让脚本和结果文件继续在实际执行的 Windows 客户端运行和保存。

服务端负责脚本版本、用户权限、任务调度、执行历史和审计；客户端负责隔离环境、真实执行、实时日志和结果文件。团队获得集中治理能力，又不必把业务文件集中上传到服务器。

## 核心优势

| 优势 | 带来的价值 |
|---|---|
| **安装后即可运行** | Windows 安装包自带私有 Python 3.11.9，使用者无需配置 Python、Node.js、Git 或全局依赖。 |
| **集中管理，数据留在本机** | 脚本、版本和权限由服务端统一管理；输入和结果文件留在执行客户端，减少文件搬运和集中泄露风险。 |
| **依赖隔离且可复用** | 根据脚本依赖指纹创建独立环境，相同依赖自动复用，既避免脚本互相污染，又减少重复安装时间。 |
| **执行过程可靠可见** | UI 关闭后 Agent 仍可继续任务；支持实时日志、取消任务、执行历史、失败工单和结果文件快速打开。 |
| **弱网场景更有韧性** | 已缓存脚本可在服务短暂不可用时继续执行，本地完成的记录在恢复连接后同步，降低网络波动影响。 |
| **企业身份与本地权限解耦** | 可使用内置账号，也可选接企业外部认证；身份验证与平台角色分开管理，支持管理员、开发者和操作员权限。 |
| **按团队隔离脚本市场** | 用户和脚本可加入多个分组，不同部门只看到获授权的脚本；角色控制操作能力，分组控制资源范围。 |
| **用户全生命周期管理** | 支持搜索、启禁用、角色调整和软删除，历史执行与审计记录不会因删除用户而丢失。 |
| **版本发布可追溯** | 脚本市场保存平台版本、语义版本和变更说明，可明确知道每次执行使用了哪一份代码。 |
| **更新链路可验证** | 支持 GitHub、Git Raw 和局域网更新源；更新清单使用 Ed25519 签名，并校验安装包长度与 SHA-256。 |
| **适合 AI 辅助开发** | 内置脚本契约、严格验证器和独立 AI Skill，让 AI 生成的脚本也遵循统一配置、参数、依赖和输出规范。 |
| **部署轻量且跨架构** | 单个 Docker 服务支持 `linux/amd64` 与 `linux/arm64`，适合普通服务器、NAS 和小型局域网环境。 |

## 典型使用场景

- 运营、数据和业务团队共享批处理脚本，而不要求每位使用者搭建开发环境。
- 开发者统一发布脚本版本，操作员只填写参数并执行，避免误改源码。
- 企业保留现有认证体系，同时在 AutoScript Hub 内独立控制脚本权限。
- 输入文件较大或较敏感，需要在员工电脑本地处理，只集中管理任务和审计信息。
- 脚本依赖复杂、版本冲突频繁，希望每个脚本拥有可复用的隔离环境。

## 正式交付形态

- 服务端：FastAPI、React 和 SQLite 单实例镜像，同一镜像支持 `linux/arm64` 与 `linux/amd64`。
- 客户端：`AutoScript-Hub-Setup-<version>.exe`，包含桌面 UI、后台 Agent、Updater 和私有 Python 运行时。
- 脚本开发：仓库提供 [autoscript-script-authoring Skill](skills/autoscript-script-authoring/SKILL.md) 和严格契约验证工具，Release 可同时分发独立开发包。
- 安全边界：客户端凭据使用 Windows DPAPI 保存；外部认证、私有服务地址和角色映射通过服务端私有环境变量配置。

## 局域网 Docker 启动

以下命令适用于 ARM64 与 x86-64 Linux：

```bash
cp deploy/.env.example deploy/.env
# 编辑 deploy/.env：至少修改 JWT_SECRET、ADMIN_PASSWORD、AUTOSCRIPT_DATA_DIR、UID/GID
mkdir -p /opt/autoscript-hub/data
docker compose --env-file deploy/.env -f deploy/compose.yaml up -d
curl http://127.0.0.1:8000/api/health/ready
```

同一局域网设备访问 `http://<服务器IP>:8000`。若在完整源码仓库中验证镜像：

```bash
docker compose --env-file deploy/.env \
  -f deploy/compose.yaml -f deploy/compose.local.yaml up -d --build
```

完整的备份、恢复、升级、回滚和镜像代理说明见 [docs/0.9-deployment-runbook.md](docs/0.9-deployment-runbook.md)。

## Windows 客户端

运行 Release 中的 `AutoScript-Hub-Setup-<version>.exe`。安装器默认按当前用户安装到 `%LOCALAPPDATA%\Programs\AutoScript Hub`，可变数据保存在 `%LOCALAPPDATA%\AutoScriptHub`，升级和普通卸载不会删除这些数据。

首次启动向导填写局域网服务端地址和账号。桌面 UI、后台 Agent 和 Updater 分别是独立 EXE；关闭 UI 不会终止 Agent 正在执行的脚本。

“设置 → 客户端更新”可检查、验证和安装更新。Gitee、Git Raw 或局域网清单地址可逐行填写，GitHub 仓库可单独配置。客户端不执行 `git pull`，也不保存仓库 Token 或 SSH Key。

## 开发启动

推荐 Python 3.11 和 Node.js 20：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt -r client\requirements.txt pytest==7.4.3 PyYAML==6.0.2
cd frontend
npm ci
npm test
npm run build
cd ..
# 首次启动必须设置强凭据；JWT_SECRET 至少 32 字符，管理员密码至少 12 字符
$env:JWT_SECRET = python -c "import secrets; print(secrets.token_urlsafe(48))"
$env:ADMIN_PASSWORD = Read-Host "设置管理员密码"
.\.venv\Scripts\python.exe backend\init_db.py
.\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port 8000
```

另一终端启动源码客户端：

```powershell
.\.venv\Scripts\python.exe -m client.start <用户名> <密码>
```

完整验证：

```powershell
.\.venv\Scripts\python.exe -m pytest -q
cd frontend
npm test
npm run lint
npm run build
```

## 发布与 Skill

- 历史发布流程、所需 Secret、资产和 0.9 → 1.0 晋级规则：[docs/0.9-release-guide.md](docs/0.9-release-guide.md)
- 历史 0.9 验收证据清单：[docs/0.9-acceptance-checklist.md](docs/0.9-acceptance-checklist.md)
- Skill 验证：`python skills/autoscript-script-authoring/scripts/validate_script.py <script.py|script.zip>`
- Skill 打包：`python skills/autoscript-script-authoring/scripts/package_script.py <source> <output.zip>`
- 人员分组、脚本市场隔离与升级兼容：[docs/人员分组与脚本市场.md](docs/人员分组与脚本市场.md)

## 关键目录

```text
backend/       FastAPI、数据库模型和 Alembic 迁移
frontend/      React 管理页面和桌面 UI 静态资源
client/        Windows UI、Agent、私有运行时和签名更新器
shared/        服务端、客户端和 Skill 共用的脚本/更新契约
deploy/        Docker Compose 与环境变量示例
ops/server/    备份、恢复、升级和回滚脚本
release/       Windows 构建和 Release 自动化
skills/        autoscript-script-authoring Skill
```
