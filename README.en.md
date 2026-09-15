# AutoScript Hub

A Python automation platform for teams: publish scripts centrally, control access, and track runs while executing tasks on Windows clients.

[简体中文](README.md) | **English**

## Downloads and versions

- **Current stable release: v1.2.4**. [GitHub Release: Windows installer and deployment assets](https://github.com/CZF39631/AutoScript_Hub/releases/tag/v1.2.4)
- [Gitee source mirror](https://gitee.com/chuzifeng/auto-script_-hub) · [Gitee v1.2.4 mirrored assets](https://gitee.com/chuzifeng/auto-script_-hub/releases/tag/v1.2.4)
- GitHub is the source of truth for release assets. The client verifies installers against signed update manifests. Gitee mirrors code, tags, deployment bundles, the Skill, and signed manifests, **not Windows EXE files**. Installers are downloaded from GitHub.
- `1.3.0-preview.1` is a development preview with **no public Release yet**, not a stable upgrade target. Development source differs from the v1.2.4 deliverables.

The development branch supports Simplified Chinese / English switching for the React interface, available on the sign-in page and in the sidebar. **This has not shipped in a stable release.** Script-provided text, raw logs, historical release-note content, and the native setup wizard retain their original language. See [language support scope](docs/多语言支持.md).

## Architecture and data boundaries

```text
Server (Linux / Docker)              Windows execution client
FastAPI + React + SQLite   ← API →   Desktop UI + background Agent + Updater
Versions, access, scheduling         Dependency environments, execution,
and run history                     and local files
```

- **Server**: a single-instance SQLite deployment, with images for `linux/amd64` and `linux/arm64`. Stores script packages and versions, users and groups, task parameters, run records, and synchronized logs and diagnostics.
- **Windows client**: the installer includes a private Python runtime. Dependency environments are isolated and reused by dependency fingerprint. Input and result files usually reside on the execution computer. In the installed client, an active task can finish after the UI closes.
- **Not a promise that business data never leaves the device**: parameters, logs, and support diagnostics may contain business information; scripts can also access networks or upload files. Review code, parameters, and logging, and apply appropriate access controls and redaction.
- **Dependency isolation is not a security sandbox**: scripts run with the current Windows user's permissions. Run trusted code only. Saved client credentials use Windows DPAPI; server secrets and external authentication settings belong in private environment configuration.

## Core capabilities

- **Script catalog and versioning**: publish, install, and update scripts with version records and change notes; script contracts, validation tools, and an AI authoring Skill are included.
- **Roles and groups**: administrators manage all resources, developers manage scripts in their groups, and operators install and run scripts. Roles determine actions; groups determine resource scope. Users and scripts can belong to multiple groups.
- **Execution and troubleshooting**: scheduling, live logs, cancellation, run history, failure tickets, and access to result files.
- **Bounded offline execution**: cached scripts require a prior online authorization sync. Authorization snapshots last at most seven days; revocation takes effect after the next successful sync. Downloaded files cannot be recalled immediately from a fully offline device. See [access and offline boundaries](docs/人员分组与脚本市场.md).
- **Verifiable updates**: Ed25519-signed manifests, installer length and SHA-256 checks, public sources, and LAN caching. Built-in accounts are supported; external enterprise authentication is optional.

## Safe quick start

### 1. Deploy the server

Install Docker Engine and the Compose plugin on Linux. Download and extract the deployment bundle from the stable Release. Run these commands in the directory containing `deploy/` (they also work in the full source checkout):

```bash
cp deploy/.env.example deploy/.env
id -u
id -g
```

**Edit `deploy/.env` before starting**:

- Explicitly set `AUTOSCRIPT_SERVER_IMAGE=ghcr.io/czf39631/autoscript-hub-server:1.2.4`. The source example still contains an older version; do not assume it selects the current stable image.
- Replace every `CHANGE_ME` value. Use a unique random `JWT_SECRET` of at least 32 characters and a strong `ADMIN_PASSWORD` of at least 12 characters. Never commit or share the real `.env`.
- Set `AUTOSCRIPT_DATA_DIR` and match `AUTOSCRIPT_UID` / `AUTOSCRIPT_GID` to its owner. The example below assumes `/opt/autoscript-hub/data` and the current user's UID/GID.
- The default binding is `0.0.0.0:8000`. Restrict access to trusted networks with a firewall; do not expose it directly to the public internet. Use an HTTPS reverse proxy across untrusted networks.

```bash
sudo install -d -o "$(id -u)" -g "$(id -g)" /opt/autoscript-hub/data
docker compose --env-file deploy/.env -f deploy/compose.yaml up -d
docker compose --env-file deploy/.env -f deploy/compose.yaml ps
curl --fail http://127.0.0.1:8000/api/health/ready
```

Adjust the health-check URL if you change the port. Confirm that `database`, `data_dir`, and `migration` are all `ok`, then access `http://<server-address>:8000` from a trusted network. Run only one server replica. Back up the database and `.env` before upgrades; do not delete persistent data. See the [deployment runbook](docs/0.9-deployment-runbook.md) for backup, restore, source image builds, and remote upgrades (it includes historical version examples; select a published target version).

### 2. Install the Windows client

Download `AutoScript-Hub-Setup-1.2.4.exe`, compare its checksum with the Release's `SHA256SUMS.txt`, and install it. No separate Python, Node.js, or Git installation is required. Enter the server address and account through the **first-run setup wizard**, not password-bearing command-line arguments.

Stable installs to `%LOCALAPPDATA%\Programs\AutoScript Hub` by default and stores data under `%LOCALAPPDATA%\AutoScriptHub`. Upgrades and normal uninstallation preserve that data.

Check for updates under Settings → Client Updates (`设置 → 客户端更新`); release notes (`更新说明`) describe version changes. Important updates can show a one-time reminder on the first launch after an upgrade, and automatic reminders can be disabled. The client tries the server's release cache, explicitly configured manifest URLs, and then Gitee Releases. Installers use URLs from verified manifests, which may point to GitHub; version checks do not depend on the GitHub Releases API. LAN sources retain signature, length, and hash verification. The client does not run `git pull` or need repository tokens or SSH keys.

### 3. Keep Preview separate

Preview has its own AppId, installation directory, data root (`%LOCALAPPDATA%\AutoScriptHubPreview`), and local ports. Its default development server is `http://127.0.0.1:8765`. Online updates are disabled; independent Preview builds are installed manually. **Beta and Stable share installation and data; Beta is not an isolated test environment.** User-selected shared output folders or production servers are outside the default isolation guarantee. See [Preview installation and data isolation](docs/Preview安装与数据隔离.md).

## Development and validation

Use **Windows, Python 3.11, and Node.js 20.19+ (or 22.13+ / 24+)**. These examples run development source; they are not a production upgrade procedure.

Use a fresh source-only clone. Do not copy production `config.json`, client configuration, credentials, or business data. The backend supports loading root-level legacy configuration, so separate data paths alone do not isolate every old setting. Start clean terminals without inherited production environment variables. The following data roots are outside the repository and separate the server from the client:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt -r client\requirements.txt pytest==7.4.3 PyYAML==6.0.2
$env:DATA_DIR = Join-Path $env:LOCALAPPDATA "AutoScriptHubDev\server"
$env:DATABASE_URL = "sqlite:///" + ($env:DATA_DIR.Replace('\', '/') + "/autoscript.db")
New-Item -ItemType Directory -Force $env:DATA_DIR | Out-Null
$env:JWT_SECRET = & .\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(48))"
$env:ADMIN_USERNAME = "devadmin"
$secret = Read-Host "Development admin password (at least 12 characters)" -AsSecureString
$env:ADMIN_PASSWORD = [System.Net.NetworkCredential]::new('', $secret).Password
$env:EXTERNAL_AUTH_ENABLED = "false"
.\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
```

Startup automatically migrates and initializes the database. The password is not recorded in command history, but is passed through the server process environment; close that terminal after stopping the service.

From the repository root in another terminal, start the React development page:

```powershell
cd frontend
npm ci
npm run dev
```

Open `http://localhost:3000`. Vite proxies `/api` to `127.0.0.1:8000`. This page supports server and frontend development; running scripts still requires a Windows Agent.

To debug the source client, open another clean PowerShell terminal at the repository root:

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

In the wizard, change the server to `http://127.0.0.1:8000` and use a development account only. Completing the wizard saves credentials through DPAPI so the Agent can start without password arguments. After completing the wizard, run `python -m client.ui.main` again using the virtual environment's Python. In a separate terminal with the same two `AUTOSCRIPT_*` environment variables, run `.\.venv\Scripts\python.exe -m client.agent.main`. Never use the production client data root or run alongside another Preview using the same ports.

Validate from the repository root in the same isolated development environment:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m compileall -q backend client shared release skills
cd frontend
npm test
npm run lint
npm run build
```

Linux CI runs Python tests in `shared/tests backend/tests test/release`; validate Windows client behavior on Windows.

## Documentation

Most detailed documents are currently in Chinese.

- [Deployment, backup, restore, and upgrades](docs/0.9-deployment-runbook.md)
- [v1.2.4 release record](docs/releases/v1.2.4-发布记录.md)
- [Groups, catalog access, and revocation](docs/人员分组与脚本市场.md)
- [Preview installation and data isolation](docs/Preview安装与数据隔离.md)
- [Language support and translation maintenance](docs/多语言支持.md)
- [Gitee mirrors and updates](docs/Gitee镜像与更新.md) · [Maintaining release notes](docs/更新说明维护.md)
- [Script authoring Skill and contract](skills/autoscript-script-authoring/SKILL.md)

Validate and package scripts using an environment with the Python dependencies above:

```bash
python skills/autoscript-script-authoring/scripts/validate_script.py <script.py|script.zip>
python skills/autoscript-script-authoring/scripts/package_script.py <source> <output.zip>
```

Source map: `backend/` server, `frontend/` React, `client/` Windows execution client, `shared/` shared contracts, `deploy/` deployment, `ops/server/` operations, `release/` builds, and `skills/` script development.

## License

This project uses the [MIT License](LICENSE), permitting commercial use, modification, and distribution with copyright and license notices retained, without warranty. Third-party dependencies, bundled runtimes, and other third-party components retain their respective copyrights and licenses; this project's MIT license does not replace their terms.
