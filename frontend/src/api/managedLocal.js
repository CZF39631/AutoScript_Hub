import { normalizeLocalRun } from './offlineData.js'

function normalizedRuns(items) {
  return (items || []).map(run => run.local_run_id ? normalizeLocalRun(run) : run)
}

/**
 * Assemble the managed panel from the established loopback API. New Agents expose
 * identity/current_run on connection or status; older versions still work via
 * run_id and the local history endpoint.
 */
export async function loadManagedPanelData(localApi) {
  const [connectionResult, statusResult, runsResult, runtimeResult] = await Promise.allSettled([
    localApi.get('/local/connection'),
    localApi.get('/status'),
    localApi.get('/local/runs'),
    localApi.get('/local/runtime'),
  ])

  if (connectionResult.status === 'rejected' && statusResult.status === 'rejected') {
    throw connectionResult.reason || statusResult.reason || new Error('本地 Agent 不可用')
  }

  const connection = connectionResult.status === 'fulfilled' ? connectionResult.value.data || {} : {}
  const status = statusResult.status === 'fulfilled' ? statusResult.value.data || {} : {}
  const recentRuns = normalizedRuns(runsResult.status === 'fulfilled' ? runsResult.value.data : [])
  const activeId = status.run_id == null ? null : String(status.run_id)
  const legacyActiveRun = activeId
    ? recentRuns.find(run => String(run.id ?? run.local_run_id) === activeId)
    : null
  const currentRun = connection.current_run || status.current_run || legacyActiveRun
    || (status.running ? { id: status.run_id, status: 'running' } : null)

  return {
    connection: { ...status, ...connection, agent_version: connection.agent_version || status.version },
    device: {
      device_uid: connection.device_uid || status.device_uid,
      machine_name: connection.machine_name || status.machine_name,
      client_mode: connection.client_mode || status.client_mode,
    },
    currentRun,
    recentRuns,
    paused: Boolean(connection.paused || status.paused || connection.enabled === false),
    runtime: runtimeResult.status === 'fulfilled' ? runtimeResult.value.data : null,
    source: 'local-agent',
  }
}
