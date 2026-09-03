export const currentRelease = {
  id: 'v1.2.1-beta.1',
  important: false,
  title: 'v1.2.1-beta.1：客户端更新超时修复',
  summary: '修复网络较慢时检查更新被本地接口 10 秒超时提前中断的问题。',
  sections: [
    {
      title: '更新体验',
      items: [
        '检查更新可等待 Gitee、GitHub 等外部更新源完成响应，不再于 10 秒后误报失败。',
        '下载安装不再受前端请求超时限制，仍由 Agent 网络超时、签名校验和更新状态机保障安全。',
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
