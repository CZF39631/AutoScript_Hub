import { useEffect, useState } from 'react'
import { Alert, Button, Card, Form, InputNumber, Modal, Select, Switch, message } from 'antd'
import api from '../api/client'
import { safeError } from '../utils/safeError'

export default function DiagnosticSettings() {
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
      message.success('诊断配置已保存')
    } catch (e) { message.error(safeError(e, '保存失败，请重新加载诊断配置')) }
    finally { setBusy(false) }
  }
  const submit = values => {
    const removed = policy.custom_sensitive_fields.some(field => !values.custom_sensitive_fields.some(v => v.toLowerCase() === field.toLowerCase()))
    const weaker = (policy.enabled && !values.enabled) || ['logs', 'params', 'summary'].some(key => policy.enabled && policy[`redact_${key}`] && !(values.enabled && values[`redact_${key}`]))
    if (removed || weaker) Modal.confirm({ title: '确认降低诊断保护？', content: '关闭保护或移除敏感字段可能向工单查看者暴露凭据与业务数据。权限、大小及保留期限仍然生效。', okText: '确认风险并保存', cancelText: '取消', onOk: () => save(values, true) })
    else void save(values)
  }
  return <Card title="诊断保护（管理员）" style={{ maxWidth: 600, marginTop: 16 }} loading={!policy && !error}>
    {error && <Alert type="error" showIcon title="诊断配置加载失败" action={<Button onClick={load}>重新加载</Button>} />}
    {policy && <Form form={form} layout="vertical" onFinish={submit}>
      <Alert type="info" showIcon title="仅影响诊断脱敏，不关闭访问权限、大小上限和自动过期。" description="应用日志落盘始终做基础脱敏；关闭上传脱敏无法恢复已移除的原文。未识别的敏感信息仍可能存在，上报前必须人工检查。" style={{ marginBottom: 16 }} />
      {[['enabled', '启用脱敏保护'], ['redact_logs', '执行及应用日志脱敏'], ['redact_params', '执行参数脱敏'], ['redact_summary', '错误摘要与说明脱敏']].map(([name, label]) => <Form.Item key={name} name={name} label={label} valuePropName="checked"><Switch /></Form.Item>)}
      <Form.Item name="custom_sensitive_fields" label="自定义敏感字段" extra="输入字段名并按回车，最多 50 项。"><Select mode="tags" maxCount={50} tokenSeparators={[',']} /></Form.Item>
      <Form.Item name="retention_days" label="诊断保留天数" extra="仅新工单按此期限保存；到期即不可读取，后台清除快照和附带执行日志。既有快照保留原到期时间。" rules={[{ required: true }]}><InputNumber min={1} max={365} /></Form.Item>
      <Button type="primary" htmlType="submit" loading={busy}>保存诊断配置</Button>
      <Button type="link" onClick={load} disabled={busy}>重新加载</Button>
    </Form>}
  </Card>
}
