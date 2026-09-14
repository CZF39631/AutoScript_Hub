import { useEffect, useRef, useState } from 'react'
import { Alert, Button, Checkbox, Form, Input, Modal, Space, message } from 'antd'
import api from '../api/client'
import { safeError } from '../utils/safeError'
import { useConnection } from '../contexts/ConnectionContext'
import { createDiagnosticPreview, diagnosticRequest } from '../utils/diagnosticReport'

export default function DiagnosticReport({ open, onCancel, onCreated, runId, scriptVersion }) {
  const { agentOnline, localApi, online } = useConnection()
  const [form] = Form.useForm()
  const [local, setLocal] = useState(null)
  const [selection, setSelection] = useState({})
  const [consent, setConsent] = useState(false)
  const [confirmed, setConfirmed] = useState(false)
  const [preview, setPreview] = useState(null)
  const [busy, setBusy] = useState(false)
  const [collection, setCollection] = useState('未采集')
  const [flow] = useState(() => createDiagnosticPreview(api))
  const epoch = useRef(0)
  useEffect(() => () => { epoch.current++; flow.cancel() }, [flow])
  const invalidate = () => { flow.cancel(); setPreview(null); setConfirmed(false) }
  const close = () => {
    epoch.current++; invalidate(); setLocal(null); setSelection({}); setConsent(false)
    setCollection('未采集'); setBusy(false); form.resetFields(); onCancel()
  }
  const collect = async () => {
    const current = ++epoch.current
    invalidate(); setBusy(true)
    try {
      const r = await localApi.get('/local/diagnostics')
      if (current !== epoch.current) return
      setLocal(r.data); setSelection({}); setConsent(false)
      setCollection(r.data.collection_state === 'collected' ? '已采集（尚未上传）' : '部分采集（尚未上传）')
    } catch {
      if (current === epoch.current) { setLocal(null); setCollection('采集失败，可不附诊断继续报单') }
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
    } catch (e) { if (current === epoch.current) message.error(safeError(e, '预览失败')) }
    finally { if (current === epoch.current) setBusy(false) }
  }
  const submit = async () => {
    if (!confirmed) return
    setBusy(true)
    try {
      await flow.submit(); message.success('问题已上报'); close(); onCreated?.()
    } catch (e) { message.error(safeError(e, '上报失败，请重新预览')); invalidate() }
    finally { setBusy(false) }
  }
  const selectedLocal = { ...Object.fromEntries(Object.entries(local || {}).filter(([key]) => key !== 'application_logs' && selection.summary)), application_logs: Object.fromEntries(['agent', 'desktop'].filter(key => selection[key] && local?.application_logs?.[key] !== undefined).map(key => [key, local.application_logs[key]])) }
  return <Modal title="上报问题" open={open} onCancel={busy && preview ? undefined : close} width={760} footer={null} mask={{ closable: false }}>
    <Space orientation="vertical" style={{ width: '100%' }}>
      <Alert type="info" showIcon title={runId ? `执行 #${runId} · 固定脚本版本 ${scriptVersion ?? '未知'}` : '通用问题反馈（无需客户端 Agent）'} description="默认不附带诊断。工单标题和描述会发送服务器；不要填写密码或 Token。" />
      <div role="status">采集状态：{agentOnline ? collection : '未连接本机 Agent，可直接报单'}{local && ` · 客户端 ${local.client_version || '未知'} · Agent ${local.agent_version || '未知'}`}</div>
      <Button onClick={collect} disabled={!agentOnline || busy}>在本机采集白名单诊断（不上传）</Button>
      <Form form={form} layout="vertical" onFinish={sendPreview} onValuesChange={invalidate} disabled={busy} style={{ width: '100%' }}>
        <Form.Item name="title" label="问题标题" rules={[{ required: true, whitespace: true, message: '请填写问题标题' }]}><Input maxLength={200} /></Form.Item>
        <Form.Item name="description" label="详细描述"><Input.TextArea rows={3} maxLength={8000} showCount /></Form.Item>
        <Space orientation="vertical">
          <Checkbox checked={!!selection.summary} disabled={busy || (!local && !runId)} onChange={e => select('summary', e.target.checked)}>附带版本、系统摘要{runId ? '及执行参数、错误摘要' : ''}</Checkbox>
          {['agent', 'desktop'].map(key => <Checkbox key={key} checked={!!selection[key]} disabled={busy || local?.application_logs?.[key] === undefined} onChange={e => select(key, e.target.checked)}>附带 {key === 'agent' ? 'Agent' : '桌面'} 应用日志</Checkbox>)}
          {runId && <Checkbox checked={!!selection.runLog} disabled={busy} onChange={e => select('runLog', e.target.checked)}>附带服务器执行日志（服务器预览时读取）</Checkbox>}
        </Space>
        <p>日志仅限白名单末尾片段，不收集配置、环境变量或结果文件。落盘日志始终做基础脱敏，关闭上传脱敏不能恢复已移除的原文。</p>
        {local && <><h4>本机所选内容（尚未发送）</h4><pre style={{ maxHeight: 220, overflow: 'auto', whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{JSON.stringify(selectedLocal, null, 2)}</pre></>}
        <Checkbox checked={consent} disabled={busy} onChange={e => { invalidate(); setConsent(e.target.checked) }}>我同意将所选诊断发送服务器预览，并在提交后供有权限的工单处理者查看</Checkbox>
        <Alert style={{ marginBlock: 12 }} type="warning" showIcon title="下一步不是本地预览：将标题、描述及所选内容发送服务器，按当前策略处理；尚不创建工单。取消无法撤回已发送的预览请求。" />
        <Button htmlType="submit" disabled={busy || !online} loading={busy && !preview}>发送服务器预览（不创建工单）</Button>
        {!online && <p role="status">服务器离线，恢复连接后才能报单。</p>}
      </Form>
      {preview && <>
        <h4>服务器处理后的内容 · {preview.size_bytes} 字节</h4>
        <pre style={{ maxHeight: 300, overflow: 'auto', whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', width: '100%' }}>{JSON.stringify(preview.preview, null, 2)}</pre>
        <Checkbox checked={confirmed} disabled={busy} onChange={e => setConfirmed(e.target.checked)}>已检查预览，确认创建工单（提交时服务器会重新检查权限和当前策略）</Checkbox>
        <Button type="primary" onClick={submit} disabled={!confirmed || busy || !online} loading={busy}>确认提交工单</Button>
      </>}
      <Button onClick={close} disabled={busy && !!preview}>取消</Button>
    </Space>
  </Modal>
}
