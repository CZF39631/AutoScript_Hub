export const currentRelease = {
  id: 'grouped-marketplace-notifications',
  important: true,
  title: '人员分组、执行通知与更新说明',
  summary: '本次更新强化了团队脚本隔离，并补齐任务完成后的桌面提醒和版本更新说明。',
  sections: [
    {
      title: '人员分组与脚本市场',
      items: [
        '管理员可维护人员分组，并为用户和脚本配置多个分组。',
        '脚本市场、安装、执行、历史、日志和工单均实施服务端分组鉴权。',
        '升级后会自动建立默认分组，保持已有用户与脚本的可见性。',
      ],
    },
    {
      title: '执行完成通知',
      items: [
        '联网与个人本地执行完成后都会发送 Windows 桌面通知。',
        '执行失败、取消以及参数或依赖检查失败也会及时提醒。',
      ],
    },
    {
      title: '更新体验',
      items: [
        '新增更新说明页面，可随时查看本次更新和历史版本。',
        '重要更新会在升级后首次运行时提醒，也可设置为默认隐藏。',
      ],
    },
  ],
}

export const releaseHistory = [
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
