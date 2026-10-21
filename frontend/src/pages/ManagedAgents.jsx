import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  Alert, Button, Checkbox, Drawer, Empty, Form, Input, InputNumber, Pagination, Popconfirm, Segmented,
  Select, Skeleton, Space, Switch, Tag, Tooltip, message,
} from 'antd'
import {
  DeleteOutlined, DesktopOutlined, LoadingOutlined, PictureOutlined, ReloadOutlined,
  SearchOutlined, SendOutlined, WarningOutlined,
} from '@ant-design/icons'
import api from '../api/client'
import ManagedParamFields from '../components/ManagedParamFields'
import { parseScriptConfig } from '../utils/groups'
import {
  apiErrorMessage, buildSchedulePayload, buildVisualCron, describeCron, formatSchedule,
  intervalToSeconds, isThumbnailStale, isValidCronExpression, statusPresentation, thumbnailTimestamp,
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

function AgentCard({ agent, updating, deleting, scheduleCount, onToggle, onDispatch, onDelete }) {
  const status = agent.running_run_id
    ? { color: 'processing', text: agent.running_dispatch_type === 'managed_schedule' ? '运行中（定时）' : '运行中（临时）' }
    : statusPresentation(agent.status, agent.enabled)
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
        <div><dt>定时任务</dt><dd>{scheduleCount ? `${scheduleCount} 个已安排` : '暂无'}</dd></div>
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
        <div className="managed-agent-card__primary-actions">
          <Tooltip title={!agent.enabled ? '设备已停用，仍可查看已安排的定时任务' : ''}>
            <Button type="primary" icon={<SendOutlined />} onClick={() => onDispatch(agent)}>
              发布任务
            </Button>
          </Tooltip>
          <Popconfirm
            title={`删除设备“${agent.machine_name}”？`}
            description={agent.status === 'online' ? '设备当前在线，删除后再次连接会重新注册。' : '设备记录和最新缩略图将被删除，历史任务仍保留。'}
            okText="删除设备"
            cancelText="取消"
            okButtonProps={{ danger: true }}
            onConfirm={() => onDelete(agent)}
          >
            <Tooltip title="删除设备">
              <Button danger type="text" icon={<DeleteOutlined />} loading={deleting} aria-label={`删除设备${agent.machine_name}`} />
            </Tooltip>
          </Popconfirm>
        </div>
      </div>
    </article>
  )
}

export default function ManagedAgents({ embedded = false }) {
  const [agents, setAgents] = useState([])
  const [schedules, setSchedules] = useState([])
  const [scripts, setScripts] = useState([])
  const [environments, setEnvironments] = useState([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState('')
  const [updating, setUpdating] = useState({})
  const [deleting, setDeleting] = useState({})
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
  const selectedTaskType = Form.useWatch('task_type', form) || 'manual'
  const selectedScheduleType = Form.useWatch('schedule_type', form) || 'interval'
  const selectedCronMode = Form.useWatch('cron_mode', form) || 'visual'
  const selectedCronPreset = Form.useWatch('cron_preset', form) || 'daily'
  const cronValues = Form.useWatch([], form) || {}
  const cronExpression = selectedCronMode === 'advanced'
    ? cronValues.cron_expression
    : buildVisualCron(cronValues)

  const load = useCallback(async ({ quiet = false } = {}) => {
    if (quiet && listRequest.current) return
    listRequest.current?.abort()
    const controller = new AbortController()
    listRequest.current = controller
    if (!quiet) setLoading(true)
    setLoadError('')
    try {
      const [agentResult, scheduleResult] = await Promise.allSettled([
        api.get('/api/admin/managed-agents', { signal: controller.signal }),
        api.get('/api/admin/managed-schedules', { signal: controller.signal }),
      ])
      if (!controller.signal.aborted && agentResult.status === 'fulfilled') {
        setAgents(Array.isArray(agentResult.value.data) ? agentResult.value.data : [])
      } else if (!controller.signal.aborted && agentResult.status === 'rejected') {
        throw agentResult.reason
      }
      if (!controller.signal.aborted && scheduleResult.status === 'fulfilled') {
        setSchedules(Array.isArray(scheduleResult.value.data) ? scheduleResult.value.data : [])
      }
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

  const schedulesByAgent = useMemo(() => {
    const result = new Map()
    schedules.forEach(schedule => {
      const items = result.get(schedule.agent_id) || []
      items.push(schedule)
      result.set(schedule.agent_id, items)
    })
    return result
  }, [schedules])

  const openDispatch = async agent => {
    setDispatchAgent(agent)
    setScripts([])
    setEnvironments([])
    form.resetFields()
    form.setFieldsValue({
      task_type: 'manual',
      schedule_name: '',
      schedule_type: 'interval',
      interval_value: 1,
      interval_unit: 'hour',
      cron_mode: 'visual',
      cron_preset: 'daily',
      cron_hour: 9,
      cron_minute: 0,
      cron_weekdays: [1],
      cron_monthday: 1,
      cron_expression: '0 9 * * *',
      timezone: 'Asia/Shanghai',
      expires_value: 1,
      expires_unit: 'hour',
      schedule_enabled: true,
      params: {},
    })
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

  const deleteAgent = async agent => {
    setDeleting(current => ({ ...current, [agent.id]: true }))
    try {
      await api.delete(`/api/agents/${agent.id}`)
      setAgents(current => current.filter(item => item.id !== agent.id))
      if (dispatchAgent?.id === agent.id) setDispatchAgent(null)
      message.success(`设备“${agent.machine_name}”已删除`)
    } catch (error) {
      message.error(apiErrorMessage(error, '设备删除失败'))
    } finally {
      setDeleting(current => ({ ...current, [agent.id]: false }))
    }
  }

  const dispatch = async values => {
    const expires = intervalToSeconds(values.expires_value, values.expires_unit)
    if (!expires || expires < 60 || expires > 604800) {
      message.error('任务有效期须在 1 分钟到 7 天之间')
      return
    }
    const isSchedule = values.task_type === 'schedule'
    const isIntervalSchedule = isSchedule && values.schedule_type !== 'cron'
    const interval = isIntervalSchedule ? intervalToSeconds(values.interval_value, values.interval_unit) : null
    if (isIntervalSchedule && (!interval || interval < 60 || interval > 31536000)) {
      message.error('执行间隔须在 1 分钟到 365 天之间')
      return
    }
    const expression = values.cron_mode === 'advanced' ? values.cron_expression : buildVisualCron(values)
    if (isSchedule && values.schedule_type === 'cron' && !isValidCronExpression(expression)) {
      message.error('请输入有效的五段 Cron 表达式')
      return
    }
    setSubmitting(true)
    try {
      if (isSchedule) {
        await api.post('/api/admin/managed-schedules', buildSchedulePayload({
          ...values,
          name: values.schedule_name,
          agent_id: dispatchAgent.id,
          enabled: values.schedule_enabled,
        }))
        message.success('定时任务已创建')
      } else {
        const response = await api.post(`/api/admin/managed-agents/${dispatchAgent.id}/runs`, {
          script_id: values.script_id,
          params: values.params || {},
          environment_id: values.environment_id ?? null,
          expires_in_seconds: expires,
        })
        message.success(`临时任务 #${response.data.id} 已发布`)
      }
      setDispatchAgent(null)
      load({ quiet: true })
    } catch (error) {
      const cronUnsupported = isSchedule && values.schedule_type === 'cron' && [400, 404, 422].includes(error?.response?.status)
      const fallback = cronUnsupported
        ? '当前服务端可能尚未支持 Cron 定时，请升级服务端或改用固定间隔'
        : isSchedule ? '定时任务创建失败' : '临时任务发布失败'
      const errorText = apiErrorMessage(error, fallback)
      message.error(cronUnsupported && errorText !== fallback ? `${errorText}；如服务端版本较旧，请升级或改用固定间隔` : errorText)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="managed-admin-page">
      <div className={embedded ? 'managed-section-heading' : 'page-heading'}>
        <div>
          {embedded ? <h3>设备与临时任务</h3> : <h2>被控设备</h2>}
          <p>查看设备画面与运行状态，向空闲设备下发一次性临时任务</p>
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
                deleting={Boolean(deleting[agent.id])}
                scheduleCount={(schedulesByAgent.get(agent.id) || []).length}
                onToggle={toggleAgent}
                onDispatch={openDispatch}
                onDelete={deleteAgent}
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
        title={`向 ${dispatchAgent?.machine_name || ''} 发布任务`}
        open={Boolean(dispatchAgent)}
        onClose={() => !submitting && setDispatchAgent(null)}
        width={620}
        rootClassName="managed-dispatch-drawer"
        extra={(
          <Button
            type="primary"
            icon={<SendOutlined />}
            loading={submitting}
            disabled={!dispatchAgent?.enabled || (selectedTaskType === 'manual' && Boolean(dispatchAgent?.running_run_id))}
            onClick={() => form.submit()}
          >
            {selectedTaskType === 'schedule' ? '创建定时任务' : '发布临时任务'}
          </Button>
        )}
        destroyOnHidden
      >
        {dispatchAgent?.running_run_id ? (
          <Alert
            className="managed-drawer-alert"
            type="warning"
            showIcon
            title={`设备正在执行${dispatchAgent.running_dispatch_type === 'managed_schedule' ? '定时' : '临时'}任务 #${dispatchAgent.running_run_id}`}
            description="当前任务结束前不能再发布临时任务，但仍可切换到定时任务进行查看或创建。"
          />
        ) : dispatchAgent?.status !== 'online' ? (
          <Alert className="managed-drawer-alert" type="warning" showIcon title="设备当前离线" description="临时任务会保留到有效期结束；设备恢复连接后才能领取。" />
        ) : null}

        <Form form={form} layout="vertical" onFinish={dispatch} requiredMark="optional">
          <Form.Item name="task_type" label="任务类型">
            <Segmented
              block
              options={[
                { label: '临时任务', value: 'manual' },
                { label: '定时任务', value: 'schedule' },
              ]}
            />
          </Form.Item>

          <div className={`managed-schedule-reveal${selectedTaskType === 'schedule' ? ' is-open' : ''}`} aria-hidden={selectedTaskType !== 'schedule'}>
            <div className="managed-schedule-reveal__inner">
              <section className="managed-dispatch-schedules">
                <div className="managed-dispatch-schedules__heading">
                  <div>
                    <h3>当前已安排</h3>
                    <span>{(schedulesByAgent.get(dispatchAgent?.id) || []).length} 个定时任务</span>
                  </div>
                </div>
                {(schedulesByAgent.get(dispatchAgent?.id) || []).length ? (
                  <div className="managed-dispatch-schedules__list">
                    {(schedulesByAgent.get(dispatchAgent?.id) || []).map(schedule => (
                      <div key={schedule.id}>
                        <div><strong>{schedule.name}</strong><span>{formatSchedule(schedule)}</span></div>
                        <small>{schedule.enabled ? `下次 ${formatServerTime(schedule.next_run_at)}` : '已暂停'}</small>
                      </div>
                    ))}
                  </div>
                ) : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="该设备暂无定时任务" />}
              </section>

              <Form.Item name="schedule_name" label="任务名称" rules={selectedTaskType === 'schedule' ? [{ required: true, whitespace: true, message: '请输入任务名称' }] : []}>
                <Input maxLength={200} placeholder="例如：每小时同步库存" />
              </Form.Item>
              <Form.Item name="schedule_type" label="执行方式">
                <Segmented block options={[{ label: '固定间隔', value: 'interval' }, { label: 'Cron', value: 'cron' }]} />
              </Form.Item>

              {selectedScheduleType === 'interval' ? (
                <Form.Item label="执行间隔" required>
                  <Space.Compact block>
                    <Form.Item name="interval_value" noStyle><InputNumber min={1} style={{ width: '70%' }} /></Form.Item>
                    <Form.Item name="interval_unit" noStyle><Select style={{ width: '30%' }} options={durationUnits} /></Form.Item>
                  </Space.Compact>
                </Form.Item>
              ) : (
                <div className="managed-cron-config">
                  <Form.Item name="cron_mode" label="Cron 配置方式">
                    <Segmented block options={[{ label: '可视化点选', value: 'visual' }, { label: '高级表达式', value: 'advanced' }]} />
                  </Form.Item>
                  {selectedCronMode === 'visual' ? (
                    <>
                      <Form.Item name="cron_preset" label="执行周期">
                        <Segmented block options={[{ label: '每小时', value: 'hourly' }, { label: '每天', value: 'daily' }, { label: '每周', value: 'weekly' }, { label: '每月', value: 'monthly' }]} />
                      </Form.Item>
                      <div className="managed-cron-grid">
                        {selectedCronPreset !== 'hourly' && <Form.Item name="cron_hour" label="小时"><Select options={Array.from({ length: 24 }, (_, value) => ({ value, label: `${String(value).padStart(2, '0')} 时` }))} /></Form.Item>}
                        <Form.Item name="cron_minute" label="分钟"><Select options={Array.from({ length: 60 }, (_, value) => ({ value, label: `${String(value).padStart(2, '0')} 分` }))} /></Form.Item>
                        {selectedCronPreset === 'monthly' && <Form.Item name="cron_monthday" label="日期"><Select options={Array.from({ length: 31 }, (_, index) => ({ value: index + 1, label: `${index + 1} 日` }))} /></Form.Item>}
                      </div>
                      {selectedCronPreset === 'weekly' && (
                        <Form.Item name="cron_weekdays" label="星期" rules={[{ required: true, message: '请至少选择一天' }]}>
                          <Checkbox.Group className="managed-weekday-grid" options={['日', '一', '二', '三', '四', '五', '六'].map((label, value) => ({ label: `周${label}`, value }))} />
                        </Form.Item>
                      )}
                    </>
                  ) : (
                    <Form.Item name="cron_expression" label="Cron 表达式" extra="分　时　日　月　星期" rules={[{ validator: (_, value) => isValidCronExpression(value) ? Promise.resolve() : Promise.reject(new Error('请输入有效的五段表达式')) }]}>
                      <Input className="managed-cron-input" placeholder="0 9 * * 1-5" spellCheck={false} />
                    </Form.Item>
                  )}
                  <Form.Item name="timezone" label="时区"><Select showSearch options={[{ value: 'Asia/Shanghai', label: 'Asia/Shanghai（北京时间）' }, { value: 'UTC', label: 'UTC' }]} /></Form.Item>
                  <div className={`managed-cron-summary${isValidCronExpression(cronExpression) ? '' : ' is-invalid'}`} aria-live="polite">
                    <span>执行摘要</span><strong>{describeCron(cronExpression)}</strong>
                  </div>
                </div>
              )}
              <Form.Item name="schedule_enabled" label="创建后立即启用" valuePropName="checked">
                <Switch />
              </Form.Item>
            </div>
          </div>

          <fieldset className="managed-task-fields" disabled={!dispatchAgent?.enabled || (selectedTaskType === 'manual' && Boolean(dispatchAgent?.running_run_id))}>
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
          </fieldset>
        </Form>
      </Drawer>
    </div>
  )
}
