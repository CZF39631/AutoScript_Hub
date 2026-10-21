import test from 'node:test'
import assert from 'node:assert/strict'

import {
  buildSchedulePayload,
  formatInterval,
  intervalToSeconds,
  isManagedClientMode,
  isThumbnailStale,
  managedClientPath,
  scheduleFormValues,
  secondsToInterval,
  shouldRefreshThumbnail,
  thumbnailTimestamp,
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

test('thumbnail timestamps only trigger image refresh when a new capture exists', () => {
  const first = '2026-04-01T08:00:00Z'
  const second = '2026-04-01T08:01:00Z'
  assert.equal(thumbnailTimestamp({ thumbnail_updated_at: first }), first)
  assert.equal(thumbnailTimestamp({}), null)
  assert.equal(shouldRefreshThumbnail(undefined, first), true)
  assert.equal(shouldRefreshThumbnail(first, first), false)
  assert.equal(shouldRefreshThumbnail(first, second), true)
  assert.equal(shouldRefreshThumbnail(first, null), false)
})

test('thumbnail age becomes stale only after two minutes', () => {
  const capturedAt = '2026-04-01T08:00:00Z'
  assert.equal(isThumbnailStale(capturedAt, new Date('2026-04-01T08:02:00Z')), false)
  assert.equal(isThumbnailStale(capturedAt, new Date('2026-04-01T08:02:00.001Z')), true)
  assert.equal(isThumbnailStale('2026-04-01T08:00:00', new Date('2026-04-01T08:02:01Z')), true)
  assert.equal(isThumbnailStale(null, new Date('2026-04-01T09:00:00Z')), false)
  assert.equal(isThumbnailStale('not-a-date', new Date('2026-04-01T09:00:00Z')), false)
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
