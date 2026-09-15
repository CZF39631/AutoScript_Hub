import { useCallback, useEffect, useState, useMemo, useRef } from 'react'
import { Table, Tag, Button, Select, DatePicker, Space, message, Tooltip } from 'antd'
import { FolderOpenOutlined, ReloadOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import api from '../api/client'
import { useAuth } from '../contexts/AuthContext'
import { useConnection } from '../contexts/ConnectionContext'
import { canOpenResultLocally, firstResultPath, loadRunList } from '../api/offlineData'
import { formatScriptVersion } from '../utils/scriptVersion'
import { formatServerTime } from '../utils/dateTime'
import { useI18n } from '../i18n/useI18n'

const { RangePicker } = DatePicker
const statusColors = { pending: 'blue', running: 'orange', success: 'green', failed: 'red', cancelled: 'default', queued: 'blue', claimed: 'processing', preparing: 'processing', cancel_requested: 'orange', unknown: 'warning', skipped: 'default' }
const buttonStyle = { whiteSpace: 'normal', height: 'auto', minHeight: 32, paddingBlock: 4 }

export default function Runs() {
  const { t } = useI18n()
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
  const statusOptions = Object.keys(statusColors).map(value => ({ label: t(`execution.runState.${value}`), value }))

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
    }).catch(() => message.error(t('execution.loadFailed'))).finally(() => setLoading(false))
  }, [online, localApi, statusFilter, userFilter, dateRange, t])

  useEffect(() => {
    if (isAdmin) api.get('/api/runs/filter-options/users').then(r => setUsers(r.data)).catch(() => {})
  }, [isAdmin])
  useEffect(load, [load])
  const hasAlive = useMemo(() => runs.some(r => ['pending', 'queued', 'claimed', 'preparing', 'running', 'cancel_requested', 'unknown'].includes(r.status)), [runs])
  const prevStatusRef = useRef({})
  useEffect(() => {
    runs.forEach(r => {
      const prev = prevStatusRef.current[r.id]
      if (prev && (prev === 'pending' || prev === 'running') && (r.status === 'success' || r.status === 'failed')) {
        const text = t(r.status === 'success' ? 'execution.runCompleted' : 'execution.runFailed', { name: r.script_name || t('execution.script') })
        if (r.status === 'success') message.success(text)
        else message.error(text)
      }
      prevStatusRef.current[r.id] = r.status
    })
  }, [runs, t])
  useEffect(() => {
    if (!hasAlive) return
    const interval = setInterval(load, 5000)
    return () => clearInterval(interval)
  }, [hasAlive, load])
  const openLocalResult = async run => {
    try {
      const path = firstResultPath(run.result_files)
      if (!path) throw new Error(t('execution.noResultPath'))
      await localApi.post('/local/results/open', { path })
    } catch (error) {
      const detail = error.response?.data?.error
      message.error(typeof detail === 'string' ? detail : error.message || t('execution.openFailed'))
    }
  }
  const columns = [
    { title: t('execution.id'), dataIndex: 'id', key: 'id', width: 55 },
    { title: t('execution.script'), key: 'script', width: 150, ellipsis: true, render: (_, r) => <Button type="link" style={{ padding: 0, ...buttonStyle }} onClick={() => nav(`/scripts/${r.script_id}`)}>{r.script_name || `#${r.script_id}`}</Button> },
    { title: t('execution.version'), key: 'ver', width: 85, render: (_, r) => formatScriptVersion(r.script_semantic_version, r.script_version) },
    ...(isAdmin ? [{ title: t('execution.executor'), dataIndex: 'username', key: 'user', width: 90 }] : []),
    { title: t('execution.status'), dataIndex: 'status', key: 'status', width: 80, render: s => <Tag color={statusColors[s] || 'default'}>{Object.hasOwn(statusColors, s) ? t(`execution.runState.${s}`) : s}</Tag> },
    { title: t('execution.duration'), dataIndex: 'duration_sec', key: 'dur', width: 70, render: v => v != null ? t('execution.seconds', { value: v }) : '-' },
    { title: t('execution.createdAt'), dataIndex: 'created_at', key: 'time', width: 160, render: formatServerTime },
    { title: t('execution.actions'), key: 'action', width: 110, render: (_, r) => <Space wrap>
      <Button type="link" style={buttonStyle} onClick={() => nav(`/runs/${r.id}`)}>{t('execution.details')}</Button>
      {r.result_files && (canOpenResultLocally(r, agentOnline, agentId) ? <Tooltip title={t('execution.openOnExecutor')}><Button type="link" aria-label={t('execution.openOnExecutor')} icon={<FolderOpenOutlined />} onClick={() => openLocalResult(r)} /></Tooltip> : <Tooltip title={t('execution.resultOnExecutor')}><span>{t('execution.localResult')}</span></Tooltip>)}
    </Space> },
  ]
  return <div>
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16, flexWrap: 'wrap', gap: 8 }}>
      <h2 style={{ margin: 0 }}>{t('execution.history')}{hasAlive ? t('execution.autoRefreshing') : ''}</h2>
      <Space wrap><Button style={buttonStyle} size="small" onClick={() => { setStatusFilter(undefined); setUserFilter(undefined); setDateRange(null) }}>{t('execution.resetFilters')}</Button><Button style={buttonStyle} icon={<ReloadOutlined />} onClick={load}>{t('execution.refresh')}</Button></Space>
    </div>
    <Space style={{ marginBottom: 16 }} wrap>
      <Select placeholder={t('execution.status')} value={statusFilter} onChange={setStatusFilter} options={statusOptions} style={{ minWidth: 120 }} allowClear />
      {isAdmin && <Select placeholder={t('execution.executor')} value={userFilter} onChange={setUserFilter} options={users.map(u => ({ label: u.name, value: u.id }))} style={{ minWidth: 130 }} allowClear />}
      <RangePicker value={dateRange} onChange={setDateRange} placeholder={[t('execution.startDate'), t('execution.endDate')]} />
    </Space>
    <Table dataSource={runs} columns={columns} rowKey="id" loading={loading} size="small" pagination={{ pageSize: 20 }} />
  </div>
}
