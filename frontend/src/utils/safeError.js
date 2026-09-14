// Never pass server objects (or echoed input values) to React message content.
export function safeError(error, fallback = '操作失败，请刷新后重试') {
  const detail = error?.response?.data?.detail ?? error?.response?.data?.error
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    const messages = detail.map(item => typeof item?.msg === 'string' ? item.msg : '输入无效')
    return messages.join('；') || fallback
  }
  if (typeof detail?.message === 'string') return detail.message
  return typeof error?.message === 'string' ? error.message : fallback
}
