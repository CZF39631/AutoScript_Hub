export function groupIds(groups = []) {
  return groups.map(group => group.id).filter(id => Number.isInteger(id))
}

export function defaultGroupIds(groups = []) {
  return groups
    .filter(group => group.is_default && (group.status === undefined || group.status === 'active'))
    .map(group => group.id)
    .filter(id => Number.isInteger(id))
}

export function activeGroupOptions(groups = []) {
  return groups
    .filter(group => group.status === undefined || group.status === 'active')
    .map(group => ({ label: group.name, value: group.id }))
}

export function shouldFallbackToLocal(error) {
  return !error?.response
}

export function parseScriptConfig(raw) {
  if (!raw) return {}
  try {
    const parsed = JSON.parse(raw)
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : {}
  } catch {
    return {}
  }
}
