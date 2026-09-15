import execution from '../i18n/locales/execution.js'

// Default Chinese keeps standalone callers compatible; React callers pass t at render time.
const defaultTranslate = (key, values = {}) => (execution.zh[key] || key).replace(/\{\{(\w+)\}\}/g, (_, name) => String(values[name] ?? ''))

export const taskStates = {
  queued: ['execution.runState.queued', 'blue'], claimed: ['execution.runState.claimed', 'processing'], running: ['execution.runState.running', 'orange'],
  cancel_requested: ['execution.runState.cancel_requested', 'orange'], unknown: ['execution.runState.unknown', 'warning'],
  success: ['execution.runState.success', 'green'], failed: ['execution.runState.failed', 'red'], cancelled: ['execution.runState.cancelled', 'default'], skipped: ['execution.runState.skipped', 'default'],
  pending: ['execution.grantState.pending', 'blue'], accepted: ['execution.grantState.accepted', 'green'], rejected: ['execution.grantState.rejected', 'default'], revoked: ['execution.grantState.revoked', 'default'],
}

export function taskError(error, t = defaultTranslate) {
  const detail = error?.response?.data?.detail ?? error?.response?.data?.error
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) return detail.map(item => typeof item?.msg === 'string' ? item.msg : t('execution.invalidInput')).join(t('execution.errorSeparator')) || t('execution.operationFailed')
  if (typeof detail?.message === 'string') return detail.message
  if (error?.translationKey) return t(error.translationKey)
  return typeof error?.message === 'string' ? error.message : t('execution.operationFailed')
}

export function makeTrigger(values, t = defaultTranslate) {
  const invalid = key => { const error = new Error(t(key)); error.translationKey = key; throw error }
  const timezone = values.timezone?.trim()
  if (!timezone) invalid('execution.requiredTimezone')
  try { new Intl.DateTimeFormat('zh-CN', { timeZone: timezone }).format() } catch { invalid('execution.invalidTimezone') }
  const result = { kind: values.kind, timezone, misfire: values.misfire, grace_seconds: values.grace_seconds }
  if (values.kind === 'once') {
    if (!/(Z|[+-]\d{2}:\d{2})$/i.test(values.start_at || '') || !Number.isFinite(Date.parse(values.start_at))) invalid('execution.invalidOnceTime')
    result.start_at = values.start_at
  }
  if (['daily', 'weekly'].includes(values.kind)) {
    if (!/^([01]\d|2[0-3]):[0-5]\d$/.test(values.time || '')) invalid('execution.invalidTime')
    result.time = values.time
  }
  if (values.kind === 'weekly') {
    if (!Array.isArray(values.weekdays) || !values.weekdays.length) invalid('execution.requiredWeekday')
    result.weekdays = values.weekdays
  }
  return result
}

export function triggerLabel(trigger, translate = defaultTranslate) {
  try {
    const rule = typeof trigger === 'string' ? JSON.parse(trigger) : trigger
    if (!rule) return '—'
    const zone = rule.timezone || 'UTC'
    if (rule.kind === 'manual') return translate('execution.trigger.manual')
    if (rule.kind === 'once') return translate('execution.onceLabel', { time: rule.start_at })
    const schedule = rule.kind === 'weekly'
      ? translate('execution.weeklyLabel', { days: (rule.weekdays || []).map(day => translate(`execution.day.${day}`)).join(translate('execution.daySeparator')) })
      : translate('execution.trigger.daily')
    return translate('execution.recurringLabel', { schedule, time: rule.time, zone })
  } catch { return translate('execution.invalidRule') }
}

export function newRequestId() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID()
  const bytes = globalThis.crypto.getRandomValues(new Uint8Array(16))
  bytes[6] = (bytes[6] & 15) | 64
  bytes[8] = (bytes[8] & 63) | 128
  const s = Array.from(bytes, b => b.toString(16).padStart(2, '0')).join('')
  return `${s.slice(0, 8)}-${s.slice(8, 12)}-${s.slice(12, 16)}-${s.slice(16, 20)}-${s.slice(20)}`
}
