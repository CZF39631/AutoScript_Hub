import test from 'node:test'
import assert from 'node:assert/strict'

import { startConnectionPolling } from './connectionRuntime.js'


test('connection polling runs once immediately and then every 30 seconds', () => {
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
  assert.equal(scheduled.delay, 30000)
  scheduled.callback()
  assert.equal(refreshCount, 2)
  stop()
  assert.equal(cleared, 17)
})
