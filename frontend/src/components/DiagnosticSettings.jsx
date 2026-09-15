import { useEffect, useState } from 'react'
import { Alert, Button, Card, Form, InputNumber, Modal, Select, Switch, message } from 'antd'
import api from '../api/client'
import { safeError } from '../utils/safeError'
import { useI18n } from '../i18n/useI18n'

export default function DiagnosticSettings() {
  const { t } = useI18n()
  const [form] = Form.useForm()
  const [policy, setPolicy] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(false)
  const load = () => {
    setError(false)
    api.get('/api/settings/diagnostics').then(r => { setPolicy(r.data); form.setFieldsValue(r.data) }).catch(() => setError(true))
  }
  useEffect(load, [form])
  const save = async (values, acknowledge_risk = false) => {
    setBusy(true)
    try {
      const r = await api.put('/api/settings/diagnostics', { ...values, acknowledge_risk })
      setPolicy(r.data)
      form.setFieldsValue(r.data)
      message.success(t('workspace.diagnostics.saved'))
    } catch (e) { message.error(safeError(e, t('workspace.diagnostics.saveFailed'))) }
    finally { setBusy(false) }
  }
  const submit = values => {
    const removed = policy.custom_sensitive_fields.some(field => !values.custom_sensitive_fields.some(v => v.toLowerCase() === field.toLowerCase()))
    const weaker = (policy.enabled && !values.enabled) || ['logs', 'params', 'summary'].some(key => policy.enabled && policy[`redact_${key}`] && !(values.enabled && values[`redact_${key}`]))
    if (removed || weaker) Modal.confirm({ title: t('workspace.diagnostics.weakenTitle'), content: t('workspace.diagnostics.weakenHelp'), okText: t('workspace.diagnostics.confirmRisk'), cancelText: t('workspace.cancel'), onOk: () => save(values, true) })
    else void save(values)
  }
  return <Card title={t('workspace.diagnostics.title')} style={{ maxWidth: 600, marginTop: 16 }} loading={!policy && !error}>
    {error && <Alert type="error" showIcon title={t('workspace.diagnostics.loadFailed')} action={<Button onClick={load}>{t('workspace.reload')}</Button>} />}
    {policy && <Form form={form} layout="vertical" onFinish={submit}>
      <Alert type="info" showIcon title={t('workspace.diagnostics.scope')} description={t('workspace.diagnostics.scopeHelp')} style={{ marginBottom: 16 }} />
      {[['enabled', 'workspace.diagnostics.enabled'], ['redact_logs', 'workspace.diagnostics.logs'], ['redact_params', 'workspace.diagnostics.params'], ['redact_summary', 'workspace.diagnostics.summary']].map(([name, label]) => <Form.Item key={name} name={name} label={t(label)} valuePropName="checked"><Switch /></Form.Item>)}
      <Form.Item name="custom_sensitive_fields" label={t('workspace.diagnostics.fields')} extra={t('workspace.diagnostics.fieldsHelp')}><Select mode="tags" maxCount={50} tokenSeparators={[',']} /></Form.Item>
      <Form.Item name="retention_days" label={t('workspace.diagnostics.retention')} extra={t('workspace.diagnostics.retentionHelp')} rules={[{ required: true }]}><InputNumber min={1} max={365} /></Form.Item>
      <Button type="primary" htmlType="submit" loading={busy}>{t('workspace.diagnostics.save')}</Button>
      <Button type="link" onClick={load} disabled={busy}>{t('workspace.reload')}</Button>
    </Form>}
  </Card>
}
