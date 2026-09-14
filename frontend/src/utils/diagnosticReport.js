const metadataKeys = ['client_version', 'agent_version', 'agent_id', 'online', 'system', 'machine', 'python_version', 'collection_state']
export const MAX_DIAGNOSTIC_BYTES = 192 * 1024

export function diagnosticRequest({ values, runId, local, selection, consent }) {
  const diagnostics = {}
  if (selection.summary && local) {
    for (const key of metadataKeys) if (local[key] !== undefined) diagnostics[key] = local[key]
  }
  const application_logs = {}
  for (const kind of ['agent', 'desktop']) {
    if (selection[kind] && typeof local?.application_logs?.[kind] === 'string') application_logs[kind] = local.application_logs[kind]
  }
  if (Object.keys(application_logs).length) diagnostics.application_logs = application_logs
  const attached = !!(selection.summary || selection.runLog || Object.keys(diagnostics).length)
  if (attached && !consent) throw new Error('请先确认将所选诊断内容发送服务器')
  const request = { title: values.title, description: values.description || '', diagnostics_consent: attached && consent, include_run_log: !!selection.runLog, include_run_summary: !!(runId && selection.summary) }
  if (runId) request.run_id = Number(runId)
  if (Object.keys(diagnostics).length) request.diagnostics = diagnostics
  if (new TextEncoder().encode(JSON.stringify(request)).length > MAX_DIAGNOSTIC_BYTES) throw new Error('所选内容超过 192 KiB，请减少日志')
  return request
}

// Cancel invalidates pending preview; no creation request is sent by preview itself.
export function createDiagnosticPreview(api) {
  let generation = 0
  let approved = null
  return {
    cancel() { generation++; approved = null },
    async preview(request) {
      const current = ++generation
      approved = null
      const frozen = JSON.parse(JSON.stringify(request))
      const result = await api.post('/api/issues/preview', frozen)
      if (current !== generation) return null
      approved = frozen
      return result.data
    },
    async submit() {
      if (!approved) throw new Error('请重新预览并确认内容')
      const request = approved
      approved = null
      return api.post('/api/issues', request)
    },
  }
}
