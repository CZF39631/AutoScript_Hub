import test from 'node:test'
import assert from 'node:assert/strict'

import {
  buildRunQuery, parseRunFilterParams, refreshDelay, runDeviceName,
} from './runHistory.js'

test('run filters round-trip supported managed dimensions', () => {
  const query = buildRunQuery({
    status: 'failed', userId: 2, agentId: 7, scheduleId: 11,
    dispatchType: 'managed_schedule', dateFrom: '2026-01-01T00:00:00Z',
  })
  assert.equal(query.get('agent_id'), '7')
  assert.equal(query.get('schedule_id'), '11')
  assert.equal(query.get('dispatch_type'), 'managed_schedule')
  assert.deepEqual(parseRunFilterParams(query), {
    agentId: 7, scheduleId: 11, dispatchType: 'managed_schedule',
  })
  assert.deepEqual(parseRunFilterParams('agent_id=bad&dispatch_type=unknown'), {
    agentId: undefined, scheduleId: undefined, dispatchType: undefined,
  })
})

test('active polling is fast only while the page is focused', () => {
  assert.equal(refreshDelay({ hasActive: true, isFocused: true }), 5000)
  assert.equal(refreshDelay({ hasActive: false, isFocused: true }), 60000)
  assert.equal(refreshDelay({ hasActive: true, isFocused: false }), 60000)
})

test('device display prefers the executing device and falls back compatibly', () => {
  assert.equal(runDeviceName({ agent_name: '工作站', target_agent_name: '目标机' }), '工作站')
  assert.equal(runDeviceName({ target_agent_name: '目标机', target_agent_id: 8 }), '目标机')
  assert.equal(runDeviceName({ target_agent_id: 8 }), '设备 #8')
})
