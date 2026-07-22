function normalizeLocalScript(script) {
  return { ...script, local_only: true }
}


function toIso(seconds) {
  return seconds == null ? null : new Date(seconds * 1000).toISOString()
}


export function firstResultPath(resultFiles) {
  if (!resultFiles) return null
  let parsed = resultFiles
  if (typeof parsed === 'string') {
    try {
      parsed = JSON.parse(parsed)
    } catch {
      return parsed
    }
  }
  const first = Array.isArray(parsed) ? parsed[0] : parsed
  if (typeof first === 'string') return first
  return first?.path || null
}


export function canOpenResultLocally(run, agentOnline, agentId) {
  if (!agentOnline || !run) return false
  if (run.local_only) return true
  if (run.agent_id == null || agentId == null) return false
  return String(run.agent_id) === String(agentId)
}


export function normalizeLocalRun(run) {
  return {
    ...run,
    id: run.local_run_id,
    local_only: true,
    params: typeof run.params === 'string' ? run.params : JSON.stringify(run.params || {}),
    created_at: toIso(run.started_at),
    started_at: toIso(run.started_at),
    finished_at: toIso(run.finished_at),
  }
}


export async function loadScriptCollections({ online, api, localApi }) {
  if (!online) {
    const response = await localApi.get('/local/scripts')
    return {
      mine: (response.data || []).map(normalizeLocalScript),
      marketplace: [],
    }
  }
  const [mine, marketplace] = await Promise.all([
    api.get('/api/scripts'),
    api.get('/api/scripts/marketplace'),
  ])
  return { mine: mine.data || [], marketplace: marketplace.data || [] }
}


export async function loadRunList({ online, api, localApi, query = '' }) {
  if (!online) {
    const response = await localApi.get('/local/runs')
    return (response.data || []).map(normalizeLocalRun)
  }
  const response = await api.get(`/api/runs${query ? `?${query}` : ''}`)
  return response.data || []
}


export async function loadRunDetail({ id, online, api, localApi }) {
  const localOnly = String(id).startsWith('L') || !online
  if (localOnly) {
    const response = await localApi.get(`/local/runs/${id}`)
    return normalizeLocalRun(response.data)
  }
  const response = await api.get(`/api/runs/${id}`)
  return response.data
}


export async function loadRunLog({ id, localOnly, api, localApi }) {
  if (localOnly || String(id).startsWith('L')) {
    const response = await localApi.get(`/local/runs/${id}/log`)
    return response.data
  }
  const response = await api.get(`/api/runs/${id}/log`)
  return response.data
}
