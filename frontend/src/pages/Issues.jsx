import { useEffect, useState } from 'react'
import { Table, Tag, Button, Modal, Input, Form, Select, Space, Descriptions, message } from 'antd'
import { EyeOutlined } from '@ant-design/icons'
import { useAuth } from '../contexts/AuthContext'
import api from '../api/client'
import DiagnosticReport from '../components/DiagnosticReport'
import { formatServerTime } from '../utils/dateTime'
import { createIssueLogLoader, formatIssueParams } from '../utils/issueDetail'
import { safeError } from '../utils/safeError'
import { useI18n } from '../i18n/useI18n'

// Keep UI fallback states distinct from real log text, even when the text is identical.
const emptyIssueLog = Symbol('emptyIssueLog')
const failedIssueLog = Symbol('failedIssueLog')
const collectionKeys = {
  collected: 'management.issues.collected',
  partial: 'management.issues.partial',
}

export default function Issues() {
  const { t } = useI18n()
  const statusMap = {
    open: { color: 'red', text: t('management.issues.open') },
    resolved: { color: 'green', text: t('management.issues.resolved') },
  }
  const { user } = useAuth()
  const [issues, setIssues] = useState([])
  const [reportOpen, setReportOpen] = useState(false)
  const [downloading, setDownloading] = useState(false)
  const [loading, setLoading] = useState(true)
  const [statusFilter, setStatusFilter] = useState(undefined)
  const [resolveModal, setResolveModal] = useState(null)
  const [resolveForm] = Form.useForm()
  const [resolving, setResolving] = useState(false)
  const [detailModal, setDetailModal] = useState(null)
  const [detailLog, setDetailLog] = useState('')
  const [detailLoading, setDetailLoading] = useState(false)
  const [detailLogLoader] = useState(() => createIssueLogLoader(
    (url) => api.get(url)
      .then(response => ({ data: { log: response.data.log || emptyIssueLog } }))
      .catch(() => ({ data: { log: failedIssueLog } })),
    setDetailLog, setDetailLoading,
  ))
  useEffect(() => () => detailLogLoader.cancel(), [detailLogLoader])
  const detailParams = formatIssueParams(detailModal?.run_params)

  const canResolve = user?.role === 'admin' || user?.role === 'developer'

  const load = () => {
    setLoading(true)
    const params = statusFilter ? `?status=${statusFilter}` : ''
    api.get(`/api/issues${params}`).then(r => setIssues(r.data))
      .catch(() => message.error(t('management.loadFailed'))).finally(() => setLoading(false))
  }

  // Language changes only rerender labels; keep the existing query lifecycle.
  useEffect(load, [statusFilter]) // eslint-disable-line react-hooks/exhaustive-deps

  const openDetail = (issue) => {
    setDetailModal(issue)
    void detailLogLoader.open(issue)
  }

  const closeDetail = () => {
    void detailLogLoader.open(null)
    setDetailModal(null)
  }

  const onResolve = async (values) => {
    setResolving(true)
    try {
      await api.post(`/api/issues/${resolveModal.id}/resolve`, values)
      message.success(t('management.issues.markedResolved'))
      setResolveModal(null)
      resolveForm.resetFields()
      load()
    } catch (e) {
      message.error(safeError(e, t('management.operationFailed')))
    } finally {
      setResolving(false)
    }
  }

  const download = async () => {
    setDownloading(true)
    try {
      const r = await api.get(`/api/issues/${detailModal.id}/diagnostics`, { responseType: 'blob' })
      const url = URL.createObjectURL(r.data)
      const link = document.createElement('a')
      link.href = url; link.download = `issue-${detailModal.id}-diagnostics.json`; link.click()
      setTimeout(() => URL.revokeObjectURL(url), 1000)
    } catch { message.error(t('management.issues.downloadFailed')) }
    finally { setDownloading(false) }
  }

  const columns = [
    { title: 'ID', dataIndex: 'id', key: 'id', width: 50 },
    { title: t('management.title'), dataIndex: 'title', key: 'title', width: 160, ellipsis: true },
    ...(canResolve ? [{ title: t('management.issues.reporter'), dataIndex: 'username', key: 'user', width: 90 }] : []),
    { title: t('management.script'), dataIndex: 'script_name', key: 'script', width: 130, ellipsis: true,
      render: (v) => v || '-' },
    { title: t('management.status'), dataIndex: 'status', key: 'status', width: 80,
      render: (s) => { const m = statusMap[s] || { color: 'default', text: s }; return <Tag color={m.color}>{m.text}</Tag> } },
    { title: t('management.issues.reportedAt'), dataIndex: 'created_at', key: 'time', width: 160,
      render: formatServerTime },
    {
      title: t('management.actions'), key: 'action', width: 160,
      render: (_, r) => (
        <Space>
          <Button type="link" size="small" icon={<EyeOutlined />} onClick={() => openDetail(r)}>{t('management.details')}</Button>
          {r.status === 'open' && canResolve && (
            <Button type="link" size="small" onClick={() => { setResolveModal(r); resolveForm.resetFields() }}>{t('management.issues.resolve')}</Button>
          )}
          {r.status === 'open' && !canResolve && (
            <span style={{ color: '#faad14', fontSize: 12 }}>{t('management.issues.awaiting')}</span>
          )}
        </Space>
      )
    },
  ]

  return (
    <div>
      <h2>{t(canResolve ? 'management.issues.title' : 'management.issues.myFeedback')}</h2>
      <Space style={{ marginBottom: 16 }}>
        <Button type="primary" onClick={() => setReportOpen(true)}>{t('management.issues.report')}</Button>
        <Select placeholder={t('management.issues.statusFilter')} value={statusFilter} onChange={setStatusFilter}
          options={[{ label: t('management.issues.open'), value: 'open' }, { label: t('management.issues.resolved'), value: 'resolved' }]}
          style={{ width: 130 }} allowClear />
      </Space>
      <Table locale={{ emptyText: t('management.empty') }} dataSource={issues} columns={columns} rowKey="id" loading={loading} size="small" />

      <DiagnosticReport open={reportOpen} onCancel={() => setReportOpen(false)} onCreated={load} />

      {/* Detail Modal */}
      <Modal title={t('management.issues.detailTitle', { id: detailModal?.id || '' })} open={!!detailModal}
        onCancel={closeDetail} footer={null} width={700}>
        {detailModal && (
          <>
            <Descriptions bordered size="small" column={2} className="issue-detail__descriptions" style={{ marginBottom: 16 }}>
              <Descriptions.Item label={t('management.title')} span={2}>{detailModal.title}</Descriptions.Item>
              {detailModal.description && (
                <Descriptions.Item label={t('management.issues.description')} span={2}>{detailModal.description}</Descriptions.Item>
              )}
              <Descriptions.Item label={t('management.issues.reporter')}>{detailModal.username || '-'}</Descriptions.Item>
              <Descriptions.Item label={t('management.script')}>{detailModal.script_name || '-'}</Descriptions.Item>
              <Descriptions.Item label={t('management.issues.scriptVersion')}>{detailModal.script_version ?? '-'}</Descriptions.Item>
              <Descriptions.Item label={t('management.issues.diagnosticState')}>{{ collected: t('management.issues.collected'), not_collected: t('management.issues.notSelected'), expired: t('management.issues.expired'), legacy: t('management.issues.legacy') }[detailModal.diagnostic_state] || detailModal.diagnostic_state}</Descriptions.Item>
              <Descriptions.Item label={t('management.issues.clientVersions')}>{detailModal.diagnostic_metadata?.client_version || t('management.issues.notCollected')} / {detailModal.diagnostic_metadata?.agent_version || t('management.issues.notCollected')}</Descriptions.Item>
              <Descriptions.Item label={t('management.issues.collectionState')}>{Object.hasOwn(collectionKeys, detailModal.diagnostic_metadata?.collection_state) ? t(collectionKeys[detailModal.diagnostic_metadata.collection_state]) : detailModal.diagnostic_metadata?.collection_state || t('management.issues.notCollected')}</Descriptions.Item>
              <Descriptions.Item label={t('management.status')}>
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
                <Descriptions.Item label={t('management.issues.errorMessage')} span={2}>
                  <pre style={{ margin: 0, color: '#ff4d4f', whiteSpace: 'pre-wrap', fontSize: 12 }}>{detailModal.error_msg}</pre>
                </Descriptions.Item>
              )}
              {detailParams.text !== '' && (
                <Descriptions.Item label={t('management.issues.runParams')} span={2}>
                  {detailParams.invalid && (
                    <p role="status">{t('management.issues.invalidParams')}</p>
                  )}
                  <pre className="issue-detail__params">{detailParams.text}</pre>
                </Descriptions.Item>
              )}
              {detailModal.resolve_note && (
                <Descriptions.Item label={t('management.issues.resolveNote')} span={2}>
                  <div className="issue-detail__note">{detailModal.resolve_note}</div>
                </Descriptions.Item>
              )}
            </Descriptions>
            {detailModal.diagnostic_state === 'collected' && <Button onClick={download} loading={downloading}>{t('management.issues.download')}</Button>}
            <p>{t('management.issues.diagnosticHint')}</p>
            {detailModal.run_id && (
              <div>
                <h4>{t('management.issues.runLog')}</h4>
                <pre style={{
                  background: '#1e1e1e', color: '#d4d4d4', padding: 16,
                  borderRadius: 4, maxHeight: 300, overflow: 'auto',
                  fontSize: 12, lineHeight: 1.5, whiteSpace: 'pre-wrap',
                }}>
                  {detailLoading ? t('management.loading')
                    : detailLog === emptyIssueLog ? t('management.issues.emptyLog')
                    : detailLog === failedIssueLog ? t('management.issues.logFailed') : detailLog}
                </pre>
              </div>
            )}
          </>
        )}
      </Modal>

      {/* Resolve Modal */}
      <Modal title={t('management.issues.markResolved')} open={!!resolveModal} onCancel={() => setResolveModal(null)}
        confirmLoading={resolving} onOk={() => resolveForm.submit()} okText={t('management.confirm')} cancelText={t('management.cancel')}>
        <Form form={resolveForm} layout="vertical" onFinish={onResolve}>
          <Form.Item name="resolve_note" label={t('management.issues.resolveNote')} rules={[{ required: true, message: t('management.required') }]}>
            <Input.TextArea rows={3} placeholder={t('management.issues.resolvePlaceholder')} />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
