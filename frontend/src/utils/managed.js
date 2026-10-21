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
  return {
    name: schedule?.name || '',
    agent_id: schedule?.agent_id,
    script_id: schedule?.script_id,
    params: parseParams(schedule?.params),
    environment_id: schedule?.environment_id ?? undefined,
    interval_value: interval.value,
    interval_unit: interval.unit,
    expires_value: expires.value,
    expires_unit: expires.unit,
    enabled: schedule?.enabled ?? true,
  }
}

export function buildSchedulePayload(values) {
  return {
    name: values.name?.trim(),
    agent_id: values.agent_id,
    script_id: values.script_id,
    params: values.params || {},
    environment_id: values.environment_id ?? null,
    interval_seconds: intervalToSeconds(values.interval_value, values.interval_unit),
    expires_after_seconds: intervalToSeconds(values.expires_value, values.expires_unit),
    enabled: values.enabled !== false,
  }
}

export function apiErrorMessage(error, fallback) {
  const detail = error?.response?.data?.detail
  if (typeof detail === 'string' && detail) return detail
  return error?.message || fallback
}
