import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Alert, Button, Drawer, Empty, Form, Input, InputNumber, Popconfirm, Select, Space,
  Switch, Table, Tag, Tooltip, message,
} from 'antd'
import {
  DeleteOutlined, EditOutlined, PauseCircleOutlined, PlayCircleOutlined,
  PlusOutlined, ReloadOutlined, ThunderboltOutlined,
} from '@ant-design/icons'
import api from '../api/client'
import ManagedParamFields from '../components/ManagedParamFields'
import { parseScriptConfig } from '../utils/groups'
import {
  INTERVAL_UNITS, apiErrorMessage, buildSchedulePayload, formatInterval,
  scheduleFormValues, statusPresentation,
} from '../utils/managed'
import { formatServerTime } from '../utils/dateTime'

function parameterDefaults(params) {
  return params.reduce((result, param) => {
    if (param.default !== undefined) result[param.key] = param.default
    return result
  }, {})
}

export default function ManagedSchedules({ embedded = false }) {
  const [schedules, setSchedules] = useState([])
  const [agents, setAgents] = useState([])
  const [scripts, setScripts] = useState([])
  const [availableScripts, setAvailableScripts] = useState([])
  const [environments, setEnvironments] = useState([])
  const [scriptDetails, setScriptDetails] = useState({})
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState('')
  const [editing, setEditing] = useState(null)
  const [submitting, setSubmitting] = useState(false)
  const [actionLoading, setActionLoading] = useState({})
  const [scriptLoading, setScriptLoading] = useState(false)
  const [form] = Form.useForm()
  const selectedAgentId = Form.useWatch('agent_id', form)
  const selectedScriptId = Form.useWatch('script_id', form)

  const load = useCallback(async () => {
    setLoading(true)
    setLoadError('')
    const [scheduleResult, agentResult, scriptResult, envResult] = await Promise.allSettled([
      api.get('/api/admin/managed-schedules'),
      api.get('/api/admin/managed-agents'),
      api.get('/api/scripts/manageable'),
      Promise.resolve({ data: [] }),
    ])
    if (scheduleResult.status === 'fulfilled') setSchedules(scheduleResult.value.data || [])
    else setLoadError(apiErrorMessage(scheduleResult.reason, '托管计划加载失败'))
    if (agentResult.status === 'fulfilled') setAgents(agentResult.value.data || [])
    if (scriptResult.status === 'fulfilled') setScripts(scriptResult.value.data || [])
    if (envResult.status === 'fulfilled') setEnvironments(envResult.value.data || [])
    setLoading(false)
  }, [])

  useEffect(() => { load() }, [load])

  const loadScriptDetail = useCallback(async (scriptId, applyDefaults = false) => {
    if (!scriptId) return
    if (scriptDetails[scriptId]) {
      if (applyDefaults) {
        const defs = parseScriptConfig(scriptDetails[scriptId].config_json).params || []
        form.setFieldValue('params', parameterDefaults(defs))
      }
      return
    }
    setScriptLoading(true)
    try {
      const response = await api.get(`/api/scripts/${scriptId}`)
      setScriptDetails(current => ({ ...current, [scriptId]: response.data }))
      if (applyDefaults) {
        const defs = parseScriptConfig(response.data?.config_json).params || []
        form.setFieldValue('params', parameterDefaults(defs))
      }
    } catch (error) {
      message.error(apiErrorMessage(error, '脚本参数加载失败'))
    } finally {
      setScriptLoading(false)
    }
  }, [form, scriptDetails])

  const loadAgentOptions = useCallback(async agentId => {
    setAvailableScripts([])
    setEnvironments([])
    form.setFieldValue('environment_id', undefined)
    if (!agentId) return
    try {
      const response = await api.get(`/api/admin/managed-agents/${agentId}/options`)
      setAvailableScripts(response.data?.scripts || [])
      setEnvironments(response.data?.environments || [])
    } catch (error) {
      message.error(apiErrorMessage(error, '无法读取该设备可用的脚本和环境'))
    }
  }, [form])

  const scriptParams = useMemo(() => {
    return parseScriptConfig(scriptDetails[selectedScriptId]?.config_json).params || []
  }, [scriptDetails, selectedScriptId])

  const agentsById = useMemo(() => new Map(agents.map(agent => [agent.id, agent])), [agents])
  const scriptsById = useMemo(() => new Map(scripts.map(script => [script.id, script])), [scripts])

  const openCreate = () => {
    setEditing({ id: null })
    setAvailableScripts([])
    setEnvironments([])
    form.resetFields()
    form.setFieldsValue(scheduleFormValues(null))
  }

  const openEdit = schedule => {
    setEditing(schedule)
    form.resetFields()
    form.setFieldsValue(scheduleFormValues(schedule))
    loadAgentOptions(schedule.agent_id).then(() => {
      form.setFieldValue('environment_id', schedule.environment_id ?? undefined)
    })
    loadScriptDetail(schedule.script_id, false)
  }

  const save = async values => {
    const payload = buildSchedulePayload(values)
    if (!payload.interval_seconds || payload.interval_seconds > 31536000) {
      message.error('执行间隔须在 1 分钟到 365 天之间')
      return
    }
    if (!payload.expires_after_seconds || payload.expires_after_seconds > 604800) {
      message.error('单次任务有效期须在 1 分钟到 7 天之间')
      return
    }
    setSubmitting(true)
    try {
      if (editing.id) {
        await api.patch(`/api/admin/managed-schedules/${editing.id}`, payload)
        message.success('托管计划已更新')
      } else {
        await api.post('/api/admin/managed-schedules', payload)
        message.success('托管计划已创建')
      }
      setEditing(null)
      load()
    } catch (error) {
      message.error(apiErrorMessage(error, editing.id ? '计划更新失败' : '计划创建失败'))
    } finally {
      setSubmitting(false)
    }
  }

  const runAction = async (schedule, action) => {
    const actionKey = `${schedule.id}:${action}`
    setActionLoading(current => ({ ...current, [actionKey]: true }))
    try {
      await api.post(`/api/admin/managed-schedules/${schedule.id}/${action}`)
      const text = action === 'run-now' ? '任务已提交' : action === 'enable' ? '计划已启用' : '计划已暂停'
      message.success(text)
      load()
    } catch (error) {
      message.error(apiErrorMessage(error, '操作失败'))
    } finally {
      setActionLoading(current => ({ ...current, [actionKey]: false }))
    }
  }

  const remove = async schedule => {
    const actionKey = `${schedule.id}:delete`
    setActionLoading(current => ({ ...current, [actionKey]: true }))
    try {
      await api.delete(`/api/admin/managed-schedules/${schedule.id}`)
      message.success('托管计划已删除')
      load()
    } catch (error) {
      message.error(apiErrorMessage(error, '删除失败'))
    } finally {
      setActionLoading(current => ({ ...current, [actionKey]: false }))
    }
  }

  const columns = [
    {
      title: '计划', dataIndex: 'name', key: 'name', minWidth: 170,
      render: (name, schedule) => (
        <div className="managed-plan-cell">
          <strong>{name}</strong>
          <small>#{schedule.id}</small>
        </div>
      ),
    },
    {
      title: '设备', dataIndex: 'agent_id', key: 'agent', minWidth: 150,
      render: id => {
        const agent = agentsById.get(id)
        const state = statusPresentation(agent?.status, agent?.enabled)
        return <Space size={6}><span>{agent?.machine_name || `设备 #${id}`}</span><Tag color={state.color}>{state.text}</Tag></Space>
      },
    },
    { title: '脚本', dataIndex: 'script_id', key: 'script', minWidth: 140, render: id => scriptsById.get(id)?.name || `脚本 #${id}` },
    { title: '频率', dataIndex: 'interval_seconds', key: 'interval', width: 110, render: formatInterval },
    { title: '下次运行', dataIndex: 'next_run_at', key: 'next', width: 170, render: value => value ? formatServerTime(value) : '-' },
    { title: '上次运行', dataIndex: 'last_run_at', key: 'last', width: 170, render: value => value ? formatServerTime(value) : '尚未运行' },
    { title: '状态', dataIndex: 'enabled', key: 'enabled', width: 80, render: enabled => <Tag color={enabled ? 'green' : 'default'}>{enabled ? '已启用' : '已暂停'}</Tag> },
    {
      title: '操作', key: 'actions', width: 222, fixed: 'right',
      render: (_, schedule) => (
        <Space size={2}>
          <Tooltip title="编辑">
            <Button type="text" icon={<EditOutlined />} onClick={() => openEdit(schedule)} aria-label={`编辑${schedule.name}`} />
          </Tooltip>
          <Tooltip title={schedule.enabled ? '暂停' : '启用'}>
            <Button
              type="text"
              icon={schedule.enabled ? <PauseCircleOutlined /> : <PlayCircleOutlined />}
              loading={actionLoading[`${schedule.id}:${schedule.enabled ? 'disable' : 'enable'}`]}
              onClick={() => runAction(schedule, schedule.enabled ? 'disable' : 'enable')}
              aria-label={`${schedule.enabled ? '暂停' : '启用'}${schedule.name}`}
            />
          </Tooltip>
          <Button type="link" icon={<ThunderboltOutlined />} loading={actionLoading[`${schedule.id}:run-now`]} onClick={() => runAction(schedule, 'run-now')}>立即运行</Button>
          <Popconfirm title="删除这个托管计划？" description="已创建的历史任务不会被删除。" okText="删除" cancelText="取消" onConfirm={() => remove(schedule)}>
            <Button type="text" danger icon={<DeleteOutlined />} loading={actionLoading[`${schedule.id}:delete`]} aria-label={`删除${schedule.name}`} />
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <div className="managed-admin-page">
      <div className={embedded ? 'managed-section-heading' : 'page-heading'}>
        <div>
          {embedded ? <h3>定时任务</h3> : <h2>托管计划</h2>}
          <p>按固定分钟、小时或天间隔，向指定被控设备自动下发任务</p>
        </div>
        <Space>
          <Button icon={<ReloadOutlined />} onClick={load} loading={loading}>刷新</Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>新建定时任务</Button>
        </Space>
      </div>

      {loadError && <Alert className="managed-page-alert" type="error" showIcon title={loadError} action={<Button size="small" onClick={load}>重试</Button>} />}

      <Table
        dataSource={schedules}
        columns={columns}
        rowKey="id"
        loading={loading}
        scroll={{ x: 1220 }}
        pagination={{ pageSize: 20, hideOnSinglePage: true }}
        locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="还没有托管计划" /> }}
      />

      <Drawer
        title={editing?.id ? '编辑托管计划' : '新建托管计划'}
        open={Boolean(editing)}
        onClose={() => !submitting && setEditing(null)}
        width={540}
        extra={<Button type="primary" loading={submitting} onClick={() => form.submit()}>{editing?.id ? '保存计划' : '创建计划'}</Button>}
        destroyOnHidden
      >
        <Form form={form} layout="vertical" onFinish={save} requiredMark="optional">
          <Form.Item name="name" label="计划名称" rules={[{ required: true, whitespace: true, message: '请输入计划名称' }]}>
            <Input maxLength={200} showCount placeholder="例如：每小时同步库存" />
          </Form.Item>
          <Form.Item name="agent_id" label="被控设备" rules={[{ required: true, message: '请选择被控设备' }]}>
            <Select
              showSearch
              optionFilterProp="label"
              placeholder="选择任务运行设备"
              onChange={value => {
                form.setFieldsValue({ script_id: undefined, params: {}, environment_id: undefined })
                loadAgentOptions(value)
              }}
              options={agents.map(agent => ({
                label: `${agent.machine_name}${agent.enabled ? '' : '（已停用）'}`,
                value: agent.id,
                disabled: !agent.enabled,
              }))}
            />
          </Form.Item>
          <Form.Item name="script_id" label="脚本" rules={[{ required: true, message: '请选择脚本' }]}>
            <Select
              showSearch
              optionFilterProp="label"
              placeholder="选择执行脚本"
              onChange={value => { form.setFieldValue('params', {}); loadScriptDetail(value, true) }}
              disabled={!selectedAgentId}
              options={availableScripts.map(script => ({ label: script.name, value: script.id, disabled: script.status !== 'active' }))}
            />
          </Form.Item>
          <Form.Item name="environment_id" label="执行环境" extra="留空时使用被控设备默认配置。">
            <Select allowClear placeholder="默认环境" options={environments.map(environment => ({ label: environment.name, value: environment.id }))} />
          </Form.Item>

          <div className="managed-form-section">
            <h3>脚本参数</h3>
            <ManagedParamFields params={scriptParams} disabled={!selectedScriptId || scriptLoading} />
          </div>

          <Form.Item label="固定执行间隔" required>
            <Space.Compact block>
              <Form.Item name="interval_value" noStyle rules={[{ required: true, message: '请输入间隔' }]}>
                <InputNumber min={1} style={{ width: '70%' }} />
              </Form.Item>
              <Form.Item name="interval_unit" noStyle>
                <Select style={{ width: '30%' }} options={INTERVAL_UNITS.map(unit => ({ label: unit.label, value: unit.value }))} />
              </Form.Item>
            </Space.Compact>
          </Form.Item>
          <Form.Item label="单次任务有效期" required extra="设备离线超过此时间后，该次任务不再执行。">
            <Space.Compact block>
              <Form.Item name="expires_value" noStyle rules={[{ required: true, message: '请输入有效期' }]}>
                <InputNumber min={1} style={{ width: '70%' }} />
              </Form.Item>
              <Form.Item name="expires_unit" noStyle>
                <Select style={{ width: '30%' }} options={INTERVAL_UNITS.map(unit => ({ label: unit.label, value: unit.value }))} />
              </Form.Item>
            </Space.Compact>
          </Form.Item>
          <Form.Item name="enabled" label="创建后启用" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Form>
      </Drawer>
    </div>
  )
}
