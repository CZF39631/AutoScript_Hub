export const taskStates = {
  queued: ['等待领取', 'blue'], claimed: ['准备中', 'processing'], running: ['执行中', 'orange'],
  cancel_requested: ['正在取消', 'orange'], unknown: ['结果未知', 'warning'],
  success: ['成功', 'green'], failed: ['失败', 'red'], cancelled: ['已取消', 'default'], skipped: ['已跳过', 'default'],
  pending: ['等待确认', 'blue'], accepted: ['已授权', 'green'], rejected: ['已拒绝', 'default'], revoked: ['已撤销', 'default'],
}

export { safeError as taskError } from './safeError.js'

export function makeTrigger(values) {
  const timezone = values.timezone?.trim()
  try { new Intl.DateTimeFormat('zh-CN', { timeZone: timezone }).format() } catch { throw new Error('请输入有效的 IANA 时区，例如 Asia/Shanghai') }
  if (!timezone) throw new Error('请填写时区')
  const result = { kind: values.kind, timezone, misfire: values.misfire, grace_seconds: values.grace_seconds }
  if (values.kind === 'once') {
    if (!/(Z|[+-]\d{2}:\d{2})$/i.test(values.start_at || '') || !Number.isFinite(Date.parse(values.start_at))) throw new Error('单次时间须包含时区，例如 2026-09-14T09:00:00+08:00')
    result.start_at = values.start_at
  }
  if (['daily', 'weekly'].includes(values.kind)) {
    if (!/^([01]\d|2[0-3]):[0-5]\d$/.test(values.time || '')) throw new Error('请填写有效的小时和分钟')
    result.time = values.time
  }
  if (values.kind === 'weekly') {
    if (!Array.isArray(values.weekdays) || !values.weekdays.length) throw new Error('请至少选择一天')
    result.weekdays = values.weekdays
  }
  return result
}

export function triggerLabel(trigger) {
  try {
    const t = typeof trigger === 'string' ? JSON.parse(trigger) : trigger
    if (!t) return '—'
    const zone = t.timezone || 'UTC'
    if (t.kind === 'manual') return '仅手动'
    if (t.kind === 'once') return `单次 ${t.start_at}`
    const days = ['一', '二', '三', '四', '五', '六', '日']
    return `${t.kind === 'weekly' ? `每周${(t.weekdays || []).map(d => days[d]).join('、')}` : '每天'} ${t.time} (${zone})`
  } catch { return '规则不可用' }
}

export function newRequestId() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID()
  const bytes = globalThis.crypto.getRandomValues(new Uint8Array(16))
  bytes[6] = (bytes[6] & 15) | 64
  bytes[8] = (bytes[8] & 63) | 128
  const s = Array.from(bytes, b => b.toString(16).padStart(2, '0')).join('')
  return `${s.slice(0, 8)}-${s.slice(8, 12)}-${s.slice(12, 16)}-${s.slice(16, 20)}-${s.slice(20)}`
}
