# AutoScript Hub

AutoScript Hub 是面向局域网的 Python 自动化脚本管理与执行平台。0.9 由 Linux Docker 服务端和 Windows x86-64 桌面客户端组成；脚本结果文件始终留在实际执行的客户端。

## 0.9 交付形态

- 服务端：同一镜像支持 `linux/arm64` 与 `linux/amd64`，FastAPI、React 和 SQLite 单实例运行。
- 客户端：`AutoScript-Hub-Setup-<version>.exe`，不要求用户预装 Python、Node.js 或 Git。
- 脚本运行时：安装器提供私有 Python 3.11.9，依赖按指纹创建并复用隔离环境。
- 更新：从公开 GitHub Release、公开 Gitee/Git Raw URL 或局域网 HTTP 清单检查；清单使用 Ed25519 签名，安装包校验长度和 SHA-256，并且由用户确认安装。
- AI Skill：仓库内 [skills/autoscript-script-authoring](skills/autoscript-script-authoring/SKILL.md)，Release 同时提供独立 ZIP；0.9 客户端不内置在线 AI。

## 局域网 Docker 启动

以下命令适用于 ARM64 与 x86-64 Linux：

```bash
cp deploy/.env.example deploy/.env
# 编辑 deploy/.env：至少修改 JWT_SECRET、ADMIN_PASSWORD、AUTOSCRIPT_DATA_DIR、UID/GID
mkdir -p /opt/autoscript-hub/data
docker compose --env-file deploy/.env -f deploy/compose.yaml up -d
curl http://127.0.0.1:8000/api/health/ready
```

同一局域网设备访问 `http://192.168.1.106:8000`；请替换为真实服务器 IP 和端口。若在完整源码仓库中验证镜像：

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

- 发布流程、所需 Secret、资产和 0.9 → 1.0 晋级规则：[docs/0.9-release-guide.md](docs/0.9-release-guide.md)
- 0.9 验收证据清单：[docs/0.9-acceptance-checklist.md](docs/0.9-acceptance-checklist.md)
- Skill 验证：`python skills/autoscript-script-authoring/scripts/validate_script.py <script.py|script.zip>`
- Skill 打包：`python skills/autoscript-script-authoring/scripts/package_script.py <source> <output.zip>`

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
