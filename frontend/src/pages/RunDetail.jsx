import { useEffect, useState, useCallback } from 'react'
import { Descriptions, Tag, Spin, Button, Space, Modal, Input, Form, message } from 'antd'
import { FolderOpenOutlined, StopOutlined, ReloadOutlined, BugOutlined, RedoOutlined } from '@ant-design/icons'
import { useNavigate, useParams } from 'react-router-dom'
import api from '../api/client'
import LogViewer from '../components/LogViewer'
import { useConnection } from '../contexts/ConnectionContext'
import { canOpenResultLocally, firstResultPath, loadRunDetail } from '../api/offlineData'
import { formatScriptVersion } from '../utils/scriptVersion'
import { formatServerTime } from '../utils/dateTime'
import { useAuth } from '../contexts/AuthContext'
import usePageFocused from '../hooks/usePageFocused'
import { refreshDelay, runDeviceName } from '../utils/runHistory'

const statusMap = {
  pending: { color: 'blue', text: '等待中' },
  running: { color: 'orange', text: '执行中' },
  success: { color: 'green', text: '成功' },
  failed: { color: 'red', text: '失败' },
  cancelled: { color: 'default', text: '已取消' },
  expired: { color: 'default', text: '已过期' },
}

export default function RunDetail() {
  const { id } = useParams()
  const navigate = useNavigate()
  const { user } = useAuth()
  const pageFocused = usePageFocused()
  const [run, setRun] = useState(null)
  const [loading, setLoading] = useState(true)
  const [issueModal, setIssueModal] = useState(false)
  const [issueForm] = Form.useForm()
  const [submitting, setSubmitting] = useState(false)
  const [retrying, setRetrying] = useState(false)
  const { online, agentOnline, agentId, localApi } = useConnection()
  const localOnly = String(id).startsWith('L') || !online
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
    if (!['pending', 'running'].includes(runStatus)) return undefined
    const interval = setInterval(() => {
      loadRunDetail({ id, online: !localOnly, api, localApi }).then(setRun).catch(() => {})
    }, refreshDelay({
      hasActive: true,
      isFocused: pageFocused,
      activeMs: localOnly ? 1000 : 5000,
      backgroundMs: 60000,
    }))
    return () => clearInterval(interval)
  }, [id, localOnly, localApi, pageFocused, runStatus])

  const onCancel = async () => {
    try {
      await api.post(`/api/runs/${id}/cancel`)
      message.success('已取消')
      load()
    } catch (e) {
      message.error(e.response?.data?.detail || '取消失败')
    }
  }

  const onRetry = async () => {
    setRetrying(true)
    try {
      const response = await api.post(`/api/admin/managed-runs/${id}/retry`)
      message.success(`已创建重试任务 #${response.data.id}`)
      navigate(`/runs/${response.data.id}`)
    } catch (error) {
      message.error(error.response?.data?.detail || '重试失败')
    } finally {
      setRetrying(false)
    }
  }

  const onSubmitIssue = async (values) => {
    setSubmitting(true)
    try {
      await api.post('/api/issues', { run_id: parseInt(id), ...values })
      message.success('问题已上报')
      setIssueModal(false)
      issueForm.resetFields()
    } catch (e) {
      message.error(e.response?.data?.detail || '上报失败')
    } finally {
      setSubmitting(false)
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
  const isAlive = run.status === 'pending' || run.status === 'running'
  const canRetry = !localOnly
    && user?.role === 'admin'
    && ['managed_manual', 'managed_schedule'].includes(run.dispatch_type)
    && ['failed', 'expired', 'cancelled'].includes(run.status)

  return (
    <div>
      <div className="page-title-row">
        <h2 style={{ margin: 0 }}>执行详情 #{run.id}</h2>
        <Space>
          <Button icon={<ReloadOutlined />} onClick={load}>刷新</Button>
          {isAlive && !localOnly && (
            <Button danger icon={<StopOutlined />} onClick={onCancel}>取消执行</Button>
          )}
          {canRetry && (
            <Button type="primary" icon={<RedoOutlined />} loading={retrying} onClick={onRetry}>重试任务</Button>
          )}
          {!localOnly && (run.status === 'failed' || run.status === 'success') && (
            <Button icon={<BugOutlined />} onClick={() => { setIssueModal(true); issueForm.resetFields() }}>上报问题</Button>
          )}
        </Space>
      </div>
      <Descriptions bordered size="small" column={2} className="run-detail__descriptions" style={{ marginBottom: 16 }}>
        <Descriptions.Item label="脚本ID">{run.script_id}</Descriptions.Item>
        <Descriptions.Item label="版本">{formatScriptVersion(run.script_semantic_version, run.script_version)}</Descriptions.Item>
        <Descriptions.Item label="状态"><Tag color={sm.color}>{sm.text}</Tag></Descriptions.Item>
        <Descriptions.Item label="耗时">{run.duration_sec != null ? `${run.duration_sec}s` : '-'}</Descriptions.Item>
        <Descriptions.Item label="开始时间">{formatServerTime(run.started_at)}</Descriptions.Item>
        <Descriptions.Item label="结束时间">{formatServerTime(run.finished_at)}</Descriptions.Item>
        {run.dispatch_type !== 'standard' && (
          <Descriptions.Item label="任务来源">
            {{ managed_manual: '管理端下发', managed_schedule: '托管计划' }[run.dispatch_type] || run.dispatch_type}
          </Descriptions.Item>
        )}
        {(run.target_agent_id || run.agent_id) && (
          <Descriptions.Item label="执行设备">{runDeviceName(run)}</Descriptions.Item>
        )}
        {run.retry_of_run_id && (
          <Descriptions.Item label="重试来源">
            <Button type="link" size="small" onClick={() => navigate(`/runs/${run.retry_of_run_id}`)}>运行 #{run.retry_of_run_id}</Button>
          </Descriptions.Item>
        )}
        {run.scheduled_for && <Descriptions.Item label="计划时间">{formatServerTime(run.scheduled_for)}</Descriptions.Item>}
        {run.expires_at && <Descriptions.Item label="领取截止">{formatServerTime(run.expires_at)}</Descriptions.Item>}
        {run.claimed_at && <Descriptions.Item label="领取时间">{formatServerTime(run.claimed_at)}</Descriptions.Item>}
        {run.error_msg && <Descriptions.Item label="错误信息" span={2}>{run.error_msg}</Descriptions.Item>}
        {(run.has_result_files || run.result_files) && (
          <Descriptions.Item label="结果文件" span={2}>
            {run.result_files && canOpenResultLocally(run, agentOnline, agentId) ? (
              <Button icon={<FolderOpenOutlined />} onClick={onOpenResult}>在本机打开结果文件</Button>
            ) : '结果文件保存在执行客户端（本页面不显示本地路径）'}
          </Descriptions.Item>
        )}
        {run.params && (
          <Descriptions.Item label="参数" span={2}>
            <pre className="run-detail__params">{JSON.stringify(JSON.parse(run.params), null, 2)}</pre>
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

      <Modal title="上报问题" open={issueModal} onCancel={() => setIssueModal(false)}
        confirmLoading={submitting} onOk={() => issueForm.submit()} okText="提交">
        <Form form={issueForm} layout="vertical" onFinish={onSubmitIssue}>
          <Form.Item name="title" label="问题标题" rules={[{ required: true, message: '请填写' }]}>
            <Input placeholder="简要描述问题" />
          </Form.Item>
          <Form.Item name="description" label="详细描述">
            <Input.TextArea rows={4} placeholder="详细说明遇到的问题，日志会自动附带" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
