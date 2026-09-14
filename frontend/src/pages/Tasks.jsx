import { useCallback, useEffect, useRef, useState } from 'react'
import { Alert, Button, Checkbox, Form, Input, InputNumber, Modal, Popconfirm, Select, Space, Table, Tabs, Tag, Typography, message } from 'antd'
import { PlusOutlined, ReloadOutlined } from '@ant-design/icons'
import { Link } from 'react-router-dom'
import api from '../api/client'
import { useConnection } from '../contexts/ConnectionContext'
import { formatServerTime } from '../utils/dateTime'
import { makeTrigger, newRequestId, taskError, taskStates, triggerLabel } from '../utils/taskScheduling'

const weekdays = ['周一', '周二', '周三', '周四', '周五', '周六', '周日'].map((label, value) => ({ label, value }))
const activeStates = ['queued', 'claimed', 'running', 'cancel_requested', 'unknown']
function State({ value }) {
  const [label, color] = taskStates[value] || [value || '—', 'default']
  return <Tag color={color}>{label}</Tag>
}

function ParameterFields({ definitions }) {
  return definitions.map(p => {
    const isCheckbox = ['bool', 'checkbox'].includes(p.type)
    const rules = p.required && !isCheckbox ? [{ required: true, message: `请填写${p.label || p.key}` }] : []
    let control = <Input placeholder={['file', 'folder'].includes(p.type) ? '目标电脑上的完整路径' : undefined} />
    if (isCheckbox) control = <Checkbox>{p.label || p.key}</Checkbox>
    if (p.type === 'number') control = <InputNumber style={{ width: '100%' }} min={p.min} max={p.max} />
    if (p.type === 'select') control = <Select options={(p.options || []).map(o => ({ label: String(o), value: o }))} />
    if (p.secret || p.sensitive || p.type === 'password') control = <Input.Password autoComplete="new-password" />
    return <Form.Item key={p.key} name={['params', p.key]} label={isCheckbox ? undefined : p.label || p.key} valuePropName={isCheckbox ? 'checked' : 'value'} rules={rules} extra={p.description}>{control}</Form.Item>
  })
}

function TaskEditor({ local, localApi, devices, grantOnly, onCancel, onSaved }) {
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
    request.then(r => { if (active) setScripts(r.data || []) }).catch(e => { if (active) setError(taskError(e)) })
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
    } catch (e) { if (current === generation.current) setError(taskError(e)) }
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
    } catch (e) { if (current === generation.current) setError(taskError(e)) }
  }
  const save = async values => {
    if (saving.current || !configReady) return
    saving.current = true
    setLoading(true)
    setError('')
    try {
      let notice = '任务已创建'
      if (grantOnly) {
        const response = await api.post(`/api/task-devices/${values.device_id}/grants`, { script_id: values.script_id, script_version: values.script_version })
        notice = ['rejected', 'revoked'].includes(response.data.status) ? '该授权曾被拒绝或撤销，请联系设备使用者在本机重新允许' : response.data.status === 'accepted' ? '该固定版本已有设备授权' : '申请已发送，请目标设备使用者在本机确认'
      } else {
        const payload = {
          name: values.name, script_id: values.script_id, script_version: values.script_version,
          params: values.params || {}, trigger: makeTrigger(values), timeout_seconds: values.timeout_seconds,
          requires_desktop: values.requires_desktop, requires_browser: values.requires_browser,
          ...(!local && { device_id: values.device_id }),
        }
        await (local ? localApi : api).post(local ? '/local/schedules' : '/api/tasks', payload)
      }
      message.success(notice)
      onSaved()
    } catch (e) { setError(taskError(e)) } finally { saving.current = false; setLoading(false) }
  }
  return <Modal open title={grantOnly ? '申请设备授权' : `新建${local ? '本机' : '远程'}任务`} width={640} onCancel={loading ? undefined : onCancel} mask={{ closable: false }} footer={<Space><Button onClick={onCancel} disabled={loading}>取消</Button><Button type="primary" loading={loading} disabled={!configReady} onClick={() => form.submit()}>{grantOnly ? '发送申请' : '创建任务'}</Button></Space>}>
    <Form form={form} layout="vertical" onFinish={save} initialValues={{ kind: 'manual', timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || 'Asia/Shanghai', misfire: 'skip', grace_seconds: 300, timeout_seconds: 600, requires_desktop: false, requires_browser: false }}>
      {error && <Alert type="error" showIcon title={error} style={{ marginBottom: 16 }} />}
      {!grantOnly && <Form.Item name="name" label="任务名称" rules={[{ required: true, whitespace: true }]}><Input maxLength={200} /></Form.Item>}
      {!local && <Form.Item name="device_id" label="目标设备编号" extra={grantOnly ? '向设备使用者获取编号；只有在目标电脑上才能批准授权。' : '需要目标设备已批准你执行所选的固定脚本版本。'} rules={[{ required: true }]}>
        {grantOnly ? <InputNumber min={1} precision={0} style={{ width: '100%' }} /> : <Select options={devices.map(d => ({ value: d.id, label: `${d.name}（#${d.id}，${d.status === 'online' ? '在线' : '离线'}）` }))} />}
      </Form.Item>}
      <Form.Item name="script_id" label="脚本" rules={[{ required: true }]}><Select showSearch optionFilterProp="label" placeholder={local ? '选择已下载脚本' : '选择可访问脚本'} options={scripts.map(s => ({ value: s.id, label: s.name }))} onChange={chooseScript} /></Form.Item>
      <Form.Item name="script_version" label="固定版本编号" extra="任务不会自动跟随市场新版本；更换版本需要重新创建任务和授权。" rules={[{ required: true }]}><Select options={versions.map(v => ({ value: v.version, label: `版本 #${v.version}${v.semantic_version ? `（${v.semantic_version}）` : ''}` }))} onChange={local ? undefined : value => chooseVersion(value)} /></Form.Item>
      {!grantOnly && <>
        <ParameterFields definitions={definitions} />
        <Form.Item name="kind" label="触发方式"><Select options={[{ value: 'manual', label: '仅手动' }, { value: 'once', label: '指定时间一次' }, { value: 'daily', label: '每天' }, { value: 'weekly', label: '每周' }]} /></Form.Item>
        <Form.Item name="timezone" label="时区" rules={[{ required: true }]}><Input placeholder="Asia/Shanghai" /></Form.Item>
        {kind === 'once' && <Form.Item name="start_at" label="执行时间（包含时区偏移）" rules={[{ required: true }]}><Input placeholder="2026-09-14T09:00:00+08:00" /></Form.Item>}
        {['daily', 'weekly'].includes(kind) && <Form.Item name="time" label="执行时刻（所选时区）" rules={[{ required: true }]}><Input type="time" /></Form.Item>}
        {kind === 'weekly' && <Form.Item name="weekdays" label="执行日期" rules={[{ required: true }]}><Checkbox.Group options={weekdays} /></Form.Item>}
        {kind !== 'manual' && <>
          <Form.Item name="misfire" label="错过执行时间"><Select options={[{ value: 'skip', label: '跳过，不补跑' }, { value: 'run_once', label: '宽限期内只补最近一次' }]} /></Form.Item>
          {misfire === 'run_once' && <Form.Item name="grace_seconds" label="补跑宽限（秒）" rules={[{ required: true }]}><InputNumber min={1} max={86400} precision={0} /></Form.Item>}
        </>}
        <Form.Item name="timeout_seconds" label="执行超时（秒，包含准备阶段）" rules={[{ required: true }]}><InputNumber min={1} max={86400} precision={0} /></Form.Item>
        <Form.Item name="requires_desktop" valuePropName="checked"><Checkbox>需要已登录的桌面会话</Checkbox></Form.Item>
        <Form.Item name="requires_browser" valuePropName="checked"><Checkbox>需要可用的浏览器环境</Checkbox></Form.Item>
        <Typography.Paragraph type="secondary">{local ? '本机 Agent 必须保持运行。离线时仅执行已缓存且通过本机校验的脚本。' : '脚本以目标电脑用户的权限执行；设备授权不等于安全沙箱。'} 结果未知时不会自动重跑。</Typography.Paragraph>
      </>}
    </Form>
  </Modal>
}

export default function Tasks() {
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
      setError(local ? '本机 Agent 不可用，请启动客户端后刷新。' : '服务器不可用；可切换到本机任务管理已下载脚本。')
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
      if (serial.current === id) setError(e.response?.status === 404 ? '当前服务或客户端尚不支持任务调度，请升级后重试。' : taskError(e))
    } finally { if (serial.current === id) setLoading(false) }
  }, [local, agentOnline, online, localApi])
  useEffect(() => {
    load()
    const timer = setInterval(load, 5000)
    return () => { invalidateRequests(); clearInterval(timer) }
  }, [load, invalidateRequests])
  const mutate = async (url, body, useLocal = local) => {
    if (inFlight.current) return
    inFlight.current = true; setBusy(true)
    try { await (useLocal ? localApi : api).post(url, body); await load(); return true }
    catch (e) { message.error(taskError(e)); return false }
    finally { inFlight.current = false; setBusy(false) }
  }
  const action = async (task, actionName) => {
    const key = `${source}:${task.id}`
    if (actionName === 'run' && !requestIds.current.has(key)) requestIds.current.set(key, newRequestId())
    const result = await mutate(`${local ? '/local/schedules' : '/api/tasks'}/${task.id}/action`, { action: actionName, ...(actionName === 'run' && { request_id: requestIds.current.get(key) }) })
    if (result) { requestIds.current.delete(key); message.success(actionName === 'run' ? '运行请求已接受，请在执行记录查看结果' : '任务已更新') }
  }
  const disabled = busy || !available || !!error || loadedSource !== source
  const deviceLabel = id => `${devices.find(d => d.id === id)?.name || '设备'}（#${id}）`
  const taskColumns = [
    { title: '任务', dataIndex: 'name', render: (name, row) => <><strong>{name}</strong><div>脚本 #{row.script_id} / 版本 #{row.script_version}</div></> },
    ...(!local ? [{ title: '目标设备', dataIndex: 'device_id', render: deviceLabel }] : []),
    { title: '计划', dataIndex: 'trigger', render: triggerLabel },
    { title: '状态', dataIndex: 'enabled', render: value => <Tag color={value ? 'green' : 'default'}>{value ? '已启用' : '已暂停'}</Tag> },
    { title: '下次执行', dataIndex: 'next_fire_at', render: value => value ? formatServerTime(value) : '—' },
    { title: '操作', key: 'actions', fixed: 'right', width: 230, render: (_, row) => <Space wrap>
      <Popconfirm title="确认运行一次？" description={`将在${local ? '本机' : deviceLabel(row.device_id)}运行脚本 #${row.script_id} 的固定版本 #${row.script_version}，使用已保存参数。`} onConfirm={() => action(row, 'run')} disabled={disabled || !row.enabled}><Button size="small" disabled={disabled || !row.enabled} title={!row.enabled ? '请先核对设备状态并恢复任务' : undefined}>运行一次</Button></Popconfirm>
      <Button size="small" disabled={disabled} onClick={() => action(row, row.enabled ? 'pause' : 'resume')}>{row.enabled ? '暂停' : '恢复'}</Button>
      <Popconfirm title="删除此任务？" description="删除不等于正在运行的进程已停止，请核对执行记录。" onConfirm={() => action(row, 'delete')} disabled={disabled}><Button danger size="small" disabled={disabled}>删除</Button></Popconfirm>
    </Space> },
  ]
  const eventColumns = [
    { title: '任务', key: 'task', render: (_, row) => row.task_name || `任务 #${row.task_id}` },
    { title: '状态', key: 'state', render: (_, row) => <State value={row.state || row.status} /> },
    { title: '计划时间', dataIndex: 'scheduled_for', render: value => value ? formatServerTime(value) : '手动触发' },
    { title: '说明', dataIndex: 'error_msg', render: value => <span style={{ overflowWrap: 'anywhere' }}>{value || '—'}</span> },
    { title: '操作', key: 'actions', render: (_, row) => {
      const runId = local ? row.local_run_id || row.run_id : row.run_id
      const cancellable = activeStates.includes(row.state || row.status) && (!local || runId)
      return <Space wrap>{runId && <Link to={`/runs/${encodeURIComponent(runId)}`}>执行详情</Link>}{cancellable && <Popconfirm title="请求取消此次执行？" description="结果未知时，必须等待设备确认停止，不会立即释放执行槽。" disabled={disabled} onConfirm={() => mutate(local ? `/local/runs/${runId}/cancel` : `/api/tasks/executions/${row.id}/cancel`, {})}><Button size="small" disabled={disabled || (row.state || row.status) === 'cancel_requested'}>取消执行</Button></Popconfirm>}</Space>
    } },
  ]
  const grantColumns = [
    { title: '申请人', key: 'requester', render: (_, row) => row.requester_name || row.requester_display_name || `用户 #${row.requester_id}` },
    { title: '设备', dataIndex: 'device_id', render: value => `#${value}` },
    { title: '脚本版本', key: 'version', render: (_, row) => `脚本 #${row.script_id} / 版本 #${row.script_version}` },
    { title: '状态', dataIndex: 'status', render: value => <State value={value} /> },
    ...(local ? [{ title: '本机确认', key: 'decision', render: (_, row) => <Space wrap>{(row.status === 'pending' ? ['accept', 'reject'] : row.status === 'accepted' ? ['revoke'] : ['rejected', 'revoked'].includes(row.status) ? ['accept'] : []).map(decision => <Popconfirm key={decision} title={decision === 'accept' ? '允许该用户以你的电脑权限运行此脚本版本？' : decision === 'revoke' ? '撤销此授权？' : '拒绝申请？'} description={decision === 'accept' ? '对方可提供执行参数。仅授权你信任的用户和脚本；此操作不是沙箱隔离。' : '正在执行的任务需要等待确认停止。'} disabled={disabled} onConfirm={() => mutate(`/local/device-grants/${row.id}/decision`, { decision }, true)}><Button size="small" danger={decision === 'revoke'} disabled={disabled}>{({ accept: row.status === 'pending' ? '允许' : '重新允许', reject: '拒绝', revoke: '撤销' })[decision]}</Button></Popconfirm>)}</Space> }] : []),
  ]
  return <div>
    <div className="page-heading" style={{ flexWrap: 'wrap', gap: 16 }}><h2>任务调度</h2><Space wrap><Button icon={<ReloadOutlined />} onClick={load} loading={loading}>刷新</Button>{!local && <Button disabled={disabled} onClick={() => setEditor('grant')}>申请设备授权</Button>}<Button type="primary" icon={<PlusOutlined />} disabled={disabled} onClick={() => setEditor('task')}>新建任务</Button></Space></div>
    <Tabs activeKey={source} onChange={value => { if (!busy) { setSource(value); setEditor(null) } }} items={[{ key: 'remote', label: '远程任务', disabled: busy }, { key: 'local', label: '本机任务', disabled: busy }]} />
    {error && <Alert type="error" title={error} showIcon style={{ marginBottom: 16 }} />}
    <Typography.Paragraph type="secondary">{local ? `本机任务保存在此电脑，Agent 退出后不会执行。${device?.id ? ` 本机设备编号：${device.id}，可提供给需要申请授权的用户。` : ' 设备尚未注册，远程授权需要登录并连接服务器。'}` : '先申请设备授权，再由目标电脑使用者在「本机任务 → 设备授权」确认。远程管理员不能替代本机同意。'}</Typography.Paragraph>
    <Tabs items={[
      { key: 'tasks', label: '任务列表', children: <Table rowKey="id" loading={loading} columns={taskColumns} dataSource={loadedSource === source ? tasks : []} scroll={{ x: 900 }} locale={{ emptyText: local ? '还没有本机任务。下载脚本后即可新建定时任务。' : '还没有远程任务。申请设备授权后即可新建。' }} /> },
      { key: 'events', label: '最近执行', children: <><Alert type="info" showIcon title="结果未知不代表失败或停止。核对目标电脑后再处理，避免重复执行。" style={{ marginBottom: 16 }} /><Table rowKey="id" columns={eventColumns} dataSource={loadedSource === source ? events : []} scroll={{ x: 800 }} /></> },
      { key: 'grants', label: '设备授权', children: <Table rowKey="id" columns={grantColumns} dataSource={loadedSource === source ? grants : []} scroll={{ x: 700 }} /> },
    ]} />
    {editor && <TaskEditor local={local} localApi={localApi} devices={devices} grantOnly={editor === 'grant'} onCancel={() => setEditor(null)} onSaved={() => { setEditor(null); load() }} />}
  </div>
}
