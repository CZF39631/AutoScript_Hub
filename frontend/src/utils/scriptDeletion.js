export function canDeleteMarketScript(user, online) {
  return online === true && user?.role === 'admin'
}

export function canConfirmDeletion({ user, online, target, name, pending }) {
  return canDeleteMarketScript(user, online) && !pending
    && target?.id != null && typeof target.name === 'string'
    && target.name.length > 0 && name === target.name
}

export function deletionError(error) {
  const detail = error?.response?.data?.detail
  const explanation = typeof detail === 'string' ? detail : ''
  if (error?.response?.status === 409) {
    return `无法删除：脚本存在待执行或运行中的任务。不会自动取消任务，请待任务结束后重试。${explanation ? ` 服务端：${explanation}` : ''}`
  }
  return explanation || '从市场删除失败，请检查连接后重试。'
}

// Snapshot the confirmed identity before awaiting; never derive the request from a refreshed row.
export async function deleteConfirmedScript(api, confirmation) {
  if (!canConfirmDeletion(confirmation)) throw new Error('删除权限或确认名称无效')
  const id = confirmation.target.id
  return api.delete(`/api/scripts/${encodeURIComponent(id)}`)
}
