import { useEffect, useState } from 'react'
import { App as AntdApp, Button, Table, Input, Select, Space, Tag } from 'antd'
import { useSearchParams } from 'react-router-dom'
import api from '../api/client'
import { formatServerTime } from '../utils/dateTime'

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
  delete_user: '删除用户',
  'managed_thumbnail.view': '查看托管设备画面',
}

const actionOptions = Object.entries(actionLabels).map(([k, v]) => ({ label: v, value: k }))

export default function AuditLog() {
  const { message } = AntdApp.useApp()
  const [searchParams, setSearchParams] = useSearchParams()
  const [logs, setLogs] = useState([])
  const [loading, setLoading] = useState(true)
  const [action, setAction] = useState(searchParams.get('action') || undefined)
  const [username, setUsername] = useState('')
  const targetType = searchParams.get('target_type') || ''
  const targetId = searchParams.get('target_id') || ''
  const activeTargetName = logs.find(log =>
    String(log.target_id) === targetId && log.target_type === targetType && log.target_name
  )?.target_name

  const clearTargetFilter = () => {
    const next = new URLSearchParams(searchParams)
    next.delete('target_type')
    next.delete('target_id')
    setSearchParams(next, { replace: true })
  }

  const load = () => {
    setLoading(true)
    const params = new URLSearchParams()
    if (action) params.set('action', action)
    if (username) params.set('username', username)
    if (targetType) params.set('target_type', targetType)
    if (targetId) params.set('target_id', targetId)
    params.set('limit', '200')
    api.get(`/api/audit?${params.toString()}`)
      .then(r => setLogs(r.data))
      .catch(error => message.error(error.response?.data?.detail || '加载审计日志失败'))
      .finally(() => setLoading(false))
  }

  useEffect(load, [action, message, username, searchParams, targetId, targetType])

  const columns = [
    { title: '时间', dataIndex: 'created_at', key: 'time', width: 170,
      render: formatServerTime },
    { title: '用户', dataIndex: 'username', key: 'user', width: 100 },
    { title: '操作', dataIndex: 'action', key: 'action', width: 110,
      render: (a) => actionLabels[a] || a },
    { title: '对象', key: 'target', width: 180,
      render: (_, r) => r.target_type
        ? r.target_name
          ? `${r.target_name}（${r.target_type} #${r.target_id}）`
          : `${r.target_type} #${r.target_id}`
        : '-' },
    { title: '详情', dataIndex: 'detail', key: 'detail', ellipsis: true },
    { title: 'IP', dataIndex: 'ip_address', key: 'ip', width: 130 },
  ]

  return (
    <div>
      <h2>操作审计</h2>
      <Space className="filter-toolbar" wrap>
        <Select placeholder="操作类型" value={action} onChange={setAction}
          options={actionOptions} style={{ width: 150 }} allowClear />
        <Input placeholder="用户名" value={username}
          onChange={e => setUsername(e.target.value)} style={{ width: 150 }} allowClear />
        {targetType && targetId && (
          <div className="audit-target-filter" role="status" aria-label="当前对象筛选">
            <span>当前对象</span>
            <Tag color="blue">{activeTargetName || targetType} #{targetId}</Tag>
            <Button size="small" onClick={clearTargetFilter}>清除对象筛选</Button>
          </div>
        )}
      </Space>
      <Table dataSource={logs} columns={columns} rowKey="id" loading={loading}
        size="small" pagination={{ pageSize: 20 }} />
    </div>
  )
}
