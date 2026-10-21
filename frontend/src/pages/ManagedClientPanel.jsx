import { useCallback, useEffect, useMemo, useState } from 'react'
import { Alert, Button, Card, Descriptions, Empty, Skeleton, Table, Tag } from 'antd'
import {
  CheckCircleOutlined, CloudServerOutlined, DisconnectOutlined, LaptopOutlined,
  LoadingOutlined, PauseCircleOutlined, ReloadOutlined, SafetyCertificateOutlined,
} from '@ant-design/icons'
import { useConnection } from '../contexts/ConnectionContext'
import { loadManagedPanelData } from '../api/managedLocal'
import { apiErrorMessage } from '../utils/managed'
import { formatServerTime } from '../utils/dateTime'

const runStates = {
  pending: { color: 'blue', text: '等待中' },
  starting: { color: 'processing', text: '启动中' },
  running: { color: 'processing', text: '执行中' },
  success: { color: 'green', text: '成功' },
  failed: { color: 'red', text: '失败' },
  cancelled: { color: 'default', text: '已取消' },
}

function localTime(value) {
  if (typeof value === 'number') return formatServerTime(new Date(value * 1000).toISOString())
  return formatServerTime(value)
}

function RunStatus({ value }) {
  const state = runStates[value] || { color: 'default', text: value || '未知' }
  return <Tag color={state.color}>{state.text}</Tag>
}

export default function ManagedClientPanel() {
  const { agentOnline, localApi, refresh: refreshConnection } = useConnection()
  const [overview, setOverview] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [lastRefresh, setLastRefresh] = useState(null)

  const load = useCallback(async ({ quiet = false } = {}) => {
    if (!quiet) setLoading(true)
    setError('')
    try {
      const data = await loadManagedPanelData(localApi)
      setOverview(data)
      setLastRefresh(new Date())
    } catch (loadError) {
      setError(apiErrorMessage(loadError, '无法读取本地 Agent 状态'))
    } finally {
      if (!quiet) setLoading(false)
    }
  }, [localApi])

  useEffect(() => {
    load()
    const timer = setInterval(() => load({ quiet: true }), 5000)
    return () => clearInterval(timer)
  }, [load, agentOnline])

  const connection = overview?.connection || {}
  const device = overview?.device || {}
  const currentRun = overview?.currentRun
  const recentRuns = overview?.recentRuns || []
  const connectedToServer = Boolean(connection.online)
  const deviceName = device.machine_name || connection.machine_name || '本机被控设备'

  const connectionState = useMemo(() => {
    if (!agentOnline) return { icon: <DisconnectOutlined />, tone: 'error', title: '本地 Agent 未连接', detail: '请确认 AutoScript Agent 正在运行。' }
    if (!connectedToServer) return { icon: <DisconnectOutlined />, tone: 'warning', title: '服务器连接已中断', detail: 'Agent 会自动重试连接，期间不会接收新任务。' }
    return { icon: <CheckCircleOutlined />, tone: 'success', title: '连接正常', detail: '设备正在等待服务器下发任务。' }
  }, [agentOnline, connectedToServer])

  const columns = [
    { title: '任务', key: 'task', ellipsis: true, render: (_, run) => run.script_name || `任务 #${run.id}` },
    { title: '状态', dataIndex: 'status', key: 'status', width: 90, render: value => <RunStatus value={value} /> },
    { title: '开始时间', key: 'started', width: 170, render: (_, run) => localTime(run.started_at || run.created_at) },
    { title: '耗时', dataIndex: 'duration_sec', key: 'duration', width: 90, render: value => value == null ? '-' : `${value} 秒` },
  ]

  const manualRefresh = () => {
    refreshConnection()
    load()
  }

  return (
    <main className="managed-client-shell">
      <header className="managed-client-header">
        <div className="managed-client-brand">
          <img src="/app-icon.png" alt="" />
          <span><strong>AutoScript Hub</strong><small>被控模式</small></span>
        </div>
        <div className="managed-client-refresh">
          <span>{lastRefresh ? `更新于 ${lastRefresh.toLocaleTimeString('zh-CN', { hour12: false })}` : '正在读取状态'}</span>
          <Button icon={<ReloadOutlined />} onClick={manualRefresh} loading={loading}>刷新</Button>
        </div>
      </header>

      <section className="managed-client-content" aria-live="polite">
        <Alert
          className="managed-privacy-notice"
          type="info"
          showIcon
          icon={<SafetyCertificateOutlined />}
          title="屏幕缩略图隐私说明"
          description="设备解锁时每分钟上传一张低分辨率缩略图，服务端只保留最新一张；锁屏时不采集。这不是视频，也不采集声音。"
        />

        {overview?.paused && (
          <Alert
            className="managed-pause-alert"
            type="warning"
            showIcon
            icon={<PauseCircleOutlined />}
            title="设备接单已暂停"
            description="管理员启用此设备后，Agent 才会继续领取新的托管任务。当前任务不会在此面板中启动或修改。"
          />
        )}

        {!overview?.paused && (
          <Alert
            className="managed-mode-notice"
            type="info"
            showIcon
            title="此设备由管理员托管"
            description="这里只显示连接和运行状态，不提供脚本管理或本地执行；管理员可随时暂停设备接单。"
          />
        )}

        {error && !overview && (
          <Alert type="error" showIcon title="本地状态读取失败" description={error} action={<Button size="small" onClick={manualRefresh}>重试</Button>} />
        )}
        {error && overview && (
          <Alert className="managed-page-alert" type="warning" showIcon title="状态刷新失败，当前展示上次读取结果" action={<Button size="small" onClick={manualRefresh}>重试</Button>} />
        )}

        {loading && !overview ? (
          <div className="managed-client-loading"><Skeleton active paragraph={{ rows: 7 }} /></div>
        ) : (
          <>
            <div className="managed-client-summary">
              <Card className={`managed-status-card managed-status-card--${connectionState.tone}`}>
                <div className="managed-status-card__icon">{connectionState.icon}</div>
                <div><span>连接</span><strong>{connectionState.title}</strong><small>{connectionState.detail}</small></div>
              </Card>
              <Card className="managed-status-card">
                <div className="managed-status-card__icon"><LaptopOutlined /></div>
                <div><span>设备</span><strong>{deviceName}</strong><small>{connection.agent_id ? `Agent #${connection.agent_id}` : '等待设备注册'}</small></div>
              </Card>
              <Card className="managed-status-card">
                <div className="managed-status-card__icon"><CloudServerOutlined /></div>
                <div><span>当前任务</span><strong>{currentRun ? (currentRun.script_name || `任务 #${currentRun.id}`) : '暂无任务'}</strong><small>{currentRun ? '任务由管理员远程下发' : '设备保持待命'}</small></div>
              </Card>
            </div>

            <div className="managed-client-grid">
              <Card title="设备状态" className="managed-client-card">
                <Descriptions column={1} size="small" colon={false}>
                  <Descriptions.Item label="设备名称">{deviceName}</Descriptions.Item>
                  <Descriptions.Item label="设备标识">{device.device_uid || connection.device_uid || '-'}</Descriptions.Item>
                  <Descriptions.Item label="Agent 版本">{connection.agent_version || '-'}</Descriptions.Item>
                  <Descriptions.Item label="运行环境">{overview?.runtime?.status === 'ready' ? `Python ${overview.runtime.version || '已就绪'}` : '等待就绪'}</Descriptions.Item>
                  <Descriptions.Item label="最近联机">{connection.last_online_at ? localTime(connection.last_online_at) : connectedToServer ? '当前在线' : '-'}</Descriptions.Item>
                </Descriptions>
              </Card>

              <Card title="当前任务" className="managed-client-card">
                {currentRun ? (
                  <div className="managed-current-run">
                    <div className="managed-current-run__top">
                      <span className="managed-current-run__icon"><LoadingOutlined spin={currentRun.status === 'running'} /></span>
                      <div><strong>{currentRun.script_name || `任务 #${currentRun.id}`}</strong><RunStatus value={currentRun.status || 'running'} /></div>
                    </div>
                    <Descriptions column={1} size="small" colon={false}>
                      <Descriptions.Item label="任务 ID">{currentRun.id}</Descriptions.Item>
                      <Descriptions.Item label="开始时间">{localTime(currentRun.started_at || currentRun.created_at)}</Descriptions.Item>
                    </Descriptions>
                  </div>
                ) : (
                  <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="当前没有正在执行的任务" />
                )}
              </Card>
            </div>

            <Card title="最近运行" className="managed-client-runs">
              <Table
                dataSource={recentRuns.slice(0, 8)}
                columns={columns}
                rowKey={run => run.id || run.local_run_id}
                size="small"
                pagination={false}
                locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="还没有本机运行记录" /> }}
                scroll={{ x: 640 }}
              />
            </Card>
          </>
        )}
      </section>
    </main>
  )
}
