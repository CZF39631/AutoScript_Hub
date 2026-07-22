import { useEffect, useState } from 'react'
import { Table, Tag, Button, Modal, Input, Form, Select, Space, Descriptions, message } from 'antd'
import { EyeOutlined } from '@ant-design/icons'
import { useAuth } from '../contexts/AuthContext'
import api from '../api/client'

const statusMap = {
  open: { color: 'red', text: '待处理' },
  resolved: { color: 'green', text: '已解决' },
}

export default function Issues() {
  const { user } = useAuth()
  const [issues, setIssues] = useState([])
  const [loading, setLoading] = useState(true)
  const [statusFilter, setStatusFilter] = useState(undefined)
  const [resolveModal, setResolveModal] = useState(null)
  const [resolveForm] = Form.useForm()
  const [resolving, setResolving] = useState(false)
  const [detailModal, setDetailModal] = useState(null)
  const [detailLog, setDetailLog] = useState('')
  const [detailLoading, setDetailLoading] = useState(false)

  const canResolve = user?.role === 'admin' || user?.role === 'developer'

  const load = () => {
    setLoading(true)
    const params = statusFilter ? `?status=${statusFilter}` : ''
    api.get(`/api/issues${params}`).then(r => setIssues(r.data))
      .catch(() => message.error('加载失败')).finally(() => setLoading(false))
  }

  useEffect(load, [statusFilter])

  const openDetail = (issue) => {
    setDetailModal(issue)
    setDetailLog('')
    if (issue.run_id) {
      setDetailLoading(true)
      api.get(`/api/issues/${issue.id}/log`).then(r => {
        setDetailLog(r.data.log || '(暂无日志)')
      }).catch(() => setDetailLog('(加载失败)')).finally(() => setDetailLoading(false))
    }
  }

  const onResolve = async (values) => {
    setResolving(true)
    try {
      await api.post(`/api/issues/${resolveModal.id}/resolve`, values)
      message.success('已标记解决')
      setResolveModal(null)
      resolveForm.resetFields()
      load()
    } catch (e) {
      message.error(e.response?.data?.detail || '操作失败')
    } finally {
      setResolving(false)
    }
  }

  const columns = [
    { title: 'ID', dataIndex: 'id', key: 'id', width: 50 },
    { title: '标题', dataIndex: 'title', key: 'title', width: 160, ellipsis: true },
    ...(canResolve ? [{ title: '上报人', dataIndex: 'username', key: 'user', width: 90 }] : []),
    { title: '脚本', dataIndex: 'script_name', key: 'script', width: 130, ellipsis: true,
      render: (v) => v || '-' },
    { title: '状态', dataIndex: 'status', key: 'status', width: 80,
      render: (s) => { const m = statusMap[s] || { color: 'default', text: s }; return <Tag color={m.color}>{m.text}</Tag> } },
    { title: '上报时间', dataIndex: 'created_at', key: 'time', width: 160,
      render: (t) => t ? new Date(t).toLocaleString() : '-' },
    {
      title: '操作', key: 'action', width: 160,
      render: (_, r) => (
        <Space>
          <Button type="link" size="small" icon={<EyeOutlined />} onClick={() => openDetail(r)}>详情</Button>
          {r.status === 'open' && canResolve && (
            <Button type="link" size="small" onClick={() => { setResolveModal(r); resolveForm.resetFields() }}>解决</Button>
          )}
          {r.status === 'open' && !canResolve && (
            <span style={{ color: '#faad14', fontSize: 12 }}>等待处理</span>
          )}
        </Space>
      )
    },
  ]

  return (
    <div>
      <h2>{canResolve ? '问题工单' : '我的反馈'}</h2>
      <Space style={{ marginBottom: 16 }}>
        <Select placeholder="状态筛选" value={statusFilter} onChange={setStatusFilter}
          options={[{ label: '待处理', value: 'open' }, { label: '已解决', value: 'resolved' }]}
          style={{ width: 130 }} allowClear />
      </Space>
      <Table dataSource={issues} columns={columns} rowKey="id" loading={loading} size="small" />

      {/* Detail Modal */}
      <Modal title={`问题 #${detailModal?.id || ''}`} open={!!detailModal}
        onCancel={() => setDetailModal(null)} footer={null} width={700}>
        {detailModal && (
          <>
            <Descriptions bordered size="small" column={2} style={{ marginBottom: 16 }}>
              <Descriptions.Item label="标题" span={2}>{detailModal.title}</Descriptions.Item>
              {detailModal.description && (
                <Descriptions.Item label="描述" span={2}>{detailModal.description}</Descriptions.Item>
              )}
              <Descriptions.Item label="上报人">{detailModal.username || '-'}</Descriptions.Item>
              <Descriptions.Item label="脚本">{detailModal.script_name || '-'}</Descriptions.Item>
              <Descriptions.Item label="状态">
                {(() => { const m = statusMap[detailModal.status] || {}; return <Tag color={m.color}>{m.text || detailModal.status}</Tag> })()}
              </Descriptions.Item>
              <Descriptions.Item label="Run ID">
                {detailModal.run_id ? (
                  <Button type="link" size="small" onClick={() => window.open(`/runs/${detailModal.run_id}`, '_blank')}>
                    #{detailModal.run_id}
                  </Button>
                ) : '-'}
              </Descriptions.Item>
              {detailModal.error_msg && (
                <Descriptions.Item label="错误信息" span={2}>
                  <pre style={{ margin: 0, color: '#ff4d4f', whiteSpace: 'pre-wrap', fontSize: 12 }}>{detailModal.error_msg}</pre>
                </Descriptions.Item>
              )}
              {detailModal.run_params && (
                <Descriptions.Item label="执行参数" span={2}>
                  <pre style={{ margin: 0, fontSize: 12 }}>{JSON.stringify(JSON.parse(detailModal.run_params), null, 2)}</pre>
                </Descriptions.Item>
              )}
              {detailModal.resolve_note && (
                <Descriptions.Item label="解决说明" span={2}>{detailModal.resolve_note}</Descriptions.Item>
              )}
            </Descriptions>
            {detailModal.run_id && (
              <div>
                <h4>执行日志</h4>
                <pre style={{
                  background: '#1e1e1e', color: '#d4d4d4', padding: 16,
                  borderRadius: 4, maxHeight: 300, overflow: 'auto',
                  fontSize: 12, lineHeight: 1.5, whiteSpace: 'pre-wrap',
                }}>
                  {detailLoading ? '加载中...' : detailLog}
                </pre>
              </div>
            )}
          </>
        )}
      </Modal>

      {/* Resolve Modal */}
      <Modal title="标记已解决" open={!!resolveModal} onCancel={() => setResolveModal(null)}
        confirmLoading={resolving} onOk={() => resolveForm.submit()} okText="确认">
        <Form form={resolveForm} layout="vertical" onFinish={onResolve}>
          <Form.Item name="resolve_note" label="解决说明" rules={[{ required: true, message: '请填写' }]}>
            <Input.TextArea rows={3} placeholder="描述解决方案" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
