export const currentRelease = {
  id: 'v1.2.3-beta.2',
  important: false,
  title: 'v1.2.3-beta.2：更新状态修复预览版',
  summary: '修复检查完成后仍显示“尚未检查”，并支持不发布到线上的本地 Review 更新测试版本。',
  sections: [
    {
      title: '更新状态',
      items: [
        '检查完成且暂无可用更新时持久化最新版本，刷新页面后仍正确显示“当前已是最新版本”。',
        '支持 1.2.2-review.1 等本地 Review 版本参与更新比较，无需发布线上 Beta 即可验证更新链路。',
        '构建测试不再向开发电脑发送模拟脚本失败的真实系统通知。',
      ],
    },
    {
      title: 'Beta.1 更新流程',
      items: [
        '版本检查仅访问 Gitee Release，GitHub 完整安装包仅作为下载阶段的最终兜底。',
        '下载安装在后台执行，本地 Agent 在下载期间保持响应。',
        '验证完成后由独立 AutoScriptUpdater.exe 静默安装、重启和回滚。',
      ],
    },
  ],
}

export const releaseHistory = [
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
