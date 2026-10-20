import test from 'node:test'
import assert from 'node:assert/strict'

import { loadManagedPanelData } from './managedLocal.js'

function localClient(routes) {
  return {
    async get(path) {
      const value = routes[path]
      if (value instanceof Error || value === undefined) throw value || new Error(`missing ${path}`)
      return { data: value }
    },
  }
}

test('managed panel uses structured identity and current task from the local Agent', async () => {
  const data = await loadManagedPanelData(localClient({
    '/local/connection': {
      online: true,
      agent_id: 9,
      device_uid: 'device-9',
      machine_name: 'QA-01',
      current_run: { id: 21, status: 'running', script_name: '安全巡检' },
    },
    '/status': { running: true, run_id: 21, version: '1.2.5' },
    '/local/runs': [{ local_run_id: 'L20', status: 'success', started_at: 100 }],
    '/local/runtime': { status: 'ready', version: '3.11.9' },
  }))

  assert.equal(data.source, 'local-agent')
  assert.equal(data.device.machine_name, 'QA-01')
  assert.equal(data.currentRun.script_name, '安全巡检')
  assert.equal(data.recentRuns[0].id, 'L20')
})

test('managed panel supports older Agent run_id responses', async () => {
  const data = await loadManagedPanelData(localClient({
    '/local/connection': { online: true, agent_id: 7 },
    '/status': { running: true, run_id: 'L2', version: '1.2.5' },
    '/local/runs': [{ local_run_id: 'L2', status: 'running', started_at: 100 }],
    '/local/runtime': { status: 'ready', version: '3.11.9' },
  }))

  assert.equal(data.currentRun.id, 'L2')
  assert.equal(data.connection.agent_version, '1.2.5')
  assert.equal(data.runtime.status, 'ready')
})
