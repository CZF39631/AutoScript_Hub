import test from 'node:test'
import assert from 'node:assert/strict'

import {
  buildSchedulePayload,
  buildVisualCron,
  describeCron,
  formatInterval,
  formatSchedule,
  intervalToSeconds,
  isValidCronExpression,
  isManagedClientMode,
  isThumbnailStale,
  managedClientPath,
  scheduleFormValues,
  scheduleStatusCounts,
  secondsToInterval,
  shortMonthSkipDay,
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
    environment_id: null, schedule_type: 'interval', interval_seconds: 7200,
    expires_after_seconds: 1800, enabled: false,
  })
})

test('visual Cron presets create valid five-field expressions and readable summaries', () => {
  assert.equal(buildVisualCron({ cron_preset: 'hourly', cron_minute: 15 }), '15 * * * *')
  assert.equal(buildVisualCron({ cron_preset: 'daily', cron_hour: 9, cron_minute: 5 }), '5 9 * * *')
  assert.equal(buildVisualCron({ cron_preset: 'weekly', cron_hour: 8, cron_minute: 0, cron_weekdays: [5, 1] }), '0 8 * * 1,5')
  assert.equal(buildVisualCron({ cron_preset: 'monthly', cron_hour: 20, cron_minute: 30, cron_monthday: 12 }), '30 20 12 * *')
  assert.equal(describeCron('0 8 * * 1,5'), '每周星期一、星期五 08:00 执行')
  assert.equal(describeCron('30 20 12 * *'), '每月 12 日 20:30 执行')
  assert.equal(isValidCronExpression('0 9 * * 1-5'), true)
  assert.equal(isValidCronExpression('0 9 * *'), false)
})

test('schedule maintenance helpers distinguish enabled state and warn about short months', () => {
  assert.deepEqual(scheduleStatusCounts([
    { id: 1, enabled: true }, { id: 2, enabled: false }, { id: 3, enabled: true },
  ]), { enabled: 2, paused: 1 })
  assert.equal(shortMonthSkipDay({ cron_mode: 'visual', cron_preset: 'monthly', cron_monthday: 29 }), 29)
  assert.equal(shortMonthSkipDay({ cron_mode: 'advanced' }, '0 9 31 * *'), 31)
  assert.equal(shortMonthSkipDay({ cron_mode: 'visual', cron_preset: 'daily', cron_monthday: 31 }), null)
  assert.equal(shortMonthSkipDay({ cron_mode: 'advanced' }, '0 9 * * *'), null)
})

test('Cron schedule payload excludes interval and legacy schedules still format as intervals', () => {
  const payload = buildSchedulePayload({
    name: '工作日报', agent_id: 2, script_id: 4, schedule_type: 'cron', cron_mode: 'visual',
    cron_preset: 'daily', cron_hour: 9, cron_minute: 0, timezone: 'Asia/Shanghai',
    expires_value: 1, expires_unit: 'hour', enabled: true,
  })
  assert.deepEqual(payload, {
    name: '工作日报', agent_id: 2, script_id: 4, params: {}, environment_id: null,
    schedule_type: 'cron', cron_expression: '0 9 * * *', timezone: 'Asia/Shanghai',
    expires_after_seconds: 3600, enabled: true,
  })
  assert.equal(formatSchedule({ interval_seconds: 3600 }), '每 1 小时')
  assert.equal(formatSchedule({ schedule_type: 'cron', cron_expression: '0 9 * * *', timezone: 'Asia/Shanghai' }), '每天 09:00 执行 · Asia/Shanghai')

  const editValues = scheduleFormValues({
    name: '月底盘点', agent_id: 2, script_id: 4, params: '{}', schedule_type: 'cron',
    cron_expression: '30 20 31 * *', timezone: 'Asia/Shanghai', expires_after_seconds: 3600,
  })
  assert.equal(editValues.schedule_type, 'cron')
  assert.equal(editValues.cron_mode, 'advanced')
  assert.equal(buildSchedulePayload(editValues).cron_expression, '30 20 31 * *')
})
