import { useCallback, useEffect, useRef, useState } from 'react'
import { Alert, Button, Checkbox, Form, Input, InputNumber, Modal, Popconfirm, Select, Space, Table, Tabs, Tag, Typography, message } from 'antd'
import { PlusOutlined, ReloadOutlined } from '@ant-design/icons'
import { Link } from 'react-router-dom'
import api from '../api/client'
import { useConnection } from '../contexts/ConnectionContext'
import { formatServerTime } from '../utils/dateTime'
import { makeTrigger, newRequestId, taskError, taskStates, triggerLabel } from '../utils/taskScheduling'

import { useI18n } from '../i18n/useI18n'

const buttonStyle = { whiteSpace: 'normal', height: 'auto', minHeight: 32, paddingBlock: 4 }
const activeStates = ['queued', 'claimed', 'running', 'cancel_requested', 'unknown']
function State({ value }) {
  const { t } = useI18n()
  const [label, color] = taskStates[value] || [value || '—', 'default']
  return <Tag color={color}>{Object.hasOwn(taskStates, value) ? t(label) : label}</Tag>
}

function ParameterFields({ definitions }) {
  const { t } = useI18n()
  return definitions.map(p => {
    const isCheckbox = ['bool', 'checkbox'].includes(p.type)
    const rules = p.required && !isCheckbox ? [{ required: true, message: t('execution.fillParameter', { label: p.label || p.key }) }] : []
    let control = <Input placeholder={['file', 'folder'].includes(p.type) ? t('execution.fullPath') : undefined} />
    if (isCheckbox) control = <Checkbox>{p.label || p.key}</Checkbox>
    if (p.type === 'number') control = <InputNumber style={{ width: '100%' }} min={p.min} max={p.max} />
    if (p.type === 'select') control = <Select options={(p.options || []).map(o => ({ label: String(o), value: o }))} />
    if (p.secret || p.sensitive || p.type === 'password') control = <Input.Password autoComplete="new-password" />
    return <Form.Item key={p.key} name={['params', p.key]} label={isCheckbox ? undefined : p.label || p.key} valuePropName={isCheckbox ? 'checked' : 'value'} rules={rules} extra={p.description}>{control}</Form.Item>
  })
}

function TaskEditor({ local, localApi, devices, grantOnly, onCancel, onSaved }) {
  const { t } = useI18n()
  const weekdays = Array.from({ length: 7 }, (_, value) => ({ label: t(`execution.weekday.${value}`), value }))
  const [form] = Form.useForm()
  const [scripts, setScripts] = useState([])
  const [versions, setVersions] = useState([])
  const [definitions, setDefinitions] = useState([])
  const [configReady, setConfigReady] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const generation = useRef(0)
  const saving = useRef(false)
  const invalidateSelection = useCallback(() => { generation.current++ }, [])
  const kind = Form.useWatch('kind', form)
  const misfire = Form.useWatch('misfire', form)
  useEffect(() => {
    let active = true
    const request = local ? localApi.get('/local/scripts') : api.get('/api/scripts/marketplace')
    request.then(r => { if (active) setScripts(r.data || []) }).catch(e => { if (active) setError(e) })
    return () => { active = false; invalidateSelection() }
  }, [local, localApi, invalidateSelection])
  const applyConfig = config => {
    const params = Array.isArray(config?.params) ? config.params : []
    setDefinitions(params)
    form.setFieldValue('params', Object.fromEntries(params.map(p => [p.key, p.default ?? (['bool', 'checkbox'].includes(p.type) ? false : undefined)])))
    setConfigReady(true)
  }
  const chooseVersion = async (version, scriptId = form.getFieldValue('script_id')) => {
    const current = ++generation.current
    setConfigReady(false)
    setDefinitions([])
    setError('')
    try {
      const r = await api.get(`/api/scripts/${scriptId}/versions/${version}/config`)
      if (current === generation.current) applyConfig(r.data.config)
    } catch (e) { if (current === generation.current) setError(e) }
  }
  const chooseScript = async id => {
    const current = ++generation.current
    setVersions([])
    setDefinitions([])
    setConfigReady(false)
    setError('')
    form.setFieldsValue({ script_version: undefined, params: {} })
    try {
      if (local) {
        const script = scripts.find(s => s.id === id)
        const config = script.config || JSON.parse(script.config_json)
        setVersions([{ version: script.latest_version }])
        form.setFieldValue('script_version', script.latest_version)
        applyConfig(config)
      } else {
        const r = await api.get(`/api/scripts/${id}/versions`)
        if (current !== generation.current) return
        setVersions(r.data || [])
        if (r.data?.length) {
          form.setFieldValue('script_version', r.data[0].version)
          await chooseVersion(r.data[0].version, id)
        }
      }
    } catch (e) { if (current === generation.current) setError(e) }
  }
  const save = async values => {
    if (saving.current || !configReady) return
    saving.current = true
    setLoading(true)
    setError('')
    try {
      let notice = t('execution.taskCreated')
      if (grantOnly) {
        const response = await api.post(`/api/task-devices/${values.device_id}/grants`, { script_id: values.script_id, script_version: values.script_version })
        notice = t(['rejected', 'revoked'].includes(response.data.status) ? 'execution.grantPreviouslyDenied' : response.data.status === 'accepted' ? 'execution.grantExists' : 'execution.grantSent')
      } else {
        const payload = {
          name: values.name, script_id: values.script_id, script_version: values.script_version,
          params: values.params || {}, trigger: makeTrigger(values, t), timeout_seconds: values.timeout_seconds,
          requires_desktop: values.requires_desktop, requires_browser: values.requires_browser,
          ...(!local && { device_id: values.device_id }),
        }
        await (local ? localApi : api).post(local ? '/local/schedules' : '/api/tasks', payload)
      }
      message.success(notice)
      onSaved()
    } catch (e) { setError(e) } finally { saving.current = false; setLoading(false) }
  }
  return <Modal open title={t(grantOnly ? 'execution.requestGrant' : local ? 'execution.newLocalTask' : 'execution.newRemoteTask')} width={640} onCancel={loading ? undefined : onCancel} mask={{ closable: false }} footer={<Space wrap><Button style={buttonStyle} onClick={onCancel} disabled={loading}>{t('execution.cancel')}</Button><Button style={buttonStyle} type="primary" loading={loading} disabled={!configReady} onClick={() => form.submit()}>{t(grantOnly ? 'execution.sendRequest' : 'execution.createTask')}</Button></Space>}>
    <Form form={form} layout="vertical" onFinish={save} initialValues={{ kind: 'manual', timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || 'Asia/Shanghai', misfire: 'skip', grace_seconds: 300, timeout_seconds: 600, requires_desktop: false, requires_browser: false }}>
      {error && <Alert type="error" showIcon title={taskError(error, t)} style={{ marginBottom: 16 }} />}
      {!grantOnly && <Form.Item name="name" label={t('execution.taskName')} rules={[{ required: true, whitespace: true }]}><Input maxLength={200} /></Form.Item>}
      {!local && <Form.Item name="device_id" label={t('execution.targetDeviceId')} extra={t(grantOnly ? 'execution.deviceIdHint' : 'execution.deviceGrantHint')} rules={[{ required: true }]}>
        {grantOnly ? <InputNumber min={1} precision={0} style={{ width: '100%' }} /> : <Select options={devices.map(d => ({ value: d.id, label: t('execution.deviceOption', { name: d.name, id: d.id, status: t(d.status === 'online' ? 'execution.online' : 'execution.offline') }) }))} />}
      </Form.Item>}
      <Form.Item name="script_id" label={t('execution.script')} rules={[{ required: true }]}><Select showSearch optionFilterProp="label" placeholder={t(local ? 'execution.selectDownloaded' : 'execution.selectAccessible')} options={scripts.map(s => ({ value: s.id, label: s.name }))} onChange={chooseScript} /></Form.Item>
      <Form.Item name="script_version" label={t('execution.pinnedVersion')} extra={t('execution.pinnedVersionHint')} rules={[{ required: true }]}><Select options={versions.map(v => ({ value: v.version, label: t('execution.versionOption', { version: v.version, semantic: v.semantic_version ? ` (${v.semantic_version})` : '' }) }))} onChange={local ? undefined : value => chooseVersion(value)} /></Form.Item>
      {!grantOnly && <>
        <ParameterFields definitions={definitions} />
        <Form.Item name="kind" label={t('execution.trigger')}><Select options={['manual', 'once', 'daily', 'weekly'].map(value => ({ value, label: t(`execution.trigger.${value}`) }))} /></Form.Item>
        <Form.Item name="timezone" label={t('execution.timezone')} rules={[{ required: true }]}><Input placeholder="Asia/Shanghai" /></Form.Item>
        {kind === 'once' && <Form.Item name="start_at" label={t('execution.onceTime')} rules={[{ required: true }]}><Input placeholder="2026-09-14T09:00:00+08:00" /></Form.Item>}
        {['daily', 'weekly'].includes(kind) && <Form.Item name="time" label={t('execution.recurringTime')} rules={[{ required: true }]}><Input type="time" /></Form.Item>}
        {kind === 'weekly' && <Form.Item name="weekdays" label={t('execution.weekdays')} rules={[{ required: true }]}><Checkbox.Group options={weekdays} /></Form.Item>}
        {kind !== 'manual' && <>
          <Form.Item name="misfire" label={t('execution.misfire')}><Select options={[{ value: 'skip', label: t('execution.misfireSkip') }, { value: 'run_once', label: t('execution.misfireOnce') }]} /></Form.Item>
          {misfire === 'run_once' && <Form.Item name="grace_seconds" label={t('execution.graceSeconds')} rules={[{ required: true }]}><InputNumber min={1} max={86400} precision={0} /></Form.Item>}
        </>}
        <Form.Item name="timeout_seconds" label={t('execution.timeout')} rules={[{ required: true }]}><InputNumber min={1} max={86400} precision={0} /></Form.Item>
        <Form.Item name="requires_desktop" valuePropName="checked"><Checkbox>{t('execution.requiresDesktop')}</Checkbox></Form.Item>
        <Form.Item name="requires_browser" valuePropName="checked"><Checkbox>{t('execution.requiresBrowser')}</Checkbox></Form.Item>
        <Typography.Paragraph type="secondary">{t(local ? 'execution.localSafety' : 'execution.remoteSafety')} {t('execution.noUnknownRetry')}</Typography.Paragraph>
      </>}
    </Form>
  </Modal>
}

export default function Tasks() {
  const { t } = useI18n()
  const { online, agentOnline, localApi } = useConnection()
  const [source, setSource] = useState('remote')
  const [loadedSource, setLoadedSource] = useState(null)
  const [tasks, setTasks] = useState([])
  const [events, setEvents] = useState([])
  const [devices, setDevices] = useState([])
  const [grants, setGrants] = useState([])
  const [device, setDevice] = useState(null)
  const [loading, setLoading] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [editor, setEditor] = useState(null)
  const serial = useRef(0)
  const invalidateRequests = useCallback(() => { serial.current++ }, [])
  const inFlight = useRef(false)
  const requestIds = useRef(new Map())
  const local = source === 'local'
  const available = local ? agentOnline : online
  const load = useCallback(async () => {
    const id = ++serial.current
    if (!(local ? agentOnline : online)) {
      setTasks([]); setEvents([]); setGrants([]); setDevices([]); setDevice(null)
      setError(t(local ? 'execution.agentUnavailable' : 'execution.serverUnavailable'))
      setLoading(false)
      setLoadedSource(null)
      return
    }
    setLoading(true)
    try {
      const paths = local ? ['/local/schedules', '/local/schedule-events', '/local/device-grants', '/local/task-device'] : ['/api/tasks', '/api/tasks/executions', '/api/tasks/grants', '/api/task-devices']
      const client = local ? localApi : api
      const results = await Promise.all(paths.map(path => client.get(path)))
      if (serial.current !== id) return
      setTasks(results[0].data || []); setEvents(results[1].data || []); setGrants(results[2].data || [])
      if (local) { setDevice(results[3].data); setDevices([]) } else { setDevices(results[3].data || []); setDevice(null) }
      setError('')
      setLoadedSource(local ? 'local' : 'remote')
    } catch (e) {
      if (serial.current === id) setError(e.response?.status === 404 ? t('execution.schedulingUnsupported') : taskError(e, t))
    } finally { if (serial.current === id) setLoading(false) }
  }, [local, agentOnline, online, localApi, t])
  useEffect(() => {
    load()
    const timer = setInterval(load, 5000)
    return () => { invalidateRequests(); clearInterval(timer) }
  }, [load, invalidateRequests])
  const mutate = async (url, body, useLocal = local) => {
    if (inFlight.current) return
    inFlight.current = true; setBusy(true)
    try { await (useLocal ? localApi : api).post(url, body); await load(); return true }
    catch (e) { message.error(taskError(e, t)); return false }
    finally { inFlight.current = false; setBusy(false) }
  }
  const action = async (task, actionName) => {
    const key = `${source}:${task.id}`
    if (actionName === 'run' && !requestIds.current.has(key)) requestIds.current.set(key, newRequestId())
    const result = await mutate(`${local ? '/local/schedules' : '/api/tasks'}/${task.id}/action`, { action: actionName, ...(actionName === 'run' && { request_id: requestIds.current.get(key) }) })
    if (result) { requestIds.current.delete(key); message.success(t(actionName === 'run' ? 'execution.runAccepted' : 'execution.taskUpdated')) }
  }
  const disabled = busy || !available || !!error || loadedSource !== source
  const deviceLabel = id => t('execution.deviceLabel', { name: devices.find(d => d.id === id)?.name || t('execution.device'), id })
  const scriptVersionLabel = row => t('execution.scriptVersionLabel', { script: row.script_id, version: row.script_version })
  const taskColumns = [
    { title: t('execution.task'), dataIndex: 'name', render: (name, row) => <><strong>{name}</strong><div>{scriptVersionLabel(row)}</div></> },
    ...(!local ? [{ title: t('execution.targetDevice'), dataIndex: 'device_id', render: deviceLabel }] : []),
    { title: t('execution.schedule'), dataIndex: 'trigger', render: value => triggerLabel(value, t) },
    { title: t('execution.status'), dataIndex: 'enabled', render: value => <Tag color={value ? 'green' : 'default'}>{t(value ? 'execution.enabled' : 'execution.paused')}</Tag> },
    { title: t('execution.nextRun'), dataIndex: 'next_fire_at', render: value => value ? formatServerTime(value) : '—' },
    { title: t('execution.actions'), key: 'actions', fixed: 'right', width: 230, render: (_, row) => <Space wrap>
      <Popconfirm title={t('execution.runOnceConfirm')} description={t('execution.runOnceHint', { device: local ? t('execution.thisComputer') : deviceLabel(row.device_id), script: row.script_id, version: row.script_version })} onConfirm={() => action(row, 'run')} disabled={disabled || !row.enabled}><Button style={buttonStyle} size="small" disabled={disabled || !row.enabled} title={!row.enabled ? t('execution.resumeHint') : undefined}>{t('execution.runOnce')}</Button></Popconfirm>
      <Button style={buttonStyle} size="small" disabled={disabled} onClick={() => action(row, row.enabled ? 'pause' : 'resume')}>{t(row.enabled ? 'execution.pause' : 'execution.resume')}</Button>
      <Popconfirm title={t('execution.deleteConfirm')} description={t('execution.deleteHint')} onConfirm={() => action(row, 'delete')} disabled={disabled}><Button style={buttonStyle} danger size="small" disabled={disabled}>{t('execution.delete')}</Button></Popconfirm>
    </Space> },
  ]
  const eventColumns = [
    { title: t('execution.task'), key: 'task', render: (_, row) => row.task_name || t('execution.taskId', { id: row.task_id }) },
    { title: t('execution.status'), key: 'state', render: (_, row) => <State value={row.state || row.status} /> },
    { title: t('execution.scheduledFor'), dataIndex: 'scheduled_for', render: value => value ? formatServerTime(value) : t('execution.manualTrigger') },
    { title: t('execution.explanation'), dataIndex: 'error_msg', render: value => <span style={{ overflowWrap: 'anywhere' }}>{value || '—'}</span> },
    { title: t('execution.actions'), key: 'actions', render: (_, row) => {
      const runId = local ? row.local_run_id || row.run_id : row.run_id
      const cancellable = activeStates.includes(row.state || row.status) && (!local || runId)
      return <Space wrap>{runId && <Link to={`/runs/${encodeURIComponent(runId)}`}>{t('execution.runDetails')}</Link>}{cancellable && <Popconfirm title={t('execution.cancelConfirm')} description={t('execution.cancelUnknownHint')} disabled={disabled} onConfirm={() => mutate(local ? `/local/runs/${runId}/cancel` : `/api/tasks/executions/${row.id}/cancel`, {})}><Button style={buttonStyle} size="small" disabled={disabled || (row.state || row.status) === 'cancel_requested'}>{t('execution.cancelRun')}</Button></Popconfirm>}</Space>
    } },
  ]
  const grantColumns = [
    { title: t('execution.requester'), key: 'requester', render: (_, row) => row.requester_name || row.requester_display_name || t('execution.userId', { id: row.requester_id }) },
    { title: t('execution.device'), dataIndex: 'device_id', render: value => `#${value}` },
    { title: t('execution.scriptVersion'), key: 'version', render: (_, row) => scriptVersionLabel(row) },
    { title: t('execution.status'), dataIndex: 'status', render: value => <State value={value} /> },
    ...(local ? [{ title: t('execution.localConfirmation'), key: 'decision', render: (_, row) => <Space wrap>{(row.status === 'pending' ? ['accept', 'reject'] : row.status === 'accepted' ? ['revoke'] : ['rejected', 'revoked'].includes(row.status) ? ['accept'] : []).map(decision => <Popconfirm key={decision} title={t(`execution.grantConfirm.${decision}`)} description={t(decision === 'accept' ? 'execution.grantSafety' : 'execution.grantStopHint')} disabled={disabled} onConfirm={() => mutate(`/local/device-grants/${row.id}/decision`, { decision }, true)}><Button style={buttonStyle} size="small" danger={decision === 'revoke'} disabled={disabled}>{t(decision === 'accept' && row.status !== 'pending' ? 'execution.grantAction.reaccept' : `execution.grantAction.${decision}`)}</Button></Popconfirm>)}</Space> }] : []),
  ]
  return <div>
    <div className="page-heading" style={{ flexWrap: 'wrap', gap: 16 }}><h2>{t('execution.scheduling')}</h2><Space wrap><Button style={buttonStyle} icon={<ReloadOutlined />} onClick={load} loading={loading}>{t('execution.refresh')}</Button>{!local && <Button style={buttonStyle} disabled={disabled} onClick={() => setEditor('grant')}>{t('execution.requestGrant')}</Button>}<Button style={buttonStyle} type="primary" icon={<PlusOutlined />} disabled={disabled} onClick={() => setEditor('task')}>{t('execution.newTask')}</Button></Space></div>
    <Tabs activeKey={source} onChange={value => { if (!busy) { setSource(value); setEditor(null) } }} items={[{ key: 'remote', label: t('execution.remoteTasks'), disabled: busy }, { key: 'local', label: t('execution.localTasks'), disabled: busy }]} />
    {error && <Alert type="error" title={error} showIcon style={{ marginBottom: 16 }} />}
    <Typography.Paragraph type="secondary">{local ? <>{t('execution.localTasksHint')} {device?.id ? t('execution.shareDeviceId', { id: device.id }) : t('execution.deviceUnregistered')}</> : t('execution.remoteTasksHint')}</Typography.Paragraph>
    <Tabs items={[
      { key: 'tasks', label: t('execution.taskList'), children: <Table rowKey="id" loading={loading} columns={taskColumns} dataSource={loadedSource === source ? tasks : []} scroll={{ x: 900 }} locale={{ emptyText: t(local ? 'execution.noLocalTasks' : 'execution.noRemoteTasks') }} /> },
      { key: 'events', label: t('execution.recentRuns'), children: <><Alert type="info" showIcon title={t('execution.unknownEventHint')} style={{ marginBottom: 16 }} /><Table rowKey="id" columns={eventColumns} dataSource={loadedSource === source ? events : []} scroll={{ x: 800 }} /></> },
      { key: 'grants', label: t('execution.deviceGrants'), children: <Table rowKey="id" columns={grantColumns} dataSource={loadedSource === source ? grants : []} scroll={{ x: 700 }} /> },
    ]} />
    {editor && <TaskEditor local={local} localApi={localApi} devices={devices} grantOnly={editor === 'grant'} onCancel={() => setEditor(null)} onSaved={() => { setEditor(null); load() }} />}
  </div>
}
