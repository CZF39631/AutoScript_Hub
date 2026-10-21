import test from 'node:test'
import assert from 'node:assert/strict'

import {
  agentImpactCounts,
  batchResultSummary,
  buildSchedulePayload,
  buildVisualCron,
  canConfirmAgentImpact,
  createManagedBatchSelection,
  describeCron,
  dispatchResourceState,
  formatInterval,
  formatSchedule,
  intervalToSeconds,
  isValidCronExpression,
  isManagedBatchTerminal,
  isManagedClientMode,
  loadManagedBatchRecovery,
  isThumbnailStale,
  MANAGED_FIRST_CONNECTION_GUIDE,
  managedBatchLimit,
  managedBatchLimitError,
  managedBatchProgress,
  managedListSearchParams,
  managedPageSelectionState,
  managedClientPath,
  parseManagedListSearch,
  scheduleFormValues,
  scheduleStatusCounts,
  saveManagedBatchRecovery,
  secondsToInterval,
  shouldResumeManagedBatch,
  shortMonthSkipDay,
  shouldRefreshThumbnail,
  thumbnailTimestamp,
} from './managed.js'

test('managed scale filters round-trip through the URL with safe defaults', () => {
  const parsed = parseManagedListSearch('query=%E4%B8%8A%E6%B5%B7&status=online&run_status=running&group_id=8&sort=name&page=3')
  assert.deepEqual(parsed, {
    query: '上海', status: 'online', runStatus: 'running', groupId: 8,
    sort: 'name', page: 3, pageSize: 24,
  })
  assert.equal(managedListSearchParams(parsed).toString(), 'query=%E4%B8%8A%E6%B5%B7&status=online&run_status=running&group_id=8&sort=name&page=3')
  assert.deepEqual(parseManagedListSearch('status=broken&sort=unknown&page=-3'), {
    query: '', status: '', runStatus: '', groupId: null,
    sort: '-last_heartbeat', page: 1, pageSize: 24,
  })
})

test('page and all-filtered selection keep their semantics explicit', () => {
  assert.deepEqual(managedPageSelectionState([1, 2, 3], [1, 3]), { checked: false, indeterminate: true })
  assert.deepEqual(managedPageSelectionState([1, 2, 3], [], true), { checked: true, indeterminate: false })
  assert.deepEqual(createManagedBatchSelection({ selectedIds: [3, 3, 5] }), {
    mode: 'explicit', agent_ids: [3, 5],
  })
  assert.deepEqual(createManagedBatchSelection({
    allMatching: true,
    selectedIds: [99],
    filters: { query: '华东', status: 'online', runStatus: 'idle', groupId: 2, sort: 'name' },
  }), {
    mode: 'all', agent_ids: [],
    filters: { query: '华东', status: 'online', run_status: 'idle', group_id: 2, sort: 'name' },
  })
  assert.equal(batchResultSummary({ success: 8, failed: 2, skipped: 1 }), '8 成功 · 2 失败 · 1 跳过')
  assert.equal(managedBatchLimit('dispatch_run'), 50)
  assert.equal(managedBatchLimit('pause_agents'), 200)
  assert.equal(managedBatchLimitError('dispatch_run', 51), '当前选择 51 台，超过此操作单批上限 50 台，请缩小筛选范围或分批处理。')
  assert.equal(managedBatchLimitError('pause_agents', 200), '')
})

test('batch recovery distinguishes progress, resumable and terminal states', () => {
  assert.deepEqual(managedBatchProgress({ total: 5, pending: 2, success: 2, failed: 1, skipped: 0 }), {
    pending: 2, completed: 3, total: 5,
  })
  assert.equal(isManagedBatchTerminal({ status: 'processing' }), false)
  assert.equal(isManagedBatchTerminal({ status: 'stale' }), false)
  assert.equal(isManagedBatchTerminal({ status: 'completed' }), true)
  assert.equal(isManagedBatchTerminal({ status: 'failed' }), true)
  assert.equal(shouldResumeManagedBatch({ status: 'stale' }), true)
  assert.equal(shouldResumeManagedBatch({ status: 'processing', recoverable: true }), true)
  assert.equal(shouldResumeManagedBatch({ status: 'retryable' }), true)
  assert.equal(shouldResumeManagedBatch({ status: 'processing' }, { elapsedSincePost: 31999 }), false)
  assert.equal(shouldResumeManagedBatch({ status: 'processing' }, { elapsedSincePost: 32000 }), true)
  assert.equal(shouldResumeManagedBatch({ status: 'processing' }, { elapsedSincePost: 64000, recoveryAttempted: true }), false)
})

test('batch recovery storage preserves the original key and payload across refreshes', () => {
  const values = new Map()
  const storage = {
    getItem: key => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value),
    removeItem: key => values.delete(key),
  }
  const payload = { operation: 'pause_agents', selection: { mode: 'explicit', agent_ids: [7] } }
  const saved = saveManagedBatchRecovery({
    batchId: 91, key: 'stable-key-0001', payload,
    result: { batch_id: 91, status: 'processing', pending: 1 },
    startedAt: 100, lastPostAt: 200, pollCount: 3, monitorState: 'monitoring', notice: '正在处理',
  }, storage)
  assert.equal(saved.key, 'stable-key-0001')
  assert.deepEqual(loadManagedBatchRecovery(storage), saved)
  assert.equal(loadManagedBatchRecovery({ getItem: () => '{bad json' }), null)
})

test('managed mode and its route whitelist are explicit', () => {
  assert.equal(isManagedClientMode({ _CLIENT_MODE: 'managed' }), true)
  assert.equal(isManagedClientMode({ _CLIENT_MODE: 'standard' }), false)
  assert.equal(managedClientPath('/scripts'), '/managed')
  assert.equal(managedClientPath('/managed'), '/managed')
})

test('first-device onboarding exposes only existing in-app recovery routes', () => {
  assert.equal(MANAGED_FIRST_CONNECTION_GUIDE.steps.length, 3)
  assert.match(MANAGED_FIRST_CONNECTION_GUIDE.minimumVersion, /最低要求/)
  assert.deepEqual(
    MANAGED_FIRST_CONNECTION_GUIDE.links.map(item => item.route),
    ['/settings', '/updates'],
  )
  assert.equal(MANAGED_FIRST_CONNECTION_GUIDE.troubleshooting.length >= 2, true)
})

test('dispatch resources distinguish loading, ready, empty and recoverable error states', () => {
  assert.equal(dispatchResourceState({ loading: true, error: 'ignored', value: [] }), 'loading')
  assert.equal(dispatchResourceState({ error: 'network failed', value: [] }), 'error')
  assert.equal(dispatchResourceState({ value: [] }), 'empty')
  assert.equal(dispatchResourceState({ value: null }), 'empty')
  assert.equal(dispatchResourceState({ value: [{ id: 1 }] }), 'ready')
  assert.equal(dispatchResourceState({ value: { id: 1 } }), 'ready')
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

test('agent lifecycle confirmation exposes every affected count and requires an exact delete name', () => {
  assert.deepEqual(agentImpactCounts({
    pending_count: 2,
    running_count: 1,
    enabled_schedule_count: 3,
    paused_schedule_count: 4,
  }), [
    { key: 'pending', label: '待执行任务', value: 2 },
    { key: 'running', label: '运行中任务', value: 1 },
    { key: 'enabled-schedules', label: '启用计划', value: 3 },
    { key: 'paused-schedules', label: '已暂停计划', value: 4 },
  ])
  assert.equal(canConfirmAgentImpact('disable', '', '工作站 A'), true)
  assert.equal(canConfirmAgentImpact('delete', '工作站 A', '工作站 A'), true)
  assert.equal(canConfirmAgentImpact('delete', '工作站 a', '工作站 A'), false)
  assert.equal(canConfirmAgentImpact('delete', ' 工作站 A ', '工作站 A'), false)
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
