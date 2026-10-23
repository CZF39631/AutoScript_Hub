export const dispatchTypeOptions = [
  { value: 'standard', label: '手工执行' },
  { value: 'managed_manual', label: '管理端下发' },
  { value: 'managed_schedule', label: '托管计划' },
]

const dispatchTypes = new Set(dispatchTypeOptions.map(item => item.value))

function positiveInteger(value) {
  const parsed = Number(value)
  return Number.isInteger(parsed) && parsed > 0 ? parsed : undefined
}

export function parseRunFilterParams(input = '') {
  const params = input instanceof URLSearchParams ? input : new URLSearchParams(input)
  const dispatchType = params.get('dispatch_type')
  return {
    agentId: positiveInteger(params.get('agent_id')),
    scheduleId: positiveInteger(params.get('schedule_id')),
    dispatchType: dispatchTypes.has(dispatchType) ? dispatchType : undefined,
  }
}

export function buildRunQuery({
  status, userId, agentId, scheduleId, dispatchType, dateFrom, dateTo,
} = {}) {
  const params = new URLSearchParams()
  if (status) params.set('status', status)
  if (positiveInteger(userId)) params.set('user_id', String(userId))
  if (positiveInteger(agentId)) params.set('agent_id', String(agentId))
  if (positiveInteger(scheduleId)) params.set('schedule_id', String(scheduleId))
  if (dispatchTypes.has(dispatchType)) params.set('dispatch_type', dispatchType)
  if (dateFrom) params.set('date_from', dateFrom)
  if (dateTo) params.set('date_to', dateTo)
  return params
}

export function refreshDelay({
  hasActive = false,
  isFocused = true,
  activeMs = 5000,
  idleMs = 60000,
  backgroundMs = 60000,
} = {}) {
  if (!isFocused) return backgroundMs
  return hasActive ? activeMs : idleMs
}

export function runDeviceName(run) {
  if (!run) return '-'
  return run.agent_name || run.target_agent_name
    || (run.agent_id ? `设备 #${run.agent_id}` : run.target_agent_id ? `设备 #${run.target_agent_id}` : '-')
}
