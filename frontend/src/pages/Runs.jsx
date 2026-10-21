import { useCallback, useEffect, useState, useMemo, useRef } from 'react'
import { Table, Tag, Button, Select, DatePicker, InputNumber, Space, message, Tooltip } from 'antd'
import { FolderOpenOutlined, ReloadOutlined } from '@ant-design/icons'
import { useNavigate, useSearchParams } from 'react-router-dom'
import api from '../api/client'
import { useAuth } from '../contexts/AuthContext'
import { useConnection } from '../contexts/ConnectionContext'
import { canOpenResultLocally, firstResultPath, loadRunList } from '../api/offlineData'
import { formatScriptVersion } from '../utils/scriptVersion'
import { formatServerTime } from '../utils/dateTime'
import usePageFocused from '../hooks/usePageFocused'
import {
  buildRunQuery, dispatchTypeOptions, parseRunFilterParams, refreshDelay, runDeviceName,
} from '../utils/runHistory'

const { RangePicker } = DatePicker

const statusMap = {
  pending: { color: 'blue', text: '等待中' },
  running: { color: 'orange', text: '执行中' },
  success: { color: 'green', text: '成功' },
  failed: { color: 'red', text: '失败' },
  cancelled: { color: 'default', text: '已取消' },
  expired: { color: 'default', text: '已过期' },
}

const statusOptions = Object.entries(statusMap).map(([k, v]) => ({ label: v.text, value: k }))

export default function Runs() {
  const [runs, setRuns] = useState([])
  const [loading, setLoading] = useState(true)
  const [users, setUsers] = useState([])
  const [agents, setAgents] = useState([])
  const [searchParams, setSearchParams] = useSearchParams()
  const [statusFilter, setStatusFilter] = useState(undefined)
  const [userFilter, setUserFilter] = useState(undefined)
  const [agentFilter, setAgentFilter] = useState(() => parseRunFilterParams(searchParams).agentId)
  const [scheduleFilter, setScheduleFilter] = useState(() => parseRunFilterParams(searchParams).scheduleId)
  const [dispatchFilter, setDispatchFilter] = useState(() => parseRunFilterParams(searchParams).dispatchType)
  const [dateRange, setDateRange] = useState(null)
  const nav = useNavigate()
  const { user } = useAuth()
  const { online, agentOnline, agentId, localApi } = useConnection()
  const pageFocused = usePageFocused()

  const isAdmin = user?.role === 'admin' || user?.role === 'developer'

  const load = useCallback(({ quiet = false } = {}) => {
    if (!quiet) setLoading(true)
    const params = buildRunQuery({
      status: statusFilter,
      userId: userFilter,
      agentId: agentFilter,
      scheduleId: scheduleFilter,
      dispatchType: dispatchFilter,
      dateFrom: dateRange?.[0]?.startOf('day').toISOString(),
      dateTo: dateRange?.[1]?.endOf('day').toISOString(),
    })
    loadRunList({ online, api, localApi, query: params.toString() }).then(data => {
      let result = data
      if (!online && statusFilter) result = result.filter(r => r.status === statusFilter)
      if (!online && agentFilter) result = result.filter(r => String(r.agent_id) === String(agentFilter))
      setRuns(result)
    })
      .catch(() => { if (!quiet) message.error('加载失败') })
      .finally(() => { if (!quiet) setLoading(false) })
  }, [online, localApi, statusFilter, userFilter, agentFilter, scheduleFilter, dispatchFilter, dateRange])

  useEffect(() => {
    if (isAdmin) {
      Promise.allSettled([
        api.get('/api/runs/filter-options/users'),
        api.get('/api/agents'),
      ]).then(([userResult, agentResult]) => {
        if (userResult.status === 'fulfilled') setUsers(userResult.value.data || [])
        if (agentResult.status === 'fulfilled') setAgents(agentResult.value.data || [])
      })
    }
  }, [isAdmin])

  useEffect(() => { load() }, [load])

  useEffect(() => {
    const query = buildRunQuery({
      status: statusFilter,
      userId: userFilter,
      agentId: agentFilter,
      scheduleId: scheduleFilter,
      dispatchType: dispatchFilter,
      dateFrom: dateRange?.[0]?.startOf('day').toISOString(),
      dateTo: dateRange?.[1]?.endOf('day').toISOString(),
    })
    if (query.toString() !== searchParams.toString()) setSearchParams(query, { replace: true })
  }, [statusFilter, userFilter, agentFilter, scheduleFilter, dispatchFilter, dateRange, searchParams, setSearchParams])

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

  // Active work refreshes quickly only while this page has focus.
  useEffect(() => {
    const timer = setInterval(
      () => load({ quiet: true }),
      refreshDelay({ hasActive: hasAlive, isFocused: pageFocused }),
    )
    return () => clearInterval(timer)
  }, [hasAlive, load, pageFocused])

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
    { title: '版本', key: 'ver', width: 85, render: (_, r) => formatScriptVersion(r.script_semantic_version, r.script_version) },
    ...(isAdmin ? [
      { title: '执行人', dataIndex: 'username', key: 'user', width: 90 },
      {
        title: '来源', dataIndex: 'dispatch_type', key: 'source', width: 100,
        render: value => ({ standard: '手工执行', managed_manual: '管理端下发', managed_schedule: '托管计划' }[value] || value || '-'),
      },
      {
        title: '设备', key: 'target', width: 130, ellipsis: true,
        render: (_, record) => runDeviceName(record),
      },
    ] : []),
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
      render: formatServerTime
    },
    {
      title: '操作', key: 'action', width: 110,
      render: (_, r) => (
        <Space>
          <Button type="link" onClick={() => nav(`/runs/${r.id}`)}>详情</Button>
          {(r.has_result_files || r.result_files) && (
            canOpenResultLocally(r, agentOnline, agentId) && r.result_files ? (
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
          <Button size="small" onClick={() => {
            setStatusFilter(undefined)
            setUserFilter(undefined)
            setAgentFilter(undefined)
            setScheduleFilter(undefined)
            setDispatchFilter(undefined)
            setDateRange(null)
          }}>重置筛选</Button>
          <Button icon={<ReloadOutlined />} onClick={load}>刷新</Button>
        </Space>
      </div>

      <Space style={{ marginBottom: 16 }} wrap>
        <Select placeholder="状态" value={statusFilter} onChange={setStatusFilter}
          options={statusOptions} style={{ width: 120 }} allowClear />
        {isAdmin && (
          <>
            <Select placeholder="执行人" value={userFilter} onChange={setUserFilter}
              options={users.map(u => ({ label: u.name, value: u.id }))} style={{ width: 130 }} allowClear />
            <Select
              showSearch
              optionFilterProp="label"
              placeholder="设备"
              value={agentFilter}
              onChange={setAgentFilter}
              options={agents.map(agent => ({ label: agent.machine_name, value: agent.id }))}
              style={{ width: 160 }}
              allowClear
            />
            <InputNumber
              min={1}
              precision={0}
              placeholder="计划 ID"
              value={scheduleFilter}
              onChange={value => setScheduleFilter(value || undefined)}
              style={{ width: 110 }}
            />
            <Select
              placeholder="任务来源"
              value={dispatchFilter}
              onChange={setDispatchFilter}
              options={dispatchTypeOptions}
              style={{ width: 140 }}
              allowClear
            />
          </>
        )}
        <RangePicker value={dateRange} onChange={setDateRange} placeholder={['开始日期', '结束日期']} />
      </Space>

      <Table dataSource={runs} columns={columns} rowKey="id" loading={loading}
        size="small" pagination={{ pageSize: 20 }} />
    </div>
  )
}
