# AutoScript Hub 项目维护约定

## 基本原则

- 默认使用中文回复、提交说明和维护文档。
- 开始修改前执行 `git status --short --branch`，从 `main` 创建独立分支。
- 不修改、不清理、不暂存、不提交根目录的 `tmp/`；它包含本地测试数据。
- 只提交当前任务相关文件，合并和推送前再次检查工作区。
- 不在跟踪文件中写入企业认证地址、内网地址、账号、密码、Token、角色映射或部门信息。
- 服务端私有配置只保存在远程 `deploy/.env`；维护电脑的连接参数保存在已忽略的 `ops/server/remote-upgrade.env`。

## 纯 UI 改动的交付约定

- 文案、样式、布局、提示、下拉定位、文本选择等不涉及客户端能力变化的交互调整，默认走前端资源更新，不通过重新打包或发布客户端交付；不要仅为这类改动提升客户端版本或要求用户重装。
- 先确认实际页面资源来自哪里：浏览器访问的服务端页面更新服务端静态资源；桌面客户端内置页面更新对应客户端的前端资源。仅更新服务端不能宣称桌面内置界面已更新。
- 更新流程：在隔离快照中构建和验证 → 确认目标实例与版本 → 备份原资源 → 更新前端资源 → 按需刷新或正常重开界面 → 核实实际加载的新资源。保留回滚依据，不改配置、凭据、业务数据，不强制中断任务或误操作其他实例。
- 本机 review 可采用已验证的前端资源热更新；推广到正式环境仍需对应授权和可验证、可回滚的交付方式。不得修改已公开的 Tag、Release 安装包或签名资产，也不把本机热更新说成所有客户端已更新。
- 只有涉及 Agent、原生桥接、Python 运行时、依赖、安装器、协议兼容或新增客户端能力时，才评估客户端升级；涉及后端接口则另行评估服务端部署。区分“纯 UI”与“客户端能力”后再选择交付方式。

## 当前稳定基线

- 当前正式版本：`v1.2.4`。
- `v1.2.4` Tag 指向提交 `461c7c1519bfc6946a171f7f1fce689330dfaed5`，不得移动。
- `1.2.4` 的恢复发布流程与 Windows 测试依赖修复位于 Tag 之后的 `main`；正式资产仍从冻结 Tag 构建，不回写 Tag。发布记录见 `docs/releases/v1.2.4-发布记录.md`。
- 公司服务端已运行 `1.2.4` stable，数据库迁移版本为 `0005_server_settings`；容器、内网健康检查与 SQLite 完整性已验证，公网健康入口尚未明确配置。
- GitHub 是发布资产和签名安装包的真源；Gitee 是代码、Tag、更新清单、部署包和 Skill 镜像，不是信任根。

## 发布流程

1. 合并并推送 `main`，等待主分支 CI 全部通过。
2. Gitee Release API 或发布流程有变化时，先手动运行 `.github/workflows/gitee-release-smoke.yml`；不得直接用正式 Tag 反复试错。
3. 确认目标 Tag 尚无公开 Release，再从已验收提交创建版本 Tag。
4. `.github/workflows/release.yml` 负责：
   - 重跑 CI；
   - 构建 Windows 安装包；
   - 构建并冒烟验证 `linux/amd64`、`linux/arm64` 镜像；
   - 生成部署包、Skill、签名更新清单和 SHA-256；
   - 发布 GitHub Release 和 Gitee Release。
5. 发布后必须验证：Release 非 draft/非 prerelease、Tag 指向、资产列表、`SHA256SUMS.txt`、签名清单、匿名下载和双架构镜像。
6. 正式 Tag 和 Release 一旦公开，不再移动 Tag 或替换资产；修复使用新版本号。

### Gitee 已确认的 API 约束

- 创建 Release 必须提供 `tag_name`、`name`、`body` 和 `target_commitish`。
- 更新 Release 不能只提交 `prerelease`；必须同时保留 `tag_name`、`name` 和 `body`。
- GitHub 托管 Runner 向 Gitee 上传 30MB 级安装包长期不稳定，因此当前不镜像 EXE。
- Gitee Release 镜像部署包、Skill、签名清单、签名和校验文件；清单中的安装包 URL 指向 GitHub。
- 客户端仍优先从 Gitee 获取签名清单，失败时回退 GitHub，并始终验证 Ed25519、文件长度和 SHA-256。

## 服务器升级流程

- 不再临时猜测 SSH 用户、私钥、Compose 路径或数据目录。
- 首次复制 `ops/server/remote-upgrade.env.example` 为 `ops/server/remote-upgrade.env` 并填写本机配置；真实配置不得提交。
- 正式镜像发布并验证后，从维护电脑运行：

```bash
python ops/server/remote_upgrade.py --version <目标版本>
```

- 脚本固定执行：配置检查、SSH 检查、运维包 SHA-256 校验、升级前健康检查、`.env` 备份、SQLite 在线备份、镜像拉取、容器重建、迁移和连续健康检查。
- 拉取、重建或就绪检查失败时必须回滚旧数据库和旧不可变镜像，并恢复原 `.env`。
- Windows 发起升级时必须以二进制 stdin 发送远程 Shell，并在打包时把 `.sh` 转为 LF；不要恢复 `text=True` 或直接打包 CRLF Shell 文件。
- 升级成功后验证内网和公网 `/api/health/ready`，版本、渠道、`database`、`data_dir`、`migration`、容器健康状态和 SQLite `integrity_check`。

## 常用验证

```bash
python -m pytest -q
cd frontend
npm test
npm run lint
npm run build
```

发布相关改动还应运行：

```bash
python -m pytest -q test/release
python -m compileall -q backend client shared release skills
```

完整运维说明见 `docs/0.9-deployment-runbook.md`，Gitee 更新策略见 `docs/Gitee镜像与更新.md`。
