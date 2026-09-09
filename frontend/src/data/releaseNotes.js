export const currentRelease = {
  id: 'v1.2.4',
  important: false,
  title: 'v1.2.4：本地端口冲突修复',
  summary: '客户端界面端口被其他软件占用时自动选择备用端口。',
  sections: [
    {
      title: '客户端',
      items: [
        '本地 UI 默认端口 18081 不可用时，自动尝试 18082 至 18090。',
        '同步支持 UI 与 Agent 的备用端口，端口冲突时仍可正常启动和通信。',
        '客户端自动发现 Agent；Agent 意外退出后自动尝试重启并恢复连接。',
        '内置 Python 环境默认使用清华 PyPI 镜像，提升国内网络下的依赖安装成功率。',
      ],
    },
  ],
}

export const releaseHistory = [
  {
    id: 'v1.2.3',
    version: '1.2.3',
    title: '后台更新与服务器缓存',
    summary: '更新检查和下载更加可靠，并支持服务器自动缓存客户端安装包。',
    sections: [],
  },
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
