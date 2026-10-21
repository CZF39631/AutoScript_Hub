import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  Alert, Button, Drawer, Empty, Form, Input, InputNumber, Pagination, Select, Skeleton, Space,
  Switch, Tag, message,
} from 'antd'
import {
  DesktopOutlined, LoadingOutlined, PictureOutlined, ReloadOutlined, SearchOutlined,
  SendOutlined, WarningOutlined,
} from '@ant-design/icons'
import api from '../api/client'
import ManagedParamFields from '../components/ManagedParamFields'
import { parseScriptConfig } from '../utils/groups'
import {
  apiErrorMessage, intervalToSeconds, isThumbnailStale, statusPresentation,
  thumbnailTimestamp,
} from '../utils/managed'
import { formatServerTime } from '../utils/dateTime'

const AGENTS_PER_PAGE = 24

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

function ThumbnailScreen({ agent }) {
  const timestamp = thumbnailTimestamp(agent)
  const [attempt, setAttempt] = useState(0)
  const [image, setImage] = useState({ status: timestamp ? 'loading' : 'empty', url: '' })
  const stale = isThumbnailStale(timestamp)

  useEffect(() => {
    if (!timestamp) {
      setImage({ status: 'empty', url: '' })
      return undefined
    }

    const controller = new AbortController()
    let objectUrl = ''
    setImage({ status: 'loading', url: '' })

    api.get(`/api/admin/managed-agents/${agent.id}/thumbnail`, {
      responseType: 'blob',
      signal: controller.signal,
    }).then(response => {
      if (controller.signal.aborted) return
      objectUrl = URL.createObjectURL(response.data)
      setImage({ status: 'ready', url: objectUrl })
    }).catch(error => {
      if (controller.signal.aborted || error?.code === 'ERR_CANCELED') return
      setImage({ status: error?.response?.status === 404 ? 'empty' : 'error', url: '' })
    })

    return () => {
      controller.abort()
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [agent.id, attempt, timestamp])

  return (
    <div className="managed-monitor" aria-busy={image.status === 'loading'}>
      <div className="managed-monitor__screen">
        {image.status === 'ready' && (
          <img src={image.url} alt={`${agent.machine_name} 最近上传的屏幕缩略图`} />
        )}
        {image.status === 'loading' && (
          <div className="managed-thumbnail-state">
            <LoadingOutlined spin />
            <span>正在读取画面</span>
          </div>
        )}
        {image.status === 'empty' && (
          <div className="managed-thumbnail-state">
            <PictureOutlined />
            <span>暂无可用画面</span>
          </div>
        )}
        {image.status === 'error' && (
          <div className="managed-thumbnail-state managed-thumbnail-state--error" role="alert">
            <WarningOutlined />
            <span>画面读取失败</span>
            <Button size="small" icon={<ReloadOutlined />} onClick={() => setAttempt(value => value + 1)}>重试</Button>
          </div>
        )}
        {image.status === 'ready' && stale && (
          <span className="managed-thumbnail-age"><WarningOutlined /> 画面较旧</span>
        )}
      </div>
      <div className="managed-monitor__chin"><span /></div>
      <div className="managed-monitor__stand" aria-hidden="true" />
    </div>
  )
}

function AgentCard({ agent, updating, onToggle, onDispatch }) {
  const status = statusPresentation(agent.status, agent.enabled)
  const updatedAt = thumbnailTimestamp(agent)

  return (
    <article className={`managed-agent-card${agent.enabled ? '' : ' is-disabled'}`}>
      <div className="managed-agent-card__header">
        <div className="managed-agent-card__identity">
          <span className="managed-agent-card__device"><DesktopOutlined /></span>
          <div>
            <h3 title={agent.machine_name}>{agent.machine_name}</h3>
            <span title={agent.machine_ip || ''}>{agent.machine_ip || '未上报 IP'}</span>
          </div>
        </div>
        <Tag color={status.color}>{status.text}</Tag>
      </div>

      <ThumbnailScreen agent={agent} />

      <dl className="managed-agent-card__details">
        <div><dt>Agent 版本</dt><dd>{agent.agent_version || '-'}</dd></div>
        <div><dt>最近心跳</dt><dd>{agent.last_heartbeat ? formatServerTime(agent.last_heartbeat) : '从未连接'}</dd></div>
        <div><dt>画面更新时间</dt><dd>{updatedAt ? formatServerTime(updatedAt) : '暂无画面'}</dd></div>
      </dl>

      <div className="managed-agent-card__actions">
        <div className="managed-agent-toggle">
          <span>允许接收任务</span>
          <Switch
            checked={agent.enabled}
            loading={updating}
            onChange={() => onToggle(agent)}
            aria-label={`${agent.machine_name}启用状态`}
          />
        </div>
        <Button
          type="primary"
          icon={<SendOutlined />}
          disabled={!agent.enabled}
          onClick={() => onDispatch(agent)}
        >
          下发任务
        </Button>
      </div>
    </article>
  )
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
  const [query, setQuery] = useState('')
  const [statusFilter, setStatusFilter] = useState('all')
  const [page, setPage] = useState(1)
  const listRequest = useRef(null)
  const [form] = Form.useForm()
  const selectedScriptId = Form.useWatch('script_id', form)

  const load = useCallback(async ({ quiet = false } = {}) => {
    if (quiet && listRequest.current) return
    listRequest.current?.abort()
    const controller = new AbortController()
    listRequest.current = controller
    if (!quiet) setLoading(true)
    setLoadError('')
    try {
      const response = await api.get('/api/admin/managed-agents', { signal: controller.signal })
      if (!controller.signal.aborted) setAgents(Array.isArray(response.data) ? response.data : [])
    } catch (error) {
      if (!controller.signal.aborted && error?.code !== 'ERR_CANCELED') {
        setLoadError(apiErrorMessage(error, '被控设备加载失败'))
      }
    } finally {
      if (listRequest.current === controller) {
        if (!quiet) setLoading(false)
        listRequest.current = null
      }
    }
  }, [])

  useEffect(() => {
    load()
    const timer = setInterval(() => load({ quiet: true }), 60_000)
    return () => {
      clearInterval(timer)
      listRequest.current?.abort()
    }
  }, [load])

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

  const filteredAgents = useMemo(() => {
    const keyword = query.trim().toLocaleLowerCase()
    return agents.filter(agent => {
      const matchesKeyword = !keyword || [agent.machine_name, agent.machine_ip, agent.agent_version]
        .some(value => String(value || '').toLocaleLowerCase().includes(keyword))
      const matchesStatus = statusFilter === 'all'
        || (statusFilter === 'disabled' ? !agent.enabled : agent.enabled && agent.status === statusFilter)
      return matchesKeyword && matchesStatus
    })
  }, [agents, query, statusFilter])

  const pageAgents = useMemo(() => {
    const start = (page - 1) * AGENTS_PER_PAGE
    return filteredAgents.slice(start, start + AGENTS_PER_PAGE)
  }, [filteredAgents, page])

  useEffect(() => {
    const lastPage = Math.max(1, Math.ceil(filteredAgents.length / AGENTS_PER_PAGE))
    if (page > lastPage) setPage(lastPage)
  }, [filteredAgents.length, page])

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
      setAgents(current => current.map(item => item.id === agent.id ? { ...item, ...response.data } : item))
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

  return (
    <div className="managed-admin-page">
      <div className="page-heading">
        <div>
          <h2>被控设备</h2>
          <p>查看设备最近上传的静态缩略图与连接状态，并定向下发一次性任务</p>
        </div>
        <Button icon={<ReloadOutlined />} onClick={() => load()} loading={loading}>刷新</Button>
      </div>

      {loadError && (
        <Alert
          className="managed-page-alert"
          type={agents.length ? 'warning' : 'error'}
          showIcon
          title={agents.length ? '自动刷新失败，当前显示上次结果' : loadError}
          description={agents.length ? loadError : undefined}
          action={<Button size="small" onClick={() => load()}>重试</Button>}
        />
      )}

      {agents.length > 0 && (
        <div className="managed-agent-toolbar">
          <Input
            allowClear
            prefix={<SearchOutlined />}
            placeholder="搜索设备名、IP 或版本"
            value={query}
            onChange={event => { setQuery(event.target.value); setPage(1) }}
          />
          <Select
            aria-label="设备状态筛选"
            value={statusFilter}
            onChange={value => { setStatusFilter(value); setPage(1) }}
            options={[
              { value: 'all', label: '全部状态' },
              { value: 'online', label: '在线' },
              { value: 'offline', label: '离线' },
              { value: 'disabled', label: '已停用' },
            ]}
          />
          <span className="managed-agent-count">{filteredAgents.length} 台设备</span>
        </div>
      )}

      {loading && !agents.length ? (
        <div className="managed-agent-grid" aria-label="正在加载被控设备">
          {[0, 1, 2, 3].map(item => (
            <div className="managed-agent-card managed-agent-card--loading" key={item}>
              <Skeleton active paragraph={{ rows: 5 }} />
            </div>
          ))}
        </div>
      ) : pageAgents.length ? (
        <>
          <div className="managed-agent-grid">
            {pageAgents.map(agent => (
              <AgentCard
                key={agent.id}
                agent={agent}
                updating={Boolean(updating[agent.id])}
                onToggle={toggleAgent}
                onDispatch={openDispatch}
              />
            ))}
          </div>
          {filteredAgents.length > AGENTS_PER_PAGE && (
            <Pagination
              className="managed-agent-pagination"
              current={page}
              pageSize={AGENTS_PER_PAGE}
              total={filteredAgents.length}
              showSizeChanger={false}
              showLessItems
              onChange={setPage}
            />
          )}
        </>
      ) : agents.length ? (
        <div className="managed-agent-empty managed-agent-empty--compact">
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="没有符合筛选条件的设备" />
        </div>
      ) : !loadError ? (
        <div className="managed-agent-empty">
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="还没有托管设备连接到服务器" />
        </div>
      ) : null}

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
