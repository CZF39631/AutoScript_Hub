export function formatIssueParams(value) {
  if (value == null || value === '') return { text: '', invalid: false }
  try {
    return { text: JSON.stringify(typeof value === 'string' ? JSON.parse(value) : value, null, 2), invalid: false }
  } catch {
    return { text: String(value), invalid: true }
  }
}

// Invalidate synchronously on every selection/close; guard every async state write.
export function createIssueLogLoader(get, setLog, setLoading) {
  let requestId = 0
  const cancel = () => { requestId += 1 }
  const open = async (issue) => {
    const current = ++requestId
    setLog('')
    setLoading(Boolean(issue?.run_id))
    if (!issue?.run_id) return
    try {
      const response = await get(`/api/issues/${issue.id}/log`)
      if (current === requestId) setLog(response.data.log || '(暂无日志)')
    } catch {
      if (current === requestId) setLog('(日志加载失败，请关闭详情后重试)')
    } finally {
      if (current === requestId) setLoading(false)
    }
  }
  return { open, cancel }
}
