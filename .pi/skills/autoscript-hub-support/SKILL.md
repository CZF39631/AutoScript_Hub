---
name: autoscript-hub-support
description: >
  处理 AutoScript Hub 应用层支持、待处理工单、执行失败、客户端 Agent 连接、脚本缺陷、脚本市场版本和脚本发布。用户提到“检查工单”“待处理问题”“查看运行日志”“修复脚本”“发布脚本版本”“脚本市场还是旧版本”“客户端连不上”“Agent 状态”时使用本 Skill；即使用户只说“检查一下”也应触发。覆盖当前客户端目标识别、脱敏诊断、下载线上脚本、最小修复、契约验证、两阶段安全发布和发布后复核。不用于 Docker、1Panel、FRP、SSH、数据库维护、系统扩容或通用基础设施运维。
compatibility: Windows desktop client configuration, Python 3.10+, requests
---

# AutoScript Hub 应用支持

以当前 Windows 客户端配置为连接入口，完成工单诊断、脚本修复和安全发布。把“目标正确”和“改动最小”放在首位，避免把本地测试库误当成用户正在使用的服务器。

## 快速入口

本 Skill 的确定性工具位于：

```text
scripts/support_client.py
```

从仓库根目录执行：

```bash
python .pi/skills/autoscript-hub-support/scripts/support_client.py target
python .pi/skills/autoscript-hub-support/scripts/support_client.py issues
python .pi/skills/autoscript-hub-support/scripts/support_client.py issue --issue-id 3
```

工具默认读取当前 Windows 客户端的 `client.json` 和 DPAPI 凭据，不接受明文密码参数，也不会输出 token、密码或完整带签名 URL。

## 意图与权限

根据用户原话决定允许的操作：

| 用户意图 | 允许操作 |
|---|---|
| “检查工单”“看看问题” | 只读查询、日志诊断，不改文件、不发布、不关闭工单 |
| “修复，先别发布” | 下载线上基线、建立 Git 分支、最小修改、针对性验证，不发布 |
| “修复并发布”“发 2.0.2” | 完成修复、验证、发布计划和发布执行；无需重复询问 |
| “关闭/解决工单” | 在修复已验证后允许关闭指定工单 |

模糊请求按只读处理。不要因为发现了明显修复方案就越权发布或关闭工单。

## 目标识别

每次连接或写操作前先运行 `target`。报告一行：

```text
目标：<服务器 origin>｜用户：<用户名>｜来源：当前客户端配置
```

遵守以下边界：

1. 默认只使用当前客户端配置，不从仓库 `tmp/`、测试数据库或 `.vscode` 配置推断目标。
2. 只有用户明确说“本地测试”“测试库”时，才设置 `AUTOSCRIPT_CLIENT_DATA_DIR` 指向测试客户端数据目录。
3. 工具显示的目标与用户语境不一致时停止，先说明差异。
4. 不在 Skill、脚本、日志或提交中保存服务器密码、JWT、代理签名或私有认证地址。

## 工单诊断流程

1. 运行 `issues` 获取待处理工单。
2. 对目标工单运行 `issue --issue-id ID`，读取关联运行摘要和脱敏日志。
3. 依据证据分类：
   - **脚本逻辑**：日志显示业务状态错误、参数处理错误或输出数量错误。
   - **运行环境**：依赖环境缺失、浏览器/代理/路径错误。
   - **客户端 Agent**：未注册、离线、下载失败、本地执行器异常。
   - **服务端**：API、权限、任务分配、状态回写异常。
4. 只报告有日志、接口响应或代码路径支持的结论，不猜测。
5. 用户仅要求检查时，输出：工单、证据、根因、建议版本；到此停止。

日志可能包含输入路径、商品 URL、代理地址和签名。工具会自动脱敏；回答中不要恢复被隐藏的值。

## 脚本修复流程

用户授权修复后：

1. 运行 `marketplace --name "精确脚本名"` 确认脚本 ID 和线上版本。
2. 运行 `download --script-id ID --output PATH` 下载当前线上版本，禁止直接修改服务器存储或客户端缓存。
3. 从线上文件建立修复副本；只改工单要求的逻辑。
4. 按 SemVer 升级脚本 `config().version`。修复默认提升补丁版本。
5. 阅读仓库的 `skills/autoscript-script-authoring/SKILL.md`，执行严格契约验证。
6. 为缺陷编写最小复现测试，验证：修复前失败、修复后通过。
7. 小脚本修复只运行契约验证和针对性测试；不要自动运行整个项目构建、安装器或无关测试。
8. 若修改的是平台代码而非脚本，遵守仓库 Git 分支、中文提交和验证流程。

## 两阶段发布

发布使用计划文件防止目标、脚本或版本漂移。

### 1. 创建计划

```bash
python .pi/skills/autoscript-hub-support/scripts/support_client.py publish-plan \
  --artifact PATH --script-id ID --expected-current 2.0.1 \
  --changelog "2.0.2：修复……"
```

计划阶段会：

- 严格验证脚本契约；
- 查询目标服务器当前版本；
- 校验脚本 ID、当前版本和新 SemVer；
- 记录目标 origin、文件 SHA-256 和 30 分钟有效期；
- 不上传任何文件。

向用户简洁显示：

```text
目标：公司服务器｜脚本 #2｜2.0.1 → 2.0.2
```

### 2. 执行计划

仅在用户已经明确说“发布/发版”时运行：

```bash
python .pi/skills/autoscript-hub-support/scripts/support_client.py publish-apply
```

执行阶段会重新验证目标、文件哈希和线上当前版本，上传后再查询脚本市场确认。不要绕过计划直接调用上传 API。

## 关闭工单

发布和复核不等于自动关闭工单。只有用户明确要求关闭时执行：

```bash
python .pi/skills/autoscript-hub-support/scripts/support_client.py resolve \
  --issue-id ID --note "修复说明与验证证据" --apply
```

关闭前确认工单仍为 `open`，并在结果中报告工单 ID 和处理说明。

## 输出要求

保持简洁，默认使用：

```text
目标：<服务器>
工单：#<id> <标题>
结论：<一句话根因>
处理：<已做或建议动作>
验证：<版本/API/测试证据>
```

不要向用户展示内部探索过程、凭据读取过程或与当前小修复无关的完整构建日志。
