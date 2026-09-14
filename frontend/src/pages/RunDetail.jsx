import { useEffect, useState, useCallback } from 'react'
import { Alert, Descriptions, Tag, Spin, Button, Space, message, Popconfirm } from 'antd'
import { FolderOpenOutlined, StopOutlined, ReloadOutlined, BugOutlined } from '@ant-design/icons'
import { useParams } from 'react-router-dom'
import api from '../api/client'
import LogViewer from '../components/LogViewer'
import DiagnosticReport from '../components/DiagnosticReport'
import { useConnection } from '../contexts/ConnectionContext'
import { canOpenResultLocally, firstResultPath, loadRunDetail } from '../api/offlineData'
import { formatScriptVersion } from '../utils/scriptVersion'
import { formatServerTime } from '../utils/dateTime'
import { taskError } from '../utils/taskScheduling'
import { formatIssueParams } from '../utils/issueDetail'

const statusMap = {
  pending: { color: 'blue', text: '等待中' },
  running: { color: 'orange', text: '执行中' },
  success: { color: 'green', text: '成功' },
  failed: { color: 'red', text: '失败' },
  cancelled: { color: 'default', text: '已取消' },
  queued: { color: 'blue', text: '等待领取' },
  claimed: { color: 'processing', text: '准备中' },
  preparing: { color: 'processing', text: '准备中' },
  cancel_requested: { color: 'orange', text: '正在取消' },
  unknown: { color: 'warning', text: '结果未知' },
  skipped: { color: 'default', text: '已跳过' },
}
const activeStates = ['pending', 'queued', 'claimed', 'preparing', 'running', 'cancel_requested', 'unknown']

export default function RunDetail() {
  const { id } = useParams()
  const [run, setRun] = useState(null)
  const [loading, setLoading] = useState(true)
  const [issueModal, setIssueModal] = useState(false)
  const { online, agentOnline, agentId, localApi } = useConnection()
  const localOnly = /^[LS]/.test(String(id)) || !online
  const runStatus = run?.status

  const load = useCallback(() => {
    setLoading(true)
    loadRunDetail({ id, online, api, localApi })
      .then(setRun)
      .catch(() => message.error(localOnly ? '本地执行记录不存在' : '加载失败'))
      .finally(() => setLoading(false))
  }, [id, online, localApi, localOnly])

  // Called by LogViewer when SSE stream ends — refresh run status without flashing the spinner.
  const onLogComplete = useCallback(() => {
    if (!localOnly) api.get(`/api/runs/${id}`).then(r => setRun(r.data)).catch(() => {})
  }, [id, localOnly])

  useEffect(load, [load])

  useEffect(() => {
    if (!activeStates.includes(runStatus)) return undefined
    let active = true
    const interval = setInterval(() => {
      loadRunDetail({ id, online, api, localApi }).then(value => { if (active) setRun(value) }).catch(() => {})
    }, localOnly ? 1000 : 5000)
    return () => { active = false; clearInterval(interval) }
  }, [id, online, localOnly, localApi, runStatus])

  const onCancel = async () => {
    try {
      const endpoint = localOnly ? `/local/runs/${id}/cancel` : run.task_execution_id ? `/api/tasks/executions/${run.task_execution_id}/cancel` : `/api/runs/${id}/cancel`
      await (localOnly ? localApi : api).post(endpoint, {})
      message.success('取消请求已发送，请等待执行端确认停止')
      load()
    } catch (e) {
      message.error(taskError(e))
    }
  }

  const onOpenResult = async () => {
    try {
      const path = firstResultPath(run.result_files)
      if (!path) throw new Error('没有可打开的结果路径')
      await localApi.post('/local/results/open', { path })
    } catch (error) {
      message.error(error.response?.data?.error || error.message || '打开失败')
    }
  }

  if (loading) return <Spin />
  if (!run) return <div>记录不存在</div>

  const sm = statusMap[run.status] || { color: 'default', text: run.status }
  const isAlive = activeStates.includes(run.status)

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <h2 style={{ margin: 0 }}>执行详情 #{run.id}</h2>
        <Space>
          <Button icon={<ReloadOutlined />} onClick={load}>刷新</Button>
          {isAlive && (
            <Popconfirm title="请求取消此次执行？" description="只有执行端确认整个进程树停止后，才能确认取消。" onConfirm={onCancel}>
              <Button danger icon={<StopOutlined />} disabled={run.status === 'cancel_requested'}>取消执行</Button>
            </Popconfirm>
          )}
          {!localOnly && (run.status === 'failed' || run.status === 'success') && (
            <Button icon={<BugOutlined />} onClick={() => setIssueModal(true)}>上报问题</Button>
          )}
        </Space>
      </div>
      {run.status === 'unknown' && <Alert type="warning" showIcon title="执行结果未知，请核对目标电脑；不要直接重复运行。" style={{ marginBottom: 16 }} />}
      <Descriptions bordered size="small" column={2} className="run-detail__descriptions" style={{ marginBottom: 16 }}>
        <Descriptions.Item label="脚本ID">{run.script_id}</Descriptions.Item>
        <Descriptions.Item label="版本">{formatScriptVersion(run.script_semantic_version, run.script_version)}</Descriptions.Item>
        <Descriptions.Item label="状态"><Tag color={sm.color}>{sm.text}</Tag></Descriptions.Item>
        <Descriptions.Item label="耗时">{run.duration_sec != null ? `${run.duration_sec}s` : '-'}</Descriptions.Item>
        <Descriptions.Item label="开始时间">{formatServerTime(run.started_at)}</Descriptions.Item>
        <Descriptions.Item label="结束时间">{formatServerTime(run.finished_at)}</Descriptions.Item>
        {run.error_msg && <Descriptions.Item label="错误信息" span={2}>{run.error_msg}</Descriptions.Item>}
        {run.result_files && (
          <Descriptions.Item label="结果文件" span={2}>
            {canOpenResultLocally(run, agentOnline, agentId) ? (
              <Button icon={<FolderOpenOutlined />} onClick={onOpenResult}>在本机打开结果文件</Button>
            ) : '结果文件保存在执行客户端'}
          </Descriptions.Item>
        )}
        {run.params && (
          <Descriptions.Item label="参数" span={2}>
            <pre className="run-detail__params">{formatIssueParams(run.params).text}</pre>
          </Descriptions.Item>
        )}
      </Descriptions>
      <LogViewer
        runId={run.id}
        status={run.status}
        onComplete={onLogComplete}
        localOnly={localOnly}
        localApi={localApi}
      />

      <DiagnosticReport key={id} open={issueModal} onCancel={() => setIssueModal(false)}
        runId={localOnly ? undefined : id} scriptVersion={formatScriptVersion(run.script_semantic_version, run.script_version)} />
    </div>
  )
}
