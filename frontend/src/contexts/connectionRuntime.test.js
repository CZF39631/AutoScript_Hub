import test from 'node:test'
import assert from 'node:assert/strict'

import { AGENT_URLS, discoverAgent, startConnectionPolling } from './connectionRuntime.js'


test('agent discovery falls back when the default port is unavailable', async () => {
  const attempts = []
  const api = {
    defaults: {},
    async get(url) {
      attempts.push(url)
      if (url.includes(':18080/')) throw new Error('port unavailable')
      return { data: { agent_id: 'agent-1' } }
    },
  }

  const response = await discoverAgent(api)

  assert.equal(response.data.agent_id, 'agent-1')
  assert.deepEqual(attempts, [
    `${AGENT_URLS[0]}/local/connection`,
    `${AGENT_URLS[1]}/local/connection`,
  ])
  assert.equal(api.defaults.baseURL, AGENT_URLS[1])
})


test('connection polling runs once immediately and then every 5 seconds', () => {
  let refreshCount = 0
  let scheduled = null
  let cleared = null

  const stop = startConnectionPolling(
    () => { refreshCount += 1 },
    {
      setIntervalFn(callback, delay) {
        scheduled = { callback, delay, id: 17 }
        return 17
      },
      clearIntervalFn(id) {
        cleared = id
      },
    },
  )

  assert.equal(refreshCount, 1)
  assert.equal(scheduled.delay, 5000)
  scheduled.callback()
  assert.equal(refreshCount, 2)
  stop()
  assert.equal(cleared, 17)
})
