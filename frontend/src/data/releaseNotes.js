export const currentRelease = {
  id: 'v1.2.2',
  important: false,
  title: 'v1.2.2：可靠冷更新与审计修复',
  summary: '完善国内分卷更新、断点续传和更新缓存，并恢复操作审计列表显示。',
  sections: [
    {
      title: '更新体验',
      items: [
        '发现新版本后持久化保存已验证的签名清单，刷新或重启客户端后可直接继续下载安装。',
        '更新源暂时不可用时保留已发现版本，后台后续检查仍可替换为更高版本。',
        '安装包优先从 Gitee 分卷下载，支持流式重试、安全续传、逐卷校验和 GitHub 完整包兜底。',
        '检查更新可等待 Gitee、GitHub 等外部更新源完成响应，不再于 10 秒后误报失败。',
      ],
    },
    {
      title: '操作审计',
      items: [
        '修复审计接口序列化失败导致操作审计页面显示为空的问题。',
        '审计日志加载失败时显示明确错误，不再伪装成空列表。',
      ],
    },
    {
      title: '运维兼容性',
      items: [
        '修复 Windows 维护电脑发起远程服务器升级时的 Shell 换行与标准输入兼容问题。',
      ],
    },
  ],
}

export const releaseHistory = [
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
