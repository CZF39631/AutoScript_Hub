import React, { useEffect, useState, useCallback } from 'react'
import { Descriptions, Tag, Spin, Button, Space, Modal, Input, Form, message } from 'antd'
import { FolderOpenOutlined, StopOutlined, ReloadOutlined, BugOutlined } from '@ant-design/icons'
import { useParams } from 'react-router-dom'
import api from '../api/client'
import LogViewer from '../components/LogViewer'

const statusMap = {
  pending: { color: 'blue', text: '等待中' },
  running: { color: 'orange', text: '执行中' },
  success: { color: 'green', text: '成功' },
  failed: { color: 'red', text: '失败' },
  cancelled: { color: 'default', text: '已取消' },
}

export default function RunDetail() {
  const { id } = useParams()
  const [run, setRun] = useState(null)
  const [loading, setLoading] = useState(true)
  const [issueModal, setIssueModal] = useState(false)
  const [issueForm] = Form.useForm()
  const [submitting, setSubmitting] = useState(false)

  const load = useCallback(() => {
    setLoading(true)
    api.get(`/api/runs/${id}`).then(r => setRun(r.data)).catch(() => message.error('加载失败')).finally(() => setLoading(false))
  }, [id])

  // Called by LogViewer when SSE stream ends — refresh run status without flashing the spinner.
  const onLogComplete = useCallback(() => {
    api.get(`/api/runs/${id}`).then(r => setRun(r.data)).catch(() => {})
  }, [id])

  useEffect(load, [load])

  const onCancel = async () => {
    try {
      await api.post(`/api/runs/${id}/cancel`)
      message.success('已取消')
      load()
    } catch (e) {
      message.error(e.response?.data?.detail || '取消失败')
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

  if (loading) return <Spin />
  if (!run) return <div>记录不存在</div>

  const sm = statusMap[run.status] || { color: 'default', text: run.status }
  const isAlive = run.status === 'pending' || run.status === 'running'

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <h2 style={{ margin: 0 }}>执行详情 #{run.id}</h2>
        <Space>
          <Button icon={<ReloadOutlined />} onClick={load}>刷新</Button>
          {isAlive && (
            <Button danger icon={<StopOutlined />} onClick={onCancel}>取消执行</Button>
          )}
          {(run.status === 'failed' || run.status === 'success') && (
            <Button icon={<BugOutlined />} onClick={() => { setIssueModal(true); issueForm.resetFields() }}>上报问题</Button>
          )}
        </Space>
      </div>
      <Descriptions bordered size="small" column={2} style={{ marginBottom: 16 }}>
        <Descriptions.Item label="脚本ID">{run.script_id}</Descriptions.Item>
        <Descriptions.Item label="版本">{run.script_version}</Descriptions.Item>
        <Descriptions.Item label="状态"><Tag color={sm.color}>{sm.text}</Tag></Descriptions.Item>
        <Descriptions.Item label="耗时">{run.duration_sec != null ? `${run.duration_sec}s` : '-'}</Descriptions.Item>
        <Descriptions.Item label="开始时间">{run.started_at ? new Date(run.started_at).toLocaleString() : '-'}</Descriptions.Item>
        <Descriptions.Item label="结束时间">{run.finished_at ? new Date(run.finished_at).toLocaleString() : '-'}</Descriptions.Item>
        {run.error_msg && <Descriptions.Item label="错误信息" span={2}>{run.error_msg}</Descriptions.Item>}
        {run.result_files && (
          <Descriptions.Item label="结果文件" span={2}>
            <Button
              icon={<FolderOpenOutlined />}
              onClick={() => api.post(`/api/runs/${run.id}/open-result`).catch(e => message.error(e.response?.data?.detail || '打开失败'))}
            >
              {(() => { try { const v = JSON.parse(run.result_files); return typeof v === 'string' ? v : '打开结果文件' } catch { return '打开结果文件' } })()}
            </Button>
          </Descriptions.Item>
        )}
        {run.params && <Descriptions.Item label="参数" span={2}><pre style={{ margin: 0 }}>{JSON.stringify(JSON.parse(run.params), null, 2)}</pre></Descriptions.Item>}
      </Descriptions>
      <LogViewer runId={run.id} status={run.status} onComplete={onLogComplete} />

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
