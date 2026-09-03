# Gitee 镜像与更新

项目主仓库位于 GitHub，公开镜像位于：

- `https://gitee.com/chuzifeng/auto-script_-hub`

客户端按以下顺序检查更新：

1. 用户配置的局域网或 Git Raw 签名清单；
2. Gitee Release；
3. GitHub Release。

Gitee 不可用或尚未同步新版本时会自动尝试 GitHub。无论使用哪个下载地址，客户端都会验证同一份 Ed25519 签名清单，并校验安装包长度和 SHA-256，镜像本身不属于信任根。

## 自动同步配置

GitHub 仓库已配置变量：

- `GITEE_OWNER=chuzifeng`
- `GITEE_REPO=auto-script_-hub`

还需由仓库管理员在 GitHub Actions Secrets 中添加 `GITEE_TOKEN`。Token 只需要目标 Gitee 仓库的写入及 Release 管理权限，不应写入源码、日志或客户端配置。

配置后：

- `.github/workflows/mirror-gitee.yml` 在 `main` 或版本 Tag 更新时同步代码和 Tags；
- `.github/workflows/release.yml` 创建对应 Gitee Release，上传安装包、签名清单和校验文件；
- 发布完成后匿名校验 GitHub 与 Gitee 两处资产。

## 配额说明

Gitee 开源仓库和流水线并非无限资源。当前仍保留安装包低于 `95MB` 的发布门槛，以适配 Release 附件单文件限制并预留余量。不要假设构建次数、API 请求或下载流量永远不受限制；默认保留 GitHub 与局域网更新源作为故障回退。
