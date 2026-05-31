import React, { useEffect, useState } from 'react'
import { Table, Input, Select, Space } from 'antd'
import api from '../api/client'

const actionLabels = {
  login: '登录',
  login_failed: '登录失败',
  logout: '登出',
  upload_script: '上传脚本',
  upload_version: '上传版本',
  disable_script: '禁用脚本',
  enable_script: '启用脚本',
  execute_script: '执行脚本',
  cancel_run: '取消执行',
  create_user: '创建用户',
  update_user: '修改用户',
}

const actionOptions = Object.entries(actionLabels).map(([k, v]) => ({ label: v, value: k }))

export default function AuditLog() {
  const [logs, setLogs] = useState([])
  const [loading, setLoading] = useState(true)
  const [action, setAction] = useState(undefined)
  const [username, setUsername] = useState('')

  const load = () => {
    setLoading(true)
    const params = new URLSearchParams()
    if (action) params.set('action', action)
    if (username) params.set('username', username)
    params.set('limit', '200')
    api.get(`/api/audit?${params.toString()}`).then(r => setLogs(r.data)).finally(() => setLoading(false))
  }

  useEffect(load, [action, username])

  const columns = [
    { title: '时间', dataIndex: 'created_at', key: 'time', width: 170,
      render: (t) => t ? new Date(t).toLocaleString() : '-' },
    { title: '用户', dataIndex: 'username', key: 'user', width: 100 },
    { title: '操作', dataIndex: 'action', key: 'action', width: 110,
      render: (a) => actionLabels[a] || a },
    { title: '对象', key: 'target', width: 100,
      render: (_, r) => r.target_type ? `${r.target_type} #${r.target_id}` : '-' },
    { title: '详情', dataIndex: 'detail', key: 'detail', ellipsis: true },
    { title: 'IP', dataIndex: 'ip_address', key: 'ip', width: 130 },
  ]

  return (
    <div>
      <h2>操作审计</h2>
      <Space style={{ marginBottom: 16 }}>
        <Select placeholder="操作类型" value={action} onChange={setAction}
          options={actionOptions} style={{ width: 150 }} allowClear />
        <Input placeholder="用户名" value={username}
          onChange={e => setUsername(e.target.value)} style={{ width: 150 }} allowClear />
      </Space>
      <Table dataSource={logs} columns={columns} rowKey="id" loading={loading}
        size="small" pagination={{ pageSize: 20 }} />
    </div>
  )
}
