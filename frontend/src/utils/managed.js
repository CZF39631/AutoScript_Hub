export const INTERVAL_UNITS = [
  { value: 'minute', label: '分钟', seconds: 60, max: 525600 },
  { value: 'hour', label: '小时', seconds: 3600, max: 8760 },
  { value: 'day', label: '天', seconds: 86400, max: 365 },
]

const unitMap = new Map(INTERVAL_UNITS.map(item => [item.value, item]))

export const THUMBNAIL_STALE_AFTER_MS = 2 * 60 * 1000

export function thumbnailTimestamp(agent) {
  return agent?.thumbnail_updated_at || null
}

export function shouldRefreshThumbnail(previousTimestamp, nextTimestamp) {
  return Boolean(nextTimestamp) && previousTimestamp !== nextTimestamp
}

export function isThumbnailStale(timestamp, now = Date.now()) {
  if (!timestamp) return false
  const value = timestamp instanceof Date ? timestamp : String(timestamp).trim()
  const normalized = typeof value === 'string' && !/(Z|[+-]\d{2}:?\d{2})$/i.test(value)
    ? `${value}Z`
    : value
  const capturedAt = new Date(normalized).getTime()
  const currentTime = now instanceof Date ? now.getTime() : Number(now)
  if (!Number.isFinite(capturedAt) || !Number.isFinite(currentTime)) return false
  return currentTime - capturedAt > THUMBNAIL_STALE_AFTER_MS
}

export function isManagedClientMode(target = typeof window === 'undefined' ? undefined : window) {
  return target?._CLIENT_MODE === 'managed'
}

export function managedClientPath(pathname = '/') {
  return pathname === '/managed' ? '/managed' : '/managed'
}

export function intervalToSeconds(value, unit) {
  const item = unitMap.get(unit)
  const amount = Number(value)
  if (!item || !Number.isFinite(amount) || amount < 1) return null
  return Math.round(amount * item.seconds)
}

export function secondsToInterval(seconds) {
  const total = Number(seconds)
  if (!Number.isFinite(total) || total < 60) return { value: 1, unit: 'minute' }
  if (total % 86400 === 0) return { value: total / 86400, unit: 'day' }
  if (total % 3600 === 0) return { value: total / 3600, unit: 'hour' }
  return { value: Math.max(1, Math.round(total / 60)), unit: 'minute' }
}

export function formatInterval(seconds) {
  const interval = secondsToInterval(seconds)
  const item = unitMap.get(interval.unit)
  return `每 ${interval.value} ${item?.label || '分钟'}`
}

const WEEKDAY_LABELS = ['星期日', '星期一', '星期二', '星期三', '星期四', '星期五', '星期六']
const CRON_FIELD_PATTERN = /^(?:\*|\d+(?:-\d+)?(?:\/\d+)?)(?:,(?:\*|\d+(?:-\d+)?(?:\/\d+)?))*$/

export function isValidCronExpression(expression) {
  const fields = String(expression || '').trim().split(/\s+/)
  return fields.length === 5 && fields.every(field => CRON_FIELD_PATTERN.test(field))
}

export function buildVisualCron(values = {}) {
  const minute = Number(values.cron_minute ?? 0)
  const hour = Number(values.cron_hour ?? 9)
  if (!Number.isInteger(minute) || minute < 0 || minute > 59) return null
  if (values.cron_preset === 'hourly') return `${minute} * * * *`
  if (!Number.isInteger(hour) || hour < 0 || hour > 23) return null
  if (values.cron_preset === 'weekly') {
    const weekdays = [...new Set(values.cron_weekdays || [])].map(Number).sort((a, b) => a - b)
    if (!weekdays.length || weekdays.some(day => !Number.isInteger(day) || day < 0 || day > 6)) return null
    return `${minute} ${hour} * * ${weekdays.join(',')}`
  }
  if (values.cron_preset === 'monthly') {
    const day = Number(values.cron_monthday ?? 1)
    if (!Number.isInteger(day) || day < 1 || day > 31) return null
    return `${minute} ${hour} ${day} * *`
  }
  return `${minute} ${hour} * * *`
}

export function describeCron(expression) {
  if (!isValidCronExpression(expression)) return '请输入有效的五段 Cron 表达式'
  const [minute, hour, day, month, weekday] = expression.trim().split(/\s+/)
  const time = hour !== '*' && minute !== '*' ? `${String(hour).padStart(2, '0')}:${String(minute).padStart(2, '0')}` : null
  if (hour === '*' && day === '*' && month === '*' && weekday === '*' && /^\d+$/.test(minute)) return `每小时的 ${minute} 分执行`
  if (day === '*' && month === '*' && weekday === '*' && time) return `每天 ${time} 执行`
  if (day === '*' && month === '*' && time && /^(?:[0-6],?)+$/.test(weekday)) {
    const days = weekday.split(',').map(value => WEEKDAY_LABELS[Number(value)]).join('、')
    return `每周${days} ${time} 执行`
  }
  if (/^\d+$/.test(day) && month === '*' && weekday === '*' && time) return `每月 ${day} 日 ${time} 执行`
  return `按 Cron “${expression.trim()}”执行`
}

export function formatSchedule(schedule) {
  const scheduleType = schedule?.schedule_type || (schedule?.cron_expression ? 'cron' : 'interval')
  if (scheduleType === 'cron' && schedule?.cron_expression) {
    return `${describeCron(schedule.cron_expression)} · ${schedule.timezone || 'Asia/Shanghai'}`
  }
  return formatInterval(schedule?.interval_seconds)
}

export function parseParams(value) {
  if (!value) return {}
  if (typeof value === 'object' && !Array.isArray(value)) return value
  try {
    const parsed = JSON.parse(value)
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : {}
  } catch {
    return {}
  }
}

export function statusPresentation(status, enabled = true) {
  if (!enabled) return { color: 'default', text: '已停用' }
  if (status === 'online') return { color: 'green', text: '在线' }
  if (status === 'running') return { color: 'processing', text: '执行中' }
  return { color: 'default', text: '离线' }
}

export function scheduleFormValues(schedule) {
  const interval = secondsToInterval(schedule?.interval_seconds)
  const expires = secondsToInterval(schedule?.expires_after_seconds || 3600)
  const scheduleType = schedule?.schedule_type || (schedule?.cron_expression ? 'cron' : 'interval')
  return {
    name: schedule?.name || '',
    agent_id: schedule?.agent_id,
    script_id: schedule?.script_id,
    params: parseParams(schedule?.params),
    environment_id: schedule?.environment_id ?? undefined,
    schedule_type: scheduleType,
    interval_value: interval.value,
    interval_unit: interval.unit,
    cron_mode: schedule?.cron_expression ? 'advanced' : 'visual',
    cron_preset: 'daily',
    cron_hour: 9,
    cron_minute: 0,
    cron_weekdays: [1],
    cron_monthday: 1,
    cron_expression: schedule?.cron_expression || '0 9 * * *',
    timezone: schedule?.timezone || 'Asia/Shanghai',
    expires_value: expires.value,
    expires_unit: expires.unit,
    enabled: schedule?.enabled ?? true,
  }
}

export function buildSchedulePayload(values) {
  const scheduleType = values.schedule_type === 'cron' ? 'cron' : 'interval'
  const payload = {
    name: values.name?.trim(),
    agent_id: values.agent_id,
    script_id: values.script_id,
    params: values.params || {},
    environment_id: values.environment_id ?? null,
    schedule_type: scheduleType,
    expires_after_seconds: intervalToSeconds(values.expires_value, values.expires_unit),
    enabled: values.enabled !== false,
  }
  if (scheduleType === 'cron') {
    payload.cron_expression = values.cron_mode === 'advanced'
      ? String(values.cron_expression || '').trim()
      : buildVisualCron(values)
    payload.timezone = values.timezone || 'Asia/Shanghai'
  } else {
    payload.interval_seconds = intervalToSeconds(values.interval_value, values.interval_unit)
  }
  return payload
}

export function apiErrorMessage(error, fallback) {
  const detail = error?.response?.data?.detail
  if (typeof detail === 'string' && detail) return detail
  return error?.message || fallback
}
