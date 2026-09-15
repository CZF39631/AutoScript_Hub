# Preview 安装与数据隔离

## 版本定位

| 项目 | Stable / Beta / RC | Preview |
| --- | --- | --- |
| 用途 | 同一正式安装家族的发布渠道 | 独立开发体验版 |
| 安装名称 | AutoScript Hub | AutoScript Hub Preview |
| 默认安装目录 | `%LOCALAPPDATA%/Programs/AutoScript Hub` | `%LOCALAPPDATA%/Programs/AutoScript Hub Preview` |
| 默认用户数据 | `%LOCALAPPDATA%/AutoScriptHub` | `%LOCALAPPDATA%/AutoScriptHubPreview` |
| Agent 端口 | 18080、18091–18099 | 18180、18191–18199 |
| 桌面 UI 端口 | 18081–18090 | 18181–18190 |
| 在线更新 | 保留现有 Beta / Stable 选择与签名验证 | 暂停在线更新，手动安装独立 Preview |

**Beta 不与 Stable 隔离，也不会因预发行状态而被归到 Preview。**

安装身份来自构建时的原始版本标记 `preview`，不能以更新渠道 `beta` 或 `Version.is_prerelease` 推导。`packaging` 会将 preview 归一为 rc，因此识别必须先于归一化，且不把 `+preview` 构建元信息当作安装身份。

## 隔离边界

- Preview 使用固定且独立的 AppId、程序组、快捷方式和窗口标题；不迁移旧正式版配置或凭据。
- 配置、DPAPI 凭据文件、本机 API token、脚本、依赖环境、日志、运行记录及 WebView 数据跟随独立数据根。
- Preview 数据根使用 `.install-flavor` 标记；拒绝接管已有且未标识的数据，也拒绝显式指向正式默认数据目录。空安装目录可由首次启动初始化。
- UI 只发现同安装家族的 Agent 端口；本机 API 的 token 和允许的 UI Origin 分离。
- 冻结应用不允许用继承环境变量改变构建安装身份。
- 安装目录的身份检查发生在停止进程和覆盖文件之前；旧无标记安装按正式家族处理。只关闭本安装目录的进程，不依赖 Restart Manager 批量关闭同名程序。
- 现有签名清单没有安装身份字段，Preview 因此不启动在线下载/安装/回退；正式更新拒绝明确 Preview 目标，Beta/RC 的原行为保留。

## 使用注意

- 安装新独立 Preview 不需要另建 Windows 用户；不要继续使用此前共享数据的 Preview 原型包。
- 默认开发服务为 `http://127.0.0.1:8765`，可在 Preview 初始化向导修改。
- 这不是脚本沙盒。Preview 仍以当前 Windows 用户权限执行脚本；用户主动配置的共享输出目录、浏览器或正式服务不在默认隔离保证内。
- 不自动删除或迁移旧原型数据；不修改正式用户数据。

## 验收状态

独立快照 713 项 Python / 39 项前端测试、lint/build、Inno 编译均通过；实际冻结 Agent 的默认路径、token/Origin、在线更新拒绝和合成正式 API 并存验收通过。详见 [独立体验版验收](releases/1.3.0-preview.1-独立体验版验收.md)。未执行真实用户环境覆盖安装。
