import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Alert, Button, Drawer, Empty, Form, InputNumber, Select, Space, Switch, Table, Tag,
  Typography, message,
} from 'antd'
import { CloudServerOutlined, ReloadOutlined, SendOutlined } from '@ant-design/icons'
import api from '../api/client'
import ManagedParamFields from '../components/ManagedParamFields'
import { parseScriptConfig } from '../utils/groups'
import { apiErrorMessage, intervalToSeconds, statusPresentation } from '../utils/managed'
import { formatServerTime } from '../utils/dateTime'

const durationUnits = [
  { value: 'minute', label: '分钟' },
  { value: 'hour', label: '小时' },
  { value: 'day', label: '天' },
]

function parameterDefaults(params) {
  return params.reduce((result, param) => {
    if (param.default !== undefined) result[param.key] = param.default
    return result
  }, {})
}

export default function ManagedAgents() {
  const [agents, setAgents] = useState([])
  const [scripts, setScripts] = useState([])
  const [environments, setEnvironments] = useState([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState('')
  const [updating, setUpdating] = useState({})
  const [dispatchAgent, setDispatchAgent] = useState(null)
  const [scriptDetails, setScriptDetails] = useState({})
  const [scriptLoading, setScriptLoading] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [form] = Form.useForm()
  const selectedScriptId = Form.useWatch('script_id', form)

  const load = useCallback(async () => {
    setLoading(true)
    setLoadError('')
    try {
      const response = await api.get('/api/admin/managed-agents')
      setAgents(response.data || [])
    } catch (error) {
      setLoadError(apiErrorMessage(error, '被控设备加载失败'))
    }
    setLoading(false)
  }, [])

  useEffect(() => { load() }, [load])

  const loadScriptDetail = useCallback(async (scriptId) => {
    if (!scriptId || scriptDetails[scriptId]) return
    setScriptLoading(true)
    try {
      const response = await api.get(`/api/scripts/${scriptId}`)
      setScriptDetails(current => ({ ...current, [scriptId]: response.data }))
      const params = parseScriptConfig(response.data?.config_json).params || []
      form.setFieldValue('params', parameterDefaults(params))
    } catch (error) {
      message.error(apiErrorMessage(error, '脚本参数加载失败'))
    } finally {
      setScriptLoading(false)
    }
  }, [form, scriptDetails])

  const scriptParams = useMemo(() => {
    const detail = scriptDetails[selectedScriptId]
    return parseScriptConfig(detail?.config_json).params || []
  }, [scriptDetails, selectedScriptId])

  const openDispatch = async agent => {
    setDispatchAgent(agent)
    setScripts([])
    setEnvironments([])
    form.resetFields()
    form.setFieldsValue({ expires_value: 1, expires_unit: 'hour', params: {} })
    setScriptLoading(true)
    try {
      const response = await api.get(`/api/admin/managed-agents/${agent.id}/options`)
      setScripts(response.data?.scripts || [])
      setEnvironments(response.data?.environments || [])
    } catch (error) {
      message.error(apiErrorMessage(error, '无法读取该设备可用的脚本和环境'))
    } finally {
      setScriptLoading(false)
    }
  }

  const toggleAgent = async agent => {
    setUpdating(current => ({ ...current, [agent.id]: true }))
    try {
      const response = await api.patch(`/api/admin/managed-agents/${agent.id}`, { enabled: !agent.enabled })
      setAgents(current => current.map(item => item.id === agent.id ? response.data : item))
      message.success(response.data.enabled ? '设备已启用' : '设备已停用')
    } catch (error) {
      message.error(apiErrorMessage(error, '设备状态更新失败'))
    } finally {
      setUpdating(current => ({ ...current, [agent.id]: false }))
    }
  }

  const dispatch = async values => {
    const expires = intervalToSeconds(values.expires_value, values.expires_unit)
    if (!expires || expires < 60 || expires > 604800) {
      message.error('有效期须在 1 分钟到 7 天之间')
      return
    }
    setSubmitting(true)
    try {
      const response = await api.post(`/api/admin/managed-agents/${dispatchAgent.id}/runs`, {
        script_id: values.script_id,
        params: values.params || {},
        environment_id: values.environment_id ?? null,
        expires_in_seconds: expires,
      })
      message.success(`任务 #${response.data.id} 已定向下发`)
      setDispatchAgent(null)
    } catch (error) {
      message.error(apiErrorMessage(error, '任务下发失败'))
    } finally {
      setSubmitting(false)
    }
  }

  const columns = [
    {
      title: '设备', key: 'device', minWidth: 190,
      render: (_, agent) => (
        <div className="managed-device-cell">
          <span className={`managed-device-icon ${agent.status === 'online' && agent.enabled ? 'is-online' : ''}`}>
            <CloudServerOutlined />
          </span>
          <span>
            <strong>{agent.machine_name}</strong>
            <small>{agent.machine_ip || '未上报 IP'}</small>
          </span>
        </div>
      ),
    },
    {
      title: '设备标识', dataIndex: 'device_uid', key: 'uid', minWidth: 180,
      render: value => <Typography.Text copyable={{ text: value }} ellipsis className="managed-device-uid">{value}</Typography.Text>,
    },
    {
      title: '状态', key: 'status', width: 90,
      render: (_, agent) => { const view = statusPresentation(agent.status, agent.enabled); return <Tag color={view.color}>{view.text}</Tag> },
    },
    { title: 'Agent 版本', dataIndex: 'agent_version', key: 'version', width: 110, render: value => value || '-' },
    { title: '最近心跳', dataIndex: 'last_heartbeat', key: 'heartbeat', width: 170, render: value => value ? formatServerTime(value) : '从未连接' },
    {
      title: '启用', key: 'enabled', width: 80,
      render: (_, agent) => <Switch checked={agent.enabled} loading={updating[agent.id]} onChange={() => toggleAgent(agent)} aria-label={`${agent.machine_name}启用状态`} />,
    },
    {
      title: '操作', key: 'action', width: 120,
      render: (_, agent) => (
        <Button type="link" icon={<SendOutlined />} disabled={!agent.enabled} onClick={() => openDispatch(agent)}>
          下发任务
        </Button>
      ),
    },
  ]

  return (
    <div className="managed-admin-page">
      <div className="page-heading">
        <div>
          <h2>被控设备</h2>
          <p>查看托管 Agent 状态，并将一次性任务定向下发到指定设备</p>
        </div>
        <Button icon={<ReloadOutlined />} onClick={load} loading={loading}>刷新</Button>
      </div>

      {loadError && <Alert className="managed-page-alert" type="error" showIcon title={loadError} action={<Button size="small" onClick={load}>重试</Button>} />}

      <Table
        dataSource={agents}
        columns={columns}
        rowKey="id"
        loading={loading}
        scroll={{ x: 980 }}
        pagination={{ pageSize: 20, hideOnSinglePage: true }}
        locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="还没有托管设备连接到服务器" /> }}
      />

      <Drawer
        title={`向 ${dispatchAgent?.machine_name || ''} 下发任务`}
        open={Boolean(dispatchAgent)}
        onClose={() => !submitting && setDispatchAgent(null)}
        width={520}
        extra={<Button type="primary" icon={<SendOutlined />} loading={submitting} onClick={() => form.submit()}>下发任务</Button>}
        destroyOnHidden
      >
        {dispatchAgent?.status !== 'online' && (
          <Alert className="managed-drawer-alert" type="warning" showIcon title="设备当前离线" description="任务会保留到有效期结束；设备恢复连接后才能领取。" />
        )}
        <Form form={form} layout="vertical" onFinish={dispatch} requiredMark="optional">
          <Form.Item name="script_id" label="脚本" rules={[{ required: true, message: '请选择脚本' }]}>
            <Select
              showSearch
              optionFilterProp="label"
              placeholder="选择要在此设备运行的脚本"
              loading={scriptLoading}
              onChange={value => { form.setFieldValue('params', {}); loadScriptDetail(value) }}
              options={scripts.map(script => ({ label: script.name, value: script.id, disabled: script.status !== 'active' }))}
            />
          </Form.Item>

          <Form.Item name="environment_id" label="执行环境" extra="留空时使用被控设备的默认运行配置。">
            <Select allowClear placeholder="默认环境" options={environments.map(environment => ({
              label: `${environment.name}${environment.is_default ? '（默认）' : ''}`,
              value: environment.id,
            }))} />
          </Form.Item>

          <div className="managed-form-section">
            <h3>脚本参数</h3>
            <ManagedParamFields params={scriptParams} disabled={!selectedScriptId || scriptLoading} />
          </div>

          <Form.Item label="任务有效期" required>
            <Space.Compact block>
              <Form.Item name="expires_value" noStyle rules={[{ required: true, message: '请输入有效期' }]}>
                <InputNumber min={1} max={10080} style={{ width: '70%' }} />
              </Form.Item>
              <Form.Item name="expires_unit" noStyle>
                <Select style={{ width: '30%' }} options={durationUnits} />
              </Form.Item>
            </Space.Compact>
          </Form.Item>
        </Form>
      </Drawer>
    </div>
  )
}
