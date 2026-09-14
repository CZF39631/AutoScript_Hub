import test from 'node:test'
import assert from 'node:assert/strict'
import { makeTrigger, newRequestId, taskError, triggerLabel } from './taskScheduling.js'

const base = { kind: 'daily', timezone: 'Asia/Shanghai', time: '09:30', misfire: 'skip', grace_seconds: 300 }
test('daily trigger carries an explicit timezone without stale once fields', () => {
  assert.deepEqual(makeTrigger({ ...base, start_at: 'bad', weekdays: [1] }), base)
})
test('once requires explicit offset; naive timestamps never use the browser timezone', () => {
  assert.throws(() => makeTrigger({ ...base, kind: 'once', start_at: '2026-09-14T09:30:00' }), /时区/)
  assert.equal(makeTrigger({ ...base, kind: 'once', start_at: '2026-09-14T09:30:00+08:00' }).start_at, '2026-09-14T09:30:00+08:00')
})
test('bad timezones, clock times and empty weekdays are rejected', () => {
  assert.throws(() => makeTrigger({ ...base, timezone: 'not-a-zone' }), /时区/)
  assert.throws(() => makeTrigger({ ...base, timezone: '' }), /时区/)
  assert.throws(() => makeTrigger({ ...base, time: '24:00' }), /时/)
  assert.throws(() => makeTrigger({ ...base, kind: 'weekly', weekdays: [] }), /至少/)
})
test('error renderer never returns a Pydantic detail object to React', () => {
  assert.equal(taskError({ response: { data: { detail: [{ msg: 'invalid UUID' }, { msg: 'missing version' }] } } }), 'invalid UUID；missing version')
  assert.equal(taskError({ response: { data: { detail: { message: 'denied' } } } }), 'denied')
})
test('labels handle malformed legacy records and weekly dates', () => {
  assert.equal(triggerLabel('{invalid'), '规则不可用')
  assert.match(triggerLabel({ ...base, kind: 'weekly', weekdays: [0, 6] }), /每周一、日/)
})
test('manual request identifiers are distinct UUIDv4 values', () => {
  const a = newRequestId(), b = newRequestId()
  assert.match(a, /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/)
  assert.notEqual(a, b)
})
