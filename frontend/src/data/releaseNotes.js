export const currentRelease = {
  id: 'v1.2.3',
  important: false,
  title: 'v1.2.3：后台更新与服务器缓存',
  summary: '更新检查和下载更加可靠，并支持服务器自动缓存客户端安装包。',
  sections: [
    {
      title: '客户端更新',
      items: [
        '版本检查仅访问当前服务器和 Gitee，避免 GitHub API 在国内网络拖慢客户端。',
        '下载安装在后台执行，本地 Agent 在下载期间持续响应。',
        '修复检查完成后刷新页面仍显示“尚未检查”的状态问题。',
        '支持本地 Review 版本完整验证更新链路，无需提前发布线上 Beta。',
      ],
    },
    {
      title: '服务器更新缓存',
      items: [
        '服务器可在启动后及每 6 小时检查 GitHub Release，验签并缓存 Stable/Beta 安装包。',
        '管理员可通过 API 配置服务器出站代理、检查周期和 GitHub 仓库。',
        '客户端优先从当前服务器缓存下载，失败时自动回退公开下载源。',
        '新发布不再生成 Gitee 安装包分卷，Gitee 仅镜像签名更新清单。',
      ],
    },
    {
      title: '界面',
      items: [
        '应用新的 Air Hub 图标，并统一网页、客户端、更新器、安装器和快捷方式图标。',
      ],
    },
  ],
}

export const releaseHistory = [
  {
    id: 'v1.2.3-beta.2',
    version: '1.2.3-beta.2',
    title: '更新状态修复预览版',
    summary: '修复检查完成状态，并支持本地 Review 更新测试版本。',
    sections: [],
  },
  {
    id: 'v1.2.3-beta.1',
    version: '1.2.3-beta.1',
    title: '异步更新下载预览版',
    summary: '更新检查仅访问 Gitee，下载安装改为后台任务。',
    sections: [],
  },
  {
    id: 'v1.2.2',
    version: '1.2.2',
    title: '可靠冷更新与审计修复',
    summary: '完善国内分卷更新、断点续传和更新缓存，并恢复操作审计列表显示。',
    sections: [],
  },
  {
    id: 'v1.2.0',
    version: '1.2.0',
    title: '分组市场、执行通知与国内更新源',
    summary: '强化团队脚本隔离，补齐任务完成提醒和更新说明，并提升国内更新下载体验。',
    sections: [],
  },
  {
    id: 'v1.1.0',
    version: '1.1.0',
    title: '企业认证与用户管理增强',
    summary: '增加可配置外部认证、凭据安全保存以及完整的用户生命周期管理。',
    sections: [
      {
        title: '主要更新',
        items: [
          '支持 HTTP Form、HTTP JSON 等外部认证适配方式。',
          '客户端可使用 Windows DPAPI 安全保存登录凭据。',
          '用户管理支持搜索、角色调整、启停用和软删除。',
        ],
      },
    ],
  },
  {
    id: 'v1.0.0',
    version: '1.0.0',
    title: '首个稳定版本',
    summary: '提供团队脚本市场、Windows 客户端、执行历史、实时日志与签名更新能力。',
    sections: [],
  },
]
