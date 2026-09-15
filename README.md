# AutoScript Hub

面向团队的 Python 自动化脚本管理与执行平台：集中发布脚本、分配权限和跟踪执行，在 Windows 客户端完成实际任务。

**简体中文** | [English](README.en.md)

## 下载与版本

- **当前正式版：v1.2.4**。[GitHub Release：Windows 安装包与部署资产](https://github.com/CZF39631/AutoScript_Hub/releases/tag/v1.2.4)
- [Gitee 代码镜像](https://gitee.com/chuzifeng/auto-script_-hub) · [Gitee v1.2.4 镜像资产](https://gitee.com/chuzifeng/auto-script_-hub/releases/tag/v1.2.4)
- GitHub 是发布资产的真源，客户端依据签名更新清单校验安装包。Gitee 镜像代码、Tag、部署包、Skill 和签名清单，**不镜像 Windows EXE**；安装包仍从 GitHub 获取。
- `1.3.0-preview.1` 是开发预览，**尚未公开 Release**，不是正式升级目标。当前开发源码与 v1.2.4 交付物不完全相同。

开发分支已接入 React 主界面的简体中文 / English 切换，入口在登录页和主界面侧栏；**尚未随正式版发布**。脚本自带文字、原始日志、历史更新正文和原生初始化向导仍保留原文，详见[多语言支持范围](docs/多语言支持.md)。

## 架构与数据边界

```text
服务端（Linux / Docker）             Windows 执行端
FastAPI + React + SQLite   ← API →   桌面 UI + 后台 Agent + Updater
脚本版本、权限、调度与历史             依赖环境、脚本执行与本机文件
```

- **服务端**：单实例 SQLite，镜像支持 `linux/amd64` 与 `linux/arm64`；保存脚本包和版本、用户与分组、任务参数、运行记录，以及同步的日志和诊断信息。
- **Windows 客户端**：安装包自带私有 Python 运行时，按依赖指纹创建并复用隔离环境；输入和结果文件通常位于执行电脑。安装版关闭 UI 后，正在执行的任务可继续完成。
- **不是“所有业务数据永不上传”**：参数、日志和工单诊断可能包含业务信息，脚本也可自行访问网络或上传文件。发布前应审查代码、参数和日志内容，按实际场景配置访问控制与脱敏。
- **依赖隔离不是安全沙盒**：脚本以当前 Windows 用户权限运行，只执行可信代码。客户端保存的凭据使用 Windows DPAPI；服务端密钥和外部认证配置应保存在私有环境配置中。

## 核心能力

- **脚本市场与版本管理**：发布、安装和更新脚本，记录版本及变更说明；提供脚本契约、验证工具和 AI 编写 Skill。
- **角色与分组权限**：管理员管理全局资源，开发者管理所属分组脚本，操作员安装执行。角色决定操作能力，分组决定资源范围；用户和脚本可属于多个分组。
- **执行与排障**：任务调度、实时日志、取消任务、执行历史、失败工单和结果文件入口。
- **受限离线执行**：已缓存脚本需先联网同步授权，授权快照最长有效 7 天；撤权在下一次成功同步后生效，完全离线设备上的已下载文件无法即时召回。详见[权限与离线边界](docs/人员分组与脚本市场.md)。
- **可验证更新**：Ed25519 签名清单、安装包长度和 SHA-256 校验；支持公开源及局域网缓存。内置账号可用，企业外部身份认证为可选配置。

## 安全快速开始

### 1. 部署服务端

在 Linux 主机安装 Docker Engine 和 Compose 插件，从正式 Release 获取部署包并解压；在包含 `deploy/` 的目录执行（完整源码仓库也可使用这些命令）：

```bash
cp deploy/.env.example deploy/.env
id -u
id -g
```

**先编辑 `deploy/.env`，再启动**：

- 将 `AUTOSCRIPT_SERVER_IMAGE` 明确设为 `ghcr.io/czf39631/autoscript-hub-server:1.2.4`；源码中的示例仍含旧版本，不能直接作为最新正式版使用。
- 替换所有 `CHANGE_ME` 值。`JWT_SECRET` 使用至少 32 字符的独立随机密钥，`ADMIN_PASSWORD` 使用至少 12 字符的强密码；不要提交或分享真实 `.env`。
- 设置 `AUTOSCRIPT_DATA_DIR`，并让 `AUTOSCRIPT_UID` / `AUTOSCRIPT_GID` 与该目录所有者一致。下例假设使用 `/opt/autoscript-hub/data` 和当前用户的 UID/GID。
- 默认绑定 `0.0.0.0:8000`；用防火墙限制可信网络访问，不要直接暴露公网。跨不可信网络应配置 HTTPS 反向代理。

```bash
sudo install -d -o "$(id -u)" -g "$(id -g)" /opt/autoscript-hub/data
docker compose --env-file deploy/.env -f deploy/compose.yaml up -d
docker compose --env-file deploy/.env -f deploy/compose.yaml ps
curl --fail http://127.0.0.1:8000/api/health/ready
```

若修改端口，请同步修改检查地址。确认 `database`、`data_dir`、`migration` 均为 `ok`，再从可信网络访问 `http://<服务器地址>:8000`。只运行一个服务端副本；升级前备份数据库和 `.env`，不要删除持久化目录。备份、恢复、源码镜像构建和远程升级见[部署运维指南](docs/0.9-deployment-runbook.md)（含历史版本示例，请使用已发布的目标版本）。

### 2. 安装 Windows 执行端

下载 `AutoScript-Hub-Setup-1.2.4.exe`，核对 Release 的 `SHA256SUMS.txt` 后安装。无需另外安装 Python、Node.js 或 Git。首次启动通过**初始化向导**填写服务端地址和账号，不要把密码写进命令行。

正式版默认安装到 `%LOCALAPPDATA%\Programs\AutoScript Hub`，数据保存在 `%LOCALAPPDATA%\AutoScriptHub`。升级和普通卸载不会删除这些数据。

在“设置 → 客户端更新”检查更新，“更新说明”查看版本变化；重要更新可在升级后首次运行时提醒一次，也可关闭自动弹窗。客户端依次尝试服务端发布缓存、显式配置的清单地址和 Gitee Release；安装包按已验签清单中的地址下载（可指向 GitHub），不依赖 GitHub Release API 检查版本。局域网源也执行签名、长度与哈希校验。客户端不执行 `git pull`，不需要保存仓库 Token 或 SSH Key。

### 3. 区分 Preview 与正式安装

Preview 使用独立 AppId、安装目录、数据根 `%LOCALAPPDATA%\AutoScriptHubPreview` 和本地端口；默认开发服务地址为 `http://127.0.0.1:8765`，暂停在线更新，手动安装独立 Preview。**Beta / Stable 共用安装和数据，Beta 不是隔离测试环境**。用户主动指定的共享输出目录或正式服务不在默认隔离保证内。详见[Preview 安装与数据隔离](docs/Preview安装与数据隔离.md)。

## 开发与验证

使用 **Windows、Python 3.11、Node.js 20.19+（或 22.13+ / 24+）**。以下是开发源码示例，不用于升级正式安装。

使用全新、仅含源码的克隆目录，不复制生产 `config.json`、客户端配置、凭据或业务数据；后端兼容加载根目录配置，仅设置数据路径不等于隔离所有旧配置。使用干净终端，不继承生产环境变量。以下数据根放在仓库外，服务端与客户端分开：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt -r client\requirements.txt pytest==7.4.3 PyYAML==6.0.2
$env:DATA_DIR = Join-Path $env:LOCALAPPDATA "AutoScriptHubDev\server"
$env:DATABASE_URL = "sqlite:///" + ($env:DATA_DIR.Replace('\', '/') + "/autoscript.db")
New-Item -ItemType Directory -Force $env:DATA_DIR | Out-Null
$env:JWT_SECRET = & .\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(48))"
$env:ADMIN_USERNAME = "devadmin"
$secret = Read-Host "设置开发管理员密码（至少 12 字符）" -AsSecureString
$env:ADMIN_PASSWORD = [System.Net.NetworkCredential]::new('', $secret).Password
$env:EXTERNAL_AUTH_ENABLED = "false"
.\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
```

服务启动时自动迁移并初始化数据库。密码不进入命令历史，但会作为服务进程环境变量使用；停止服务后关闭该终端。

另一终端在仓库根目录启动 React 开发页面：

```powershell
cd frontend
npm ci
npm run dev
```

访问 `http://localhost:3000`，Vite 将 `/api` 代理到 `127.0.0.1:8000`。此页面用于服务端和前端开发；实际执行脚本仍需要 Windows Agent。

若需调试源码客户端，在另一个干净 PowerShell 终端、仓库根目录执行：

```powershell
$env:AUTOSCRIPT_INSTALL_FLAVOR = "preview"
$env:AUTOSCRIPT_CLIENT_DATA_DIR = Join-Path $env:LOCALAPPDATA "AutoScriptHubDev\client"
cd frontend
npm run build
cd ..
New-Item -ItemType Directory -Force client\ui\static | Out-Null
Copy-Item frontend\dist\* client\ui\static -Recurse -Force
.\.venv\Scripts\python.exe -m client.ui.main
```

向导中将服务地址改为 `http://127.0.0.1:8000`，只使用开发账号；向导完成时会通过 DPAPI 保存凭据，供 Agent 无密码参数启动。向导完成后，再运行一次 `python -m client.ui.main`（使用上述虚拟环境 Python）。在具有相同两个 `AUTOSCRIPT_*` 环境变量的独立终端，用 `.\.venv\Scripts\python.exe -m client.agent.main` 启动 Agent。不要使用正式客户端数据根，也不要与其他 Preview 共用端口运行。

在同一隔离开发环境中验证（仓库根目录）：

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m compileall -q backend client shared release skills
cd frontend
npm test
npm run lint
npm run build
```

Linux CI 的 Python 测试范围为 `shared/tests backend/tests test/release`；Windows 客户端相关验证应在 Windows 完成。

## 文档入口

- [部署、备份、恢复与升级](docs/0.9-deployment-runbook.md)
- [v1.2.4 发布记录](docs/releases/v1.2.4-发布记录.md)
- [人员分组、脚本市场与撤权规则](docs/人员分组与脚本市场.md)
- [Preview 安装与数据隔离](docs/Preview安装与数据隔离.md)
- [多语言支持与词条维护](docs/多语言支持.md)
- [Gitee 镜像与更新策略](docs/Gitee镜像与更新.md) · [更新说明维护](docs/更新说明维护.md)
- [脚本编写 Skill 与契约](skills/autoscript-script-authoring/SKILL.md)

脚本验证与打包（在已安装上述 Python 依赖的环境中）：

```bash
python skills/autoscript-script-authoring/scripts/validate_script.py <script.py|script.zip>
python skills/autoscript-script-authoring/scripts/package_script.py <source> <output.zip>
```

代码入口：`backend/` 服务端、`frontend/` React、`client/` Windows 执行端、`shared/` 共用契约、`deploy/` 部署、`ops/server/` 运维、`release/` 构建、`skills/` 脚本开发。

## 许可证

本项目采用 [MIT License](LICENSE)，允许商业使用、修改和分发，但须保留版权及许可声明，且不提供担保。第三方依赖、随包运行时及其他第三方组件保留各自版权，并遵循各自许可证；本项目的 MIT 许可不替代其许可条款。
