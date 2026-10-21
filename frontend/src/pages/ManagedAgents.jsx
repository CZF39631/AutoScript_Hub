import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  Alert, Button, Checkbox, Drawer, Empty, Form, Input, InputNumber, Modal, Pagination, Popconfirm,
  Segmented, Select, Skeleton, Space, Switch, Tag, Tooltip, message,
} from 'antd'
import {
  DeleteOutlined, DesktopOutlined, EditOutlined, EyeOutlined, LoadingOutlined,
  PauseCircleOutlined, PictureOutlined, PlayCircleOutlined, ReloadOutlined, SafetyCertificateOutlined,
  SearchOutlined, SendOutlined, ThunderboltOutlined, WarningOutlined, ZoomInOutlined,
} from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import api from '../api/client'
import { loadManagedThumbnail } from '../api/managedThumbnails'
import ManagedParamFields from '../components/ManagedParamFields'
import { parseScriptConfig } from '../utils/groups'
import {
  agentImpactCounts, apiErrorMessage, buildSchedulePayload, buildVisualCron,
  canConfirmAgentImpact, describeCron, dispatchResourceState, formatSchedule, intervalToSeconds,
  isThumbnailStale, isValidCronExpression, MANAGED_FIRST_CONNECTION_GUIDE,
  scheduleFormValues, scheduleStatusCounts, shortMonthSkipDay, statusPresentation, thumbnailTimestamp,
} from '../utils/managed'
import { formatServerTime } from '../utils/dateTime'
import usePageFocused from '../hooks/usePageFocused'
import { refreshDelay } from '../utils/runHistory'

const AGENTS_PER_PAGE = 24

const durationUnits = [
  { value: 'minute', label: '分钟' },
  { value: 'hour', label: '小时' },
  { value: 'day', label: '天' },
]

const runStatusLabels = {
  pending: '等待中',
  running: '执行中',
  success: '成功',
  failed: '失败',
  cancelled: '已取消',
  expired: '已过期',
}

function parameterDefaults(params) {
  return params.reduce((result, param) => {
    if (param.default !== undefined) result[param.key] = param.default
    return result
  }, {})
}

function ThumbnailScreen({ agent }) {
  const timestamp = thumbnailTimestamp(agent)
  const [attempt, setAttempt] = useState(0)
  const [requested, setRequested] = useState(false)
  const [previewOpen, setPreviewOpen] = useState(false)
  const [image, setImage] = useState({ status: timestamp ? 'masked' : 'empty', url: '' })
  const stale = isThumbnailStale(timestamp)

  useEffect(() => {
    if (!timestamp) {
      setImage({ status: 'empty', url: '' })
      return undefined
    }
    if (!requested) {
      setImage({ status: 'masked', url: '' })
      return undefined
    }

    const controller = new AbortController()
    let loadedImage = null
    setImage({ status: 'loading', url: '' })

    loadManagedThumbnail(api, agent.id, { signal: controller.signal }).then(result => {
      loadedImage = result
      if (controller.signal.aborted) {
        result.release()
        return
      }
      setImage({ status: 'ready', url: result.url })
    }).catch(error => {
      if (controller.signal.aborted || error?.code === 'ERR_CANCELED') return
      setImage({ status: error?.response?.status === 404 ? 'empty' : 'error', url: '' })
    })

    return () => {
      controller.abort()
      loadedImage?.release()
    }
  }, [agent.id, attempt, requested, timestamp])

  const openPreview = () => {
    if (image.status === 'ready') setPreviewOpen(true)
  }

  const screenImage = image.status === 'ready' && (
    <img src={image.url} alt={`${agent.machine_name} 最近上传的屏幕缩略图`} />
  )

  return (
    <>
      <div
        className={`managed-monitor${image.status === 'ready' ? ' is-zoomable' : ''}`}
        aria-busy={image.status === 'loading'}
        role={image.status === 'ready' ? 'button' : undefined}
        tabIndex={image.status === 'ready' ? 0 : undefined}
        aria-label={image.status === 'ready' ? `放大查看 ${agent.machine_name} 的屏幕画面` : undefined}
        onClick={openPreview}
        onKeyDown={event => {
          if (image.status === 'ready' && (event.key === 'Enter' || event.key === ' ')) {
            event.preventDefault()
            openPreview()
          }
        }}
      >
        <div className="managed-monitor__screen">
        {screenImage}
        {image.status === 'masked' && (
          <div className="managed-thumbnail-state managed-thumbnail-state--masked">
            <SafetyCertificateOutlined />
            <span>画面已遮罩，查看操作会记录审计</span>
            <Button
              size="small"
              type="primary"
              icon={<EyeOutlined />}
              onClick={() => setRequested(true)}
            >
              查看画面
            </Button>
          </div>
        )}
        {image.status === 'loading' && (
          <div className="managed-thumbnail-state">
            <LoadingOutlined spin />
            <span>正在安全读取画面</span>
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
          {image.status === 'ready' && (
            <span className="managed-thumbnail-zoom"><ZoomInOutlined /> 点击放大</span>
          )}
        </div>
        <div className="managed-monitor__chin"><span /></div>
        <div className="managed-monitor__stand" aria-hidden="true" />
      </div>

      <Modal
        className="managed-thumbnail-modal"
        title={`${agent.machine_name} · 最新画面`}
        open={previewOpen}
        onCancel={() => setPreviewOpen(false)}
        footer={null}
        width={960}
        centered
        destroyOnHidden
      >
        <div className="managed-monitor managed-monitor--preview">
          <div className="managed-monitor__screen">
            {screenImage}
            {stale && <span className="managed-thumbnail-age"><WarningOutlined /> 画面较旧</span>}
          </div>
          <div className="managed-monitor__chin"><span /></div>
          <div className="managed-monitor__stand" aria-hidden="true" />
        </div>
        <p className="managed-thumbnail-modal__meta">
          画面更新时间：{timestamp ? formatServerTime(timestamp) : '暂无'}
        </p>
      </Modal>
    </>
  )
}

function AgentCard({ agent, updating, scheduleSummary, onPause, onRestore, onDispatch, onDelete, onOpenRun, onOpenHistory, onOpenThumbnailAudit }) {
  const currentRun = agent.current_run
  const latestRun = agent.latest_run
  const earliestPending = agent.earliest_pending
  const status = currentRun || agent.running_run_id
    ? { color: 'processing', text: (currentRun?.dispatch_type || agent.running_dispatch_type) === 'managed_schedule' ? '运行中（定时）' : '运行中（临时）' }
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
        <div><dt>采集允许</dt><dd>{agent.enabled ? '服务端允许上传' : '设备停用，不接收上传'}</dd></div>
        <div><dt>设备端暂停</dt><dd>{agent.thumbnail_capture_paused ? '已暂停（管理员不可恢复）' : '未暂停'}</dd></div>
        <div><dt>最近上传</dt><dd>{updatedAt ? formatServerTime(updatedAt) : '尚未上传'}</dd></div>
        <div>
          <dt>定时任务</dt>
          <dd>{scheduleSummary.enabled || scheduleSummary.paused
            ? `${scheduleSummary.enabled} 个启用 · ${scheduleSummary.paused} 个暂停`
            : '暂无'}</dd>
        </div>
      </dl>

      <section className="managed-agent-card__runs" aria-label="任务状态摘要">
        <div className="managed-agent-card__run-row">
          <span>待领取</span>
          <div>
            <strong>{agent.pending_count || 0} 项</strong>
            {earliestPending && (
              <Button type="link" size="small" onClick={() => onOpenRun(earliestPending.id)}>
                最早 #{earliestPending.id}
              </Button>
            )}
          </div>
          <small>{earliestPending?.expires_at ? `截止 ${formatServerTime(earliestPending.expires_at)}` : '当前无待领取任务'}</small>
        </div>
        <div className="managed-agent-card__run-row">
          <span>当前运行</span>
          {currentRun ? (
            <>
              <Button type="link" size="small" onClick={() => onOpenRun(currentRun.id)}>
                #{currentRun.id} · {currentRun.script_name || `脚本 ${currentRun.script_id}`}
              </Button>
              <small>{currentRun.started_at ? `开始于 ${formatServerTime(currentRun.started_at)}` : '正在准备执行'}</small>
            </>
          ) : <small>当前未运行</small>}
        </div>
        <div className="managed-agent-card__run-row">
          <span>最近结果</span>
          {latestRun ? (
            <>
              <div>
                <Tag color={latestRun.status === 'success' ? 'green' : latestRun.status === 'failed' ? 'red' : 'default'}>
                  {runStatusLabels[latestRun.status] || latestRun.status}
                </Tag>
                <Button type="link" size="small" onClick={() => onOpenRun(latestRun.id)}>#{latestRun.id}</Button>
                {latestRun.has_result_files && <Tag>有结果文件</Tag>}
              </div>
              <small>{latestRun.finished_at ? formatServerTime(latestRun.finished_at) : '结束时间未知'}</small>
              {latestRun.error_summary && (
                <p className="managed-agent-card__error" title={latestRun.error_summary}>{latestRun.error_summary}</p>
              )}
            </>
          ) : <small>暂无已结束任务</small>}
        </div>
      </section>

      <div className="managed-agent-card__actions">
        <Button
          className="managed-agent-acceptance-action"
          icon={agent.enabled ? <PauseCircleOutlined /> : <PlayCircleOutlined />}
          loading={updating}
          onClick={() => agent.enabled ? onPause(agent) : onRestore(agent)}
        >
          {agent.enabled ? '暂停接单' : '恢复接单'}
        </Button>
        <div className="managed-agent-card__primary-actions">
          <Button type="text" icon={<SafetyCertificateOutlined />} onClick={() => onOpenThumbnailAudit(agent.id)}>查看记录</Button>
          <Button type="text" icon={<EyeOutlined />} onClick={() => onOpenHistory(agent.id)}>历史</Button>
          <Tooltip title={!agent.enabled ? '设备已停用；可查看计划，但不能发布新任务' : ''}>
            <Button type="primary" icon={<SendOutlined />} disabled={!agent.enabled} onClick={() => onDispatch(agent)}>
              发布任务
            </Button>
          </Tooltip>
          <Tooltip title="删除设备">
            <Button danger type="text" icon={<DeleteOutlined />} onClick={() => onDelete(agent)} aria-label={`删除设备${agent.machine_name}`} />
          </Tooltip>
        </div>
      </div>
    </article>
  )
}

export default function ManagedAgents({ embedded = false }) {
  const navigate = useNavigate()
  const pageFocused = usePageFocused()
  const [agents, setAgents] = useState([])
  const [schedules, setSchedules] = useState([])
  const [scripts, setScripts] = useState([])
  const [environments, setEnvironments] = useState([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState('')
  const [updating, setUpdating] = useState({})
  const [impactDialog, setImpactDialog] = useState({
    open: false, action: 'disable', agent: null, data: null,
    loading: false, submitting: false, error: '', confirmName: '',
  })
  const [scheduleActionLoading, setScheduleActionLoading] = useState({})
  const [dispatchAgent, setDispatchAgent] = useState(null)
  const [editingSchedule, setEditingSchedule] = useState(null)
  const [scriptDetails, setScriptDetails] = useState({})
  const [optionsResource, setOptionsResource] = useState({ status: 'empty', error: '' })
  const [scriptResource, setScriptResource] = useState({ status: 'empty', error: '', scriptId: null })
  const [submitting, setSubmitting] = useState(false)
  const [query, setQuery] = useState('')
  const [statusFilter, setStatusFilter] = useState('all')
  const [page, setPage] = useState(1)
  const listRequest = useRef(null)
  const impactRequest = useRef(null)
  const optionsRequest = useRef(0)
  const scriptRequest = useRef(0)
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
  const shortMonthDay = selectedScheduleType === 'cron'
    ? shortMonthSkipDay(cronValues, cronExpression)
    : null

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
      } else if (!controller.signal.aborted && scheduleResult.status === 'rejected') {
        throw scheduleResult.reason
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
    return () => {
      listRequest.current?.abort()
      impactRequest.current?.abort()
    }
  }, [load])

  const hasActiveWork = useMemo(
    () => agents.some(agent => (agent.pending_count || 0) > 0 || agent.current_run || agent.running_run_id),
    [agents],
  )

  useEffect(() => {
    const timer = setInterval(
      () => load({ quiet: true }),
      refreshDelay({ hasActive: hasActiveWork, isFocused: pageFocused }),
    )
    return () => clearInterval(timer)
  }, [hasActiveWork, load, pageFocused])

  const loadScriptDetail = useCallback(async (scriptId, applyDefaults = true) => {
    const requestId = scriptRequest.current + 1
    scriptRequest.current = requestId
    if (!scriptId) {
      setScriptResource({ status: 'empty', error: '', scriptId: null })
      return
    }
    if (scriptDetails[scriptId]) {
      const params = parseScriptConfig(scriptDetails[scriptId].config_json).params || []
      setScriptResource({ status: dispatchResourceState({ value: params }), error: '', scriptId })
      if (applyDefaults) form.setFieldValue('params', parameterDefaults(params))
      return
    }
    setScriptResource({ status: 'loading', error: '', scriptId })
    try {
      const response = await api.get(`/api/scripts/${scriptId}`)
      if (scriptRequest.current !== requestId) return
      const params = parseScriptConfig(response.data?.config_json).params || []
      setScriptDetails(current => ({ ...current, [scriptId]: response.data }))
      setScriptResource({ status: dispatchResourceState({ value: params }), error: '', scriptId })
      if (applyDefaults) form.setFieldValue('params', parameterDefaults(params))
    } catch (error) {
      if (scriptRequest.current !== requestId) return
      setScriptResource({
        status: 'error',
        error: apiErrorMessage(error, '脚本参数加载失败，请重试'),
        scriptId,
      })
    }
  }, [form, scriptDetails])

  const scriptsById = useMemo(() => new Map(scripts.map(script => [script.id, script])), [scripts])

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

  const closeDispatch = () => {
    optionsRequest.current += 1
    scriptRequest.current += 1
    setDispatchAgent(null)
    setEditingSchedule(null)
  }

  const loadDispatchOptions = async agent => {
    if (!agent) return
    const requestId = optionsRequest.current + 1
    optionsRequest.current = requestId
    setOptionsResource({ status: 'loading', error: '' })
    try {
      const response = await api.get(`/api/admin/managed-agents/${agent.id}/options`)
      if (optionsRequest.current !== requestId) return
      const nextScripts = response.data?.scripts || []
      setScripts(nextScripts)
      setEnvironments(response.data?.environments || [])
      setOptionsResource({ status: dispatchResourceState({ value: nextScripts }), error: '' })
    } catch (error) {
      if (optionsRequest.current !== requestId) return
      setOptionsResource({
        status: 'error',
        error: apiErrorMessage(error, '无法读取该设备可用的脚本和环境'),
      })
    }
  }

  const openDispatch = agent => {
    setDispatchAgent(agent)
    setEditingSchedule(null)
    setScripts([])
    setEnvironments([])
    setScriptResource({ status: 'empty', error: '', scriptId: null })
    form.resetFields()
    form.setFieldsValue({
      ...scheduleFormValues(null),
      task_type: 'manual',
    })
    void loadDispatchOptions(agent)
  }

  const openEditSchedule = schedule => {
    setEditingSchedule(schedule)
    form.resetFields()
    form.setFieldsValue({
      ...scheduleFormValues(schedule),
      task_type: 'schedule',
    })
    loadScriptDetail(schedule.script_id, false)
  }

  const runScheduleAction = async (schedule, action) => {
    const actionKey = `${schedule.id}:${action}`
    setScheduleActionLoading(current => ({ ...current, [actionKey]: true }))
    try {
      const response = await api.post(`/api/admin/managed-schedules/${schedule.id}/${action}`)
      const successText = {
        enable: `定时任务“${schedule.name}”已恢复`,
        disable: `定时任务“${schedule.name}”已暂停`,
        'run-now': `定时任务“${schedule.name}”已提交运行 #${response.data.id}`,
      }[action]
      message.success(successText)
      setSchedules(current => current.map(item => {
        if (item.id !== schedule.id) return item
        if (action === 'run-now') {
          return {
            ...item,
            latest_run_id: response.data.id,
            latest_run_status: response.data.status,
            last_run_at: response.data.created_at || item.last_run_at,
          }
        }
        return { ...item, ...response.data }
      }))
      await load({ quiet: true })
    } catch (error) {
      const fallback = {
        enable: `恢复定时任务“${schedule.name}”失败`,
        disable: `暂停定时任务“${schedule.name}”失败`,
        'run-now': `立即运行“${schedule.name}”失败`,
      }[action]
      message.error(apiErrorMessage(error, fallback))
    } finally {
      setScheduleActionLoading(current => ({ ...current, [actionKey]: false }))
    }
  }

  const deleteSchedule = async schedule => {
    const actionKey = `${schedule.id}:delete`
    setScheduleActionLoading(current => ({ ...current, [actionKey]: true }))
    try {
      await api.delete(`/api/admin/managed-schedules/${schedule.id}`)
      setSchedules(current => current.filter(item => item.id !== schedule.id))
      if (editingSchedule?.id === schedule.id) setEditingSchedule(null)
      message.success(`定时任务“${schedule.name}”已删除，待执行任务已取消`)
    } catch (error) {
      message.error(apiErrorMessage(error, `删除定时任务“${schedule.name}”失败`))
    } finally {
      setScheduleActionLoading(current => ({ ...current, [actionKey]: false }))
    }
  }

  const loadImpact = useCallback(async (agent, action, { resetName = false } = {}) => {
    impactRequest.current?.abort()
    const controller = new AbortController()
    impactRequest.current = controller
    setImpactDialog(current => ({
      ...current,
      open: true,
      action,
      agent,
      data: null,
      loading: true,
      submitting: false,
      error: '',
      confirmName: resetName ? '' : current.confirmName,
    }))
    try {
      const response = await api.get(`/api/admin/managed-agents/${agent.id}/impact`, {
        params: { action },
        signal: controller.signal,
      })
      if (!controller.signal.aborted) {
        setImpactDialog(current => current.agent?.id === agent.id && current.action === action
          ? { ...current, data: response.data, loading: false }
          : current)
      }
    } catch (error) {
      if (!controller.signal.aborted && error?.code !== 'ERR_CANCELED') {
        setImpactDialog(current => current.agent?.id === agent.id && current.action === action
          ? { ...current, loading: false, error: apiErrorMessage(error, '无法读取操作影响，请重试') }
          : current)
      }
    } finally {
      if (impactRequest.current === controller) impactRequest.current = null
    }
  }, [])

  const closeImpact = () => {
    if (impactDialog.submitting) return
    impactRequest.current?.abort()
    impactRequest.current = null
    setImpactDialog(current => ({ ...current, open: false }))
  }

  const restoreAgent = async agent => {
    setUpdating(current => ({ ...current, [agent.id]: true }))
    try {
      const response = await api.patch(`/api/admin/managed-agents/${agent.id}`, { enabled: true })
      setAgents(current => current.map(item => item.id === agent.id ? { ...item, ...response.data } : item))
      message.success('设备已恢复接单；原有定时计划仍保持暂停')
    } catch (error) {
      message.error(apiErrorMessage(error, '恢复接单失败'))
    } finally {
      setUpdating(current => ({ ...current, [agent.id]: false }))
    }
  }

  const confirmImpact = async () => {
    const { action, agent, data } = impactDialog
    if (!agent || !data) return
    setImpactDialog(current => ({ ...current, submitting: true, error: '' }))
    try {
      if (action === 'disable') {
        const response = await api.patch(`/api/admin/managed-agents/${agent.id}`, {
          enabled: false,
          impact_version: data.version,
        })
        setAgents(current => current.map(item => item.id === agent.id ? { ...item, ...response.data } : item))
        message.success(`设备“${agent.machine_name}”已暂停接单，关联启用计划已暂停`)
      } else {
        await api.delete(`/api/admin/managed-agents/${agent.id}`, {
          params: { impact_version: data.version },
        })
        setAgents(current => current.filter(item => item.id !== agent.id))
        if (dispatchAgent?.id === agent.id) closeDispatch()
        message.success(`设备“${agent.machine_name}”已删除；同一设备身份不会自动恢复`)
      }
      setImpactDialog(current => ({ ...current, open: false, submitting: false }))
      await load({ quiet: true })
    } catch (error) {
      const conflict = error?.response?.status === 409
      setImpactDialog(current => ({
        ...current,
        submitting: false,
        data: conflict ? null : current.data,
        error: apiErrorMessage(error, conflict ? '设备状态已变化，请重新获取影响预览' : '操作失败'),
      }))
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
        const payload = buildSchedulePayload({ ...values, agent_id: dispatchAgent.id })
        if (editingSchedule) {
          await api.patch(`/api/admin/managed-schedules/${editingSchedule.id}`, payload)
          message.success(`定时任务“${payload.name}”已更新`)
        } else {
          await api.post('/api/admin/managed-schedules', payload)
          message.success(`定时任务“${payload.name}”已创建`)
        }
      } else {
        const response = await api.post(`/api/admin/managed-agents/${dispatchAgent.id}/runs`, {
          script_id: values.script_id,
          params: values.params || {},
          environment_id: values.environment_id ?? null,
          expires_in_seconds: expires,
        })
        message.success(`临时任务 #${response.data.id} 已发布`)
      }
      closeDispatch()
      load({ quiet: true })
    } catch (error) {
      const cronUnsupported = isSchedule && values.schedule_type === 'cron' && [400, 404, 422].includes(error?.response?.status)
      const fallback = cronUnsupported
        ? '当前服务端可能尚未支持 Cron 定时，请升级服务端或改用固定间隔'
        : isSchedule ? (editingSchedule ? '定时任务更新失败' : '定时任务创建失败') : '临时任务发布失败'
      const errorText = apiErrorMessage(error, fallback)
      message.error(cronUnsupported && errorText !== fallback ? `${errorText}；如服务端版本较旧，请升级或改用固定间隔` : errorText)
    } finally {
      setSubmitting(false)
    }
  }

  const dispatchSchedules = schedulesByAgent.get(dispatchAgent?.id) || []
  const dispatchScheduleCounts = scheduleStatusCounts(dispatchSchedules)
  const taskFieldsDisabled = selectedTaskType === 'manual'
    ? !dispatchAgent?.enabled || Boolean(dispatchAgent?.current_run || dispatchAgent?.running_run_id)
    : !dispatchAgent?.enabled && !editingSchedule
  const selectedScriptResource = scriptResource.scriptId === selectedScriptId ? scriptResource.status : 'empty'
  const dispatchDataUnavailable = optionsResource.status !== 'ready'
    || (selectedScriptId && ['loading', 'error'].includes(selectedScriptResource))
  const impactMachineName = impactDialog.data?.machine_name || impactDialog.agent?.machine_name

  return (
    <div className="managed-admin-page">
      <div className={embedded ? 'managed-section-heading' : 'page-heading'}>
        <div>
          {embedded ? <h3>设备、临时任务与定时任务</h3> : <h2>被控设备</h2>}
          <p>查看设备状态，发布临时任务，并维护固定间隔或 Cron 定时任务</p>
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
                key={`${agent.id}:${page}:${statusFilter}:${query}`}
                agent={agent}
                updating={Boolean(updating[agent.id])}
                scheduleSummary={scheduleStatusCounts(schedulesByAgent.get(agent.id) || [])}
                onPause={item => loadImpact(item, 'disable', { resetName: true })}
                onRestore={restoreAgent}
                onDispatch={openDispatch}
                onDelete={item => loadImpact(item, 'delete', { resetName: true })}
                onOpenRun={runId => navigate(`/runs/${runId}`)}
                onOpenHistory={agentId => navigate(`/runs?agent_id=${agentId}`)}
                onOpenThumbnailAudit={() => navigate('/audit?action=managed_thumbnail.view')}
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
        <section className="managed-agent-onboarding" aria-labelledby="managed-first-device-title">
          <div className="managed-agent-onboarding__intro">
            <DesktopOutlined aria-hidden="true" />
            <div>
              <h3 id="managed-first-device-title">{MANAGED_FIRST_CONNECTION_GUIDE.title}</h3>
              <p>完成一次真实连接后，设备状态、画面与任务入口会显示在这里。</p>
            </div>
          </div>
          <ol className="managed-agent-onboarding__steps">
            {MANAGED_FIRST_CONNECTION_GUIDE.steps.map((step, index) => (
              <li key={step}><span aria-hidden="true">{index + 1}</span><p>{step}</p></li>
            ))}
          </ol>
          <Alert
            type="info"
            showIcon
            title={MANAGED_FIRST_CONNECTION_GUIDE.minimumVersion}
            description={(
              <ul className="managed-agent-onboarding__troubleshooting">
                {MANAGED_FIRST_CONNECTION_GUIDE.troubleshooting.map(item => <li key={item}>{item}</li>)}
              </ul>
            )}
          />
          <Alert
            className="managed-agent-onboarding__safety"
            type="warning"
            showIcon
            title="首次上线后先做安全试运行"
            description="先选择无副作用、可快速结束的脚本，使用测试环境和最小参数发布一次临时任务；确认设备、日志与结果均正确后，再创建定时任务。"
          />
          <div className="managed-agent-onboarding__actions">
            {MANAGED_FIRST_CONNECTION_GUIDE.links.map(link => (
              <Button key={link.route} onClick={() => navigate(link.route)}>{link.label}</Button>
            ))}
            <Button type="primary" icon={<ReloadOutlined />} onClick={() => load()}>我已启动客户端，刷新状态</Button>
          </div>
        </section>
      ) : null}

      <Modal
        className="managed-impact-modal"
        title={impactDialog.action === 'delete' ? '删除设备前确认影响' : '暂停接单前确认影响'}
        open={impactDialog.open}
        onCancel={closeImpact}
        width={620}
        centered
        destroyOnHidden
        okText={impactDialog.action === 'delete' ? '永久删除设备' : '确认暂停接单'}
        cancelText="取消"
        okButtonProps={{
          danger: impactDialog.action === 'delete',
          disabled: impactDialog.loading || !impactDialog.data || !canConfirmAgentImpact(
            impactDialog.action,
            impactDialog.confirmName,
            impactMachineName,
          ),
          loading: impactDialog.submitting,
        }}
        cancelButtonProps={{ disabled: impactDialog.submitting }}
        onOk={confirmImpact}
      >
        {impactDialog.loading ? (
          <div className="managed-impact-loading"><Skeleton active paragraph={{ rows: 4 }} /></div>
        ) : impactDialog.error ? (
          <Alert
            type="error"
            showIcon
            title="无法继续操作"
            description={impactDialog.error}
            action={(
              <Button
                size="small"
                onClick={() => loadImpact(impactDialog.agent, impactDialog.action)}
              >
                重新获取
              </Button>
            )}
          />
        ) : impactDialog.data ? (
          <div className="managed-impact-content">
            <Alert
              type={impactDialog.action === 'delete' ? 'error' : 'warning'}
              showIcon
              title={`设备“${impactMachineName}”${impactDialog.action === 'delete' ? '将被删除' : '将停止接收任务'}`}
              description="以下数量来自刚刚获取的服务端预览；确认时若状态已变化，操作会被拒绝。"
            />
            <dl className="managed-impact-counts">
              {agentImpactCounts(impactDialog.data).map(item => (
                <div key={item.key}>
                  <dt>{item.label}</dt>
                  <dd>{item.value}</dd>
                </div>
              ))}
            </dl>
            <ul className="managed-impact-consequences">
              <li>{impactDialog.data.pending_count} 个待执行任务将取消，{impactDialog.data.running_count} 个运行中任务将终止。</li>
              <li>{impactDialog.data.enabled_schedule_count} 个启用计划将暂停；已有暂停计划保持不变。</li>
              <li>{impactDialog.data.history_policy?.message}</li>
              <li>
                {impactDialog.action === 'delete'
                  ? `最新屏幕缩略图${impactDialog.data.thumbnail_exists ? '将永久删除' : '不存在，无需清理'}。`
                  : `最新屏幕缩略图${impactDialog.data.thumbnail_exists ? '将保留' : '当前不存在'}。`}
              </li>
              <li>{impactDialog.data.identity_recovery?.message}</li>
            </ul>
            {impactDialog.action === 'delete' && (
              <div className="managed-impact-name-confirmation">
                <label htmlFor="managed-delete-device-name">
                  输入设备名 <strong>{impactMachineName}</strong> 以确认删除
                </label>
                <Input
                  id="managed-delete-device-name"
                  value={impactDialog.confirmName}
                  status={impactDialog.confirmName && !canConfirmAgentImpact(
                    'delete', impactDialog.confirmName, impactMachineName,
                  ) ? 'error' : undefined}
                  placeholder="完整输入设备名"
                  autoComplete="off"
                  onChange={event => setImpactDialog(current => ({
                    ...current, confirmName: event.target.value,
                  }))}
                />
              </div>
            )}
          </div>
        ) : null}
      </Modal>

      <Drawer
        title={editingSchedule
          ? `编辑 ${dispatchAgent?.machine_name || ''} 的定时任务`
          : `向 ${dispatchAgent?.machine_name || ''} 发布任务`}
        open={Boolean(dispatchAgent)}
        onClose={() => !submitting && closeDispatch()}
        width={620}
        rootClassName="managed-dispatch-drawer"
        extra={(
          <Button
            type="primary"
            icon={<SendOutlined />}
            loading={submitting}
            disabled={taskFieldsDisabled || dispatchDataUnavailable}
            onClick={() => form.submit()}
          >
            {editingSchedule ? '保存定时任务' : selectedTaskType === 'schedule' ? '创建定时任务' : '发布临时任务'}
          </Button>
        )}
        destroyOnHidden
      >
        {dispatchAgent?.current_run || dispatchAgent?.running_run_id ? (
          <Alert
            className="managed-drawer-alert"
            type="warning"
            showIcon
            title={`设备正在执行${(dispatchAgent.current_run?.dispatch_type || dispatchAgent.running_dispatch_type) === 'managed_schedule' ? '定时' : '临时'}任务 #${dispatchAgent.current_run?.id || dispatchAgent.running_run_id}`}
            description="当前任务结束前不能再发布临时任务，但仍可切换到定时任务进行查看或创建。"
          />
        ) : dispatchAgent?.status !== 'online' ? (
          <Alert className="managed-drawer-alert" type="warning" showIcon title="设备当前离线" description="临时任务会保留到有效期结束；设备恢复连接后才能领取。" />
        ) : null}

        {optionsResource.status === 'loading' && (
          <Alert
            className="managed-drawer-alert"
            type="info"
            showIcon
            title="正在读取可用脚本与执行环境"
            description="已填写的任务内容不会因重新读取而清空。"
          />
        )}
        {optionsResource.status === 'error' && (
          <Alert
            className="managed-drawer-alert"
            type="error"
            showIcon
            title="可用选项读取失败"
            description={optionsResource.error}
            action={<Button onClick={() => loadDispatchOptions(dispatchAgent)}>重试读取</Button>}
          />
        )}
        {optionsResource.status === 'empty' && (
          <Alert
            className="managed-drawer-alert"
            type="info"
            showIcon
            title="该设备暂无可用脚本"
            description="请求已成功，但没有可发布的启用脚本。请先在脚本管理中安装或启用脚本，然后重试读取。"
            action={<Button onClick={() => navigate('/scripts')}>打开脚本管理</Button>}
          />
        )}

        <Form form={form} layout="vertical" onFinish={dispatch} requiredMark="optional">
          <Form.Item name="task_type" label="任务类型">
            <Segmented
              block
              disabled={Boolean(editingSchedule)}
              options={[
                { label: '临时任务', value: 'manual' },
                { label: '定时任务', value: 'schedule' },
              ]}
            />
          </Form.Item>

          {selectedTaskType === 'schedule' && (
            <div className="managed-schedule-reveal is-open">
              <div className="managed-schedule-reveal__inner">
                <section className="managed-dispatch-schedules">
                  <div className="managed-dispatch-schedules__heading">
                    <div>
                      <h3>当前已安排</h3>
                      <span>{dispatchScheduleCounts.enabled} 个启用 · {dispatchScheduleCounts.paused} 个暂停</span>
                    </div>
                  </div>
                  {dispatchSchedules.length ? (
                    <div className="managed-dispatch-schedules__list">
                      {dispatchSchedules.map(schedule => {
                        const toggleAction = schedule.enabled ? 'disable' : 'enable'
                        const toggleText = schedule.enabled ? '暂停' : '恢复'
                        return (
                          <article className={`managed-dispatch-schedule-row${editingSchedule?.id === schedule.id ? ' is-editing' : ''}`} key={schedule.id}>
                            <div className="managed-dispatch-schedule-row__summary">
                              <div>
                                <strong title={schedule.name}>{schedule.name}</strong>
                                <Tag color={schedule.enabled ? 'green' : 'default'}>{schedule.enabled ? '已启用' : '已暂停'}</Tag>
                              </div>
                              <span>{scriptsById.get(schedule.script_id)?.name || `脚本 #${schedule.script_id}`}</span>
                              <small>{formatSchedule(schedule)}</small>
                              <small>{schedule.enabled ? `下次 ${formatServerTime(schedule.next_run_at)}` : '暂停期间不会自动下发'}</small>
                              <small>
                                {schedule.latest_run_id
                                  ? `最近运行 #${schedule.latest_run_id} · ${runStatusLabels[schedule.latest_run_status] || schedule.latest_run_status || '状态未知'}`
                                  : '暂无最近运行'}
                              </small>
                            </div>
                            <Space className="managed-dispatch-schedule-row__actions" size={2} wrap>
                              <Button type="text" size="small" icon={<EditOutlined />} onClick={() => openEditSchedule(schedule)}>编辑</Button>
                              <Popconfirm
                                title={`${toggleText}定时任务“${schedule.name}”？`}
                                description={schedule.enabled ? '暂停后不会再自动下发任务。' : '恢复后将重新计算下一次运行时间。'}
                                okText={toggleText}
                                cancelText="取消"
                                onConfirm={() => runScheduleAction(schedule, toggleAction)}
                              >
                                <Button
                                  type="text"
                                  size="small"
                                  icon={schedule.enabled ? <PauseCircleOutlined /> : <PlayCircleOutlined />}
                                  loading={scheduleActionLoading[`${schedule.id}:${toggleAction}`]}
                                >
                                  {toggleText}
                                </Button>
                              </Popconfirm>
                              <Popconfirm
                                title={`立即运行“${schedule.name}”？`}
                                description="确认后会立即创建一次待执行任务。"
                                okText="立即运行"
                                cancelText="取消"
                                onConfirm={() => runScheduleAction(schedule, 'run-now')}
                              >
                                <Button type="text" size="small" icon={<ThunderboltOutlined />} loading={scheduleActionLoading[`${schedule.id}:run-now`]}>运行</Button>
                              </Popconfirm>
                              <Tooltip title={schedule.latest_run_id ? `查看运行 #${schedule.latest_run_id}` : '暂无最近运行'}>
                                <Button
                                  type="text"
                                  size="small"
                                  icon={<EyeOutlined />}
                                  disabled={!schedule.latest_run_id}
                                  onClick={() => schedule.latest_run_id && navigate(`/runs/${schedule.latest_run_id}`)}
                                >
                                  最近运行
                                </Button>
                              </Tooltip>
                              <Popconfirm
                                title={`删除定时任务“${schedule.name}”？`}
                                description="待执行任务会被取消；已执行和运行中的历史记录会保留。"
                                okText="删除"
                                cancelText="取消"
                                okButtonProps={{ danger: true }}
                                onConfirm={() => deleteSchedule(schedule)}
                              >
                                <Button danger type="text" size="small" icon={<DeleteOutlined />} loading={scheduleActionLoading[`${schedule.id}:delete`]}>删除</Button>
                              </Popconfirm>
                            </Space>
                          </article>
                        )
                      })}
                    </div>
                  ) : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="该设备暂无定时任务" />}
                </section>

                <Form.Item name="name" label={editingSchedule ? '编辑任务名称' : '任务名称'} rules={[{ required: true, whitespace: true, message: '请输入任务名称' }]}>
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
                    {shortMonthDay && (
                      <Alert
                        className="managed-cron-month-warning"
                        type="warning"
                        showIcon
                        title={`每月 ${shortMonthDay} 日执行时，没有该日期的短月份不会执行。`}
                      />
                    )}
                    <div className={`managed-cron-summary${isValidCronExpression(cronExpression) ? '' : ' is-invalid'}`} aria-live="polite">
                      <span>执行摘要</span><strong>{describeCron(cronExpression)}</strong>
                    </div>
                  </div>
                )}
                <Form.Item name="enabled" label={editingSchedule ? '任务启用状态' : '创建后立即启用'} valuePropName="checked">
                  <Switch checkedChildren="启用" unCheckedChildren="暂停" />
                </Form.Item>
              </div>
            </div>
          )}

          <fieldset className="managed-task-fields" disabled={taskFieldsDisabled}>
          <Form.Item name="script_id" label="脚本" rules={[{ required: true, message: '请选择脚本' }]}>
            <Select
              showSearch
              optionFilterProp="label"
              placeholder="选择要在此设备运行的脚本"
              loading={optionsResource.status === 'loading'}
              disabled={optionsResource.status !== 'ready'}
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

          <div className="managed-form-section" aria-live="polite">
            <h3>脚本参数</h3>
            {!selectedScriptId && <div className="managed-param-empty">选择脚本后读取参数配置</div>}
            {selectedScriptId && selectedScriptResource === 'loading' && (
              <Skeleton active paragraph={{ rows: 2 }} title={false} />
            )}
            {selectedScriptId && selectedScriptResource === 'error' && (
              <Alert
                type="error"
                showIcon
                title="脚本详情读取失败"
                description={scriptResource.error}
                action={<Button onClick={() => loadScriptDetail(selectedScriptId)}>重试</Button>}
              />
            )}
            {selectedScriptId && selectedScriptResource === 'empty' && (
              <div className="managed-param-empty">脚本详情已读取，此脚本无需额外参数</div>
            )}
            {selectedScriptId && selectedScriptResource === 'ready' && (
              <ManagedParamFields params={scriptParams} />
            )}
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
