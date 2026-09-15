import { useEffect, useRef, useState } from 'react'
import { Alert, Button, Checkbox, Form, Input, Modal, Space, message } from 'antd'
import api from '../api/client'
import { safeError } from '../utils/safeError'
import { useConnection } from '../contexts/ConnectionContext'
import { createDiagnosticPreview, diagnosticRequest } from '../utils/diagnosticReport'
import { useI18n } from '../i18n/useI18n'

export default function DiagnosticReport({ open, onCancel, onCreated, runId, scriptVersion }) {
  const { t } = useI18n()
  const { agentOnline, localApi, online } = useConnection()
  const [form] = Form.useForm()
  const [local, setLocal] = useState(null)
  const [selection, setSelection] = useState({})
  const [consent, setConsent] = useState(false)
  const [confirmed, setConfirmed] = useState(false)
  const [preview, setPreview] = useState(null)
  const [busy, setBusy] = useState(false)
  const [collection, setCollection] = useState('workspace.report.notCollected')
  const [flow] = useState(() => createDiagnosticPreview(api))
  const epoch = useRef(0)
  useEffect(() => () => { epoch.current++; flow.cancel() }, [flow])
  const invalidate = () => { flow.cancel(); setPreview(null); setConfirmed(false) }
  const close = () => {
    epoch.current++; invalidate(); setLocal(null); setSelection({}); setConsent(false)
    setCollection('workspace.report.notCollected'); setBusy(false); form.resetFields(); onCancel()
  }
  const collect = async () => {
    const current = ++epoch.current
    invalidate(); setBusy(true)
    try {
      const r = await localApi.get('/local/diagnostics')
      if (current !== epoch.current) return
      setLocal(r.data); setSelection({}); setConsent(false)
      setCollection(r.data.collection_state === 'collected' ? 'workspace.report.collected' : 'workspace.report.partial')
    } catch {
      if (current === epoch.current) { setLocal(null); setCollection('workspace.report.collectionFailed') }
    } finally { if (current === epoch.current) setBusy(false) }
  }
  const select = (key, value) => { invalidate(); setConsent(false); setSelection(s => ({ ...s, [key]: value })) }
  const sendPreview = async values => {
    const current = epoch.current
    setBusy(true)
    try {
      const request = diagnosticRequest({ values, runId, local, selection, consent })
      const result = await flow.preview(request)
      if (result && current === epoch.current) setPreview(result)
    } catch (e) { if (current === epoch.current) message.error(safeError(e, t('workspace.report.previewFailed'))) }
    finally { if (current === epoch.current) setBusy(false) }
  }
  const submit = async () => {
    if (!confirmed) return
    setBusy(true)
    try {
      await flow.submit(); message.success(t('workspace.report.created')); close(); onCreated?.()
    } catch (e) { message.error(safeError(e, t('workspace.report.submitFailed'))); invalidate() }
    finally { setBusy(false) }
  }
  const selectedLocal = { ...Object.fromEntries(Object.entries(local || {}).filter(([key]) => key !== 'application_logs' && selection.summary)), application_logs: Object.fromEntries(['agent', 'desktop'].filter(key => selection[key] && local?.application_logs?.[key] !== undefined).map(key => [key, local.application_logs[key]])) }
  return <Modal title={t('workspace.report.title')} open={open} onCancel={busy && preview ? undefined : close} width={760} footer={null} mask={{ closable: false }}>
    <Space orientation="vertical" style={{ width: '100%' }}>
      <Alert type="info" showIcon title={runId ? t('workspace.report.run', { id: runId, version: scriptVersion ?? t('workspace.unknown') }) : t('workspace.report.general')} description={t('workspace.report.privacy')} />
      <div role="status">{t('workspace.report.collectionStatus')}{agentOnline ? t(collection) : t('workspace.report.noAgent')}{local && t('workspace.report.versions', { client: local.client_version || t('workspace.unknown'), agent: local.agent_version || t('workspace.unknown') })}</div>
      <Button onClick={collect} disabled={!agentOnline || busy}>{t('workspace.report.collect')}</Button>
      <Form form={form} layout="vertical" onFinish={sendPreview} onValuesChange={invalidate} disabled={busy} style={{ width: '100%' }}>
        <Form.Item name="title" label={t('workspace.report.issueTitle')} rules={[{ required: true, whitespace: true, message: t('workspace.report.titleRequired') }]}><Input maxLength={200} /></Form.Item>
        <Form.Item name="description" label={t('workspace.report.description')}><Input.TextArea rows={3} maxLength={8000} showCount /></Form.Item>
        <Space orientation="vertical">
          <Checkbox checked={!!selection.summary} disabled={busy || (!local && !runId)} onChange={e => select('summary', e.target.checked)}>{t(runId ? 'workspace.report.attachRunSummary' : 'workspace.report.attachSummary')}</Checkbox>
          {['agent', 'desktop'].map(key => <Checkbox key={key} checked={!!selection[key]} disabled={busy || local?.application_logs?.[key] === undefined} onChange={e => select(key, e.target.checked)}>{t(key === 'agent' ? 'workspace.report.attachAgent' : 'workspace.report.attachDesktop')}</Checkbox>)}
          {runId && <Checkbox checked={!!selection.runLog} disabled={busy} onChange={e => select('runLog', e.target.checked)}>{t('workspace.report.attachRunLog')}</Checkbox>}
        </Space>
        <p>{t('workspace.report.logsHelp')}</p>
        {local && <><h4>{t('workspace.report.localPreview')}</h4><pre style={{ maxHeight: 220, overflow: 'auto', whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{JSON.stringify(selectedLocal, null, 2)}</pre></>}
        <Checkbox checked={consent} disabled={busy} onChange={e => { invalidate(); setConsent(e.target.checked) }}>{t('workspace.report.consent')}</Checkbox>
        <Alert style={{ marginBlock: 12 }} type="warning" showIcon title={t('workspace.report.previewWarning')} />
        <Button htmlType="submit" disabled={busy || !online} loading={busy && !preview}>{t('workspace.report.sendPreview')}</Button>
        {!online && <p role="status">{t('workspace.report.offline')}</p>}
      </Form>
      {preview && <>
        <h4>{t('workspace.report.serverPreview', { bytes: preview.size_bytes })}</h4>
        <pre style={{ maxHeight: 300, overflow: 'auto', whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', width: '100%' }}>{JSON.stringify(preview.preview, null, 2)}</pre>
        <Checkbox checked={confirmed} disabled={busy} onChange={e => setConfirmed(e.target.checked)}>{t('workspace.report.confirm')}</Checkbox>
        <Button type="primary" onClick={submit} disabled={!confirmed || busy || !online} loading={busy}>{t('workspace.report.submit')}</Button>
      </>}
      <Button onClick={close} disabled={busy && !!preview}>{t('workspace.cancel')}</Button>
    </Space>
  </Modal>
}
