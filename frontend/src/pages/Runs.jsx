import { useCallback, useEffect, useState, useMemo, useRef } from 'react'
import { Table, Tag, Button, Select, DatePicker, Space, message, Tooltip } from 'antd'
import { FolderOpenOutlined, ReloadOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import api from '../api/client'
import { useAuth } from '../contexts/AuthContext'
import { useConnection } from '../contexts/ConnectionContext'
import { canOpenResultLocally, firstResultPath, loadRunList } from '../api/offlineData'

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
  const { online, agentOnline, agentId, localApi } = useConnection()

  const isAdmin = user?.role === 'admin' || user?.role === 'developer'

  const load = useCallback(() => {
    setLoading(true)
    const params = new URLSearchParams()
    if (statusFilter) params.set('status', statusFilter)
    if (userFilter) params.set('user_id', userFilter)
    if (dateRange && dateRange[0]) params.set('date_from', dateRange[0].startOf('day').toISOString())
    if (dateRange && dateRange[1]) params.set('date_to', dateRange[1].endOf('day').toISOString())
    loadRunList({ online, api, localApi, query: params.toString() }).then(data => {
      let result = data
      if (!online && statusFilter) result = result.filter(r => r.status === statusFilter)
      setRuns(result)
    })
      .catch(() => message.error('加载失败')).finally(() => setLoading(false))
  }, [online, localApi, statusFilter, userFilter, dateRange])

  useEffect(() => {
    if (isAdmin) {
      api.get('/api/runs/filter-options/users').then(r => setUsers(r.data)).catch(() => {})
    }
  }, [isAdmin])

  useEffect(load, [load])

  const hasAlive = useMemo(() => runs.some(r => r.status === 'pending' || r.status === 'running'), [runs])

  // Track previous statuses so we can fire a toast when a run finishes.
  const prevStatusRef = useRef({})

  useEffect(() => {
    runs.forEach(r => {
      const prev = prevStatusRef.current[r.id]
      // Only fire if we previously saw it as pending/running and now it's terminal
      if (prev && (prev === 'pending' || prev === 'running') &&
          (r.status === 'success' || r.status === 'failed')) {
        if (r.status === 'success') {
          message.success(`${r.script_name || '脚本'} 执行完成`)
        } else {
          message.error(`${r.script_name || '脚本'} 执行失败`)
        }
      }
      prevStatusRef.current[r.id] = r.status
    })
  }, [runs])

  // Auto-refresh while any run is alive (design §5.5 web notification)
  useEffect(() => {
    if (!hasAlive) return
    const interval = setInterval(load, 5000)
    return () => clearInterval(interval)
  }, [hasAlive, load])

  const openLocalResult = async (run) => {
    try {
      const path = firstResultPath(run.result_files)
      if (!path) throw new Error('没有可打开的结果路径')
      await localApi.post('/local/results/open', { path })
    } catch (error) {
      message.error(error.response?.data?.error || error.message || '打开失败')
    }
  }

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
            canOpenResultLocally(r, agentOnline, agentId) ? (
              <Tooltip title="在执行客户端打开结果文件">
                <Button type="link" icon={<FolderOpenOutlined />} onClick={() => openLocalResult(r)} />
              </Tooltip>
            ) : <Tooltip title="结果保存在执行客户端"><span>本地结果</span></Tooltip>
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
