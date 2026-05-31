import React, { useEffect, useState, useMemo } from 'react'
import { Table, Tag, Button, Select, DatePicker, Space, message, Tooltip } from 'antd'
import { FolderOpenOutlined, ReloadOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import api from '../api/client'
import { useAuth } from '../contexts/AuthContext'

const { RangePicker } = DatePicker

const statusMap = {
  pending: { color: 'blue', text: '等待中' },
  running: { color: 'orange', text: '执行中' },
  success: { color: 'green', text: '成功' },
  failed: { color: 'red', text: '失败' },
  cancelled: { color: 'default', text: '已取消' },
}

const statusOptions = Object.entries(statusMap).map(([k, v]) => ({ label: v.text, value: k }))

export default function Runs() {
  const [runs, setRuns] = useState([])
  const [loading, setLoading] = useState(true)
  const [users, setUsers] = useState([])
  const [statusFilter, setStatusFilter] = useState(undefined)
  const [userFilter, setUserFilter] = useState(undefined)
  const [dateRange, setDateRange] = useState(null)
  const nav = useNavigate()
  const { user } = useAuth()

  const isAdmin = user?.role === 'admin' || user?.role === 'developer'

  const load = () => {
    setLoading(true)
    const params = new URLSearchParams()
    if (statusFilter) params.set('status', statusFilter)
    if (userFilter) params.set('user_id', userFilter)
    if (dateRange && dateRange[0]) params.set('date_from', dateRange[0].startOf('day').toISOString())
    if (dateRange && dateRange[1]) params.set('date_to', dateRange[1].endOf('day').toISOString())
    api.get(`/api/runs?${params.toString()}`).then(r => setRuns(r.data))
      .catch(() => message.error('加载失败')).finally(() => setLoading(false))
  }

  useEffect(() => {
    if (isAdmin) {
      api.get('/api/runs/filter-options/users').then(r => setUsers(r.data)).catch(() => {})
    }
  }, [isAdmin])

  useEffect(load, [statusFilter, userFilter, dateRange])

  const hasAlive = useMemo(() => runs.some(r => r.status === 'pending' || r.status === 'running'), [runs])

  const columns = [
    { title: 'ID', dataIndex: 'id', key: 'id', width: 55 },
    {
      title: '脚本', key: 'script', width: 150, ellipsis: true,
      render: (_, r) => (
        <Button type="link" style={{ padding: 0 }} onClick={() => nav(`/scripts/${r.script_id}`)}>
          {r.script_name || `#${r.script_id}`}
        </Button>
      )
    },
    { title: '版本', dataIndex: 'script_version', key: 'ver', width: 55 },
    ...(isAdmin ? [{ title: '执行人', dataIndex: 'username', key: 'user', width: 90 }] : []),
    {
      title: '状态', dataIndex: 'status', key: 'status', width: 80,
      render: (s) => { const m = statusMap[s] || { color: 'default', text: s }; return <Tag color={m.color}>{m.text}</Tag> }
    },
    {
      title: '耗时', dataIndex: 'duration_sec', key: 'dur', width: 70,
      render: (v) => v != null ? `${v}s` : '-'
    },
    {
      title: '创建时间', dataIndex: 'created_at', key: 'time', width: 160,
      render: (t) => t ? new Date(t).toLocaleString() : '-'
    },
    {
      title: '操作', key: 'action', width: 110,
      render: (_, r) => (
        <Space>
          <Button type="link" onClick={() => nav(`/runs/${r.id}`)}>详情</Button>
          {r.result_files && (
            <Tooltip title="打开结果文件">
              <Button type="link" icon={<FolderOpenOutlined />} onClick={() => {
                api.post(`/api/runs/${r.id}/open-result`).catch(e => message.error(e.response?.data?.detail || '打开失败'))
              }} />
            </Tooltip>
          )}
        </Space>
      )
    },
  ]

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <h2 style={{ margin: 0 }}>执行历史{hasAlive ? ' (自动刷新中...)' : ''}</h2>
        <Space>
          <Button size="small" onClick={() => { setStatusFilter(undefined); setUserFilter(undefined); setDateRange(null) }}>重置筛选</Button>
          <Button icon={<ReloadOutlined />} onClick={load}>刷新</Button>
        </Space>
      </div>

      <Space style={{ marginBottom: 16 }} wrap>
        <Select placeholder="状态" value={statusFilter} onChange={setStatusFilter}
          options={statusOptions} style={{ width: 120 }} allowClear />
        {isAdmin && (
          <Select placeholder="执行人" value={userFilter} onChange={setUserFilter}
            options={users.map(u => ({ label: u.name, value: u.id }))} style={{ width: 130 }} allowClear />
        )}
        <RangePicker value={dateRange} onChange={setDateRange} placeholder={['开始日期', '结束日期']} />
      </Space>

      <Table dataSource={runs} columns={columns} rowKey="id" loading={loading}
        size="small" pagination={{ pageSize: 20 }} />
    </div>
  )
}
