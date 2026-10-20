import test from 'node:test'
import assert from 'node:assert/strict'

import {
  buildSchedulePayload,
  formatInterval,
  intervalToSeconds,
  isManagedClientMode,
  managedClientPath,
  scheduleFormValues,
  secondsToInterval,
} from './managed.js'

test('managed mode and its route whitelist are explicit', () => {
  assert.equal(isManagedClientMode({ _CLIENT_MODE: 'managed' }), true)
  assert.equal(isManagedClientMode({ _CLIENT_MODE: 'standard' }), false)
  assert.equal(managedClientPath('/scripts'), '/managed')
  assert.equal(managedClientPath('/managed'), '/managed')
})

test('fixed intervals convert between form units and seconds', () => {
  assert.equal(intervalToSeconds(15, 'minute'), 900)
  assert.equal(intervalToSeconds(2, 'hour'), 7200)
  assert.deepEqual(secondsToInterval(172800), { value: 2, unit: 'day' })
  assert.equal(formatInterval(3600), '每 1 小时')
  assert.equal(intervalToSeconds(0, 'day'), null)
})

test('schedule form values and API payload preserve params and nullable environment', () => {
  const values = scheduleFormValues({
    name: '日报', agent_id: 3, script_id: 8, params: '{"scope":"today"}',
    environment_id: null, interval_seconds: 7200, expires_after_seconds: 1800, enabled: false,
  })
  assert.equal(values.interval_value, 2)
  assert.equal(values.interval_unit, 'hour')
  assert.deepEqual(values.params, { scope: 'today' })

  assert.deepEqual(buildSchedulePayload(values), {
    name: '日报', agent_id: 3, script_id: 8, params: { scope: 'today' },
    environment_id: null, interval_seconds: 7200, expires_after_seconds: 1800, enabled: false,
  })
})
