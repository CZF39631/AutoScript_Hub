import test from 'node:test'
import assert from 'node:assert/strict'

import { formatServerTime } from './dateTime.js'

test('naive server timestamps are treated as UTC and shown in UTC+8', () => {
  assert.equal(formatServerTime('2025-01-02T12:34:56'), '2025-01-02 20:34:56')
  assert.equal(formatServerTime('2025-01-02T20:30:00'), '2025-01-03 04:30:00')
})

test('explicit timezones are not shifted twice', () => {
  assert.equal(formatServerTime('2025-01-02T12:34:56Z'), '2025-01-02 20:34:56')
  assert.equal(formatServerTime('2025-01-02T20:34:56+08:00'), '2025-01-02 20:34:56')
})

test('empty and invalid values use a safe placeholder', () => {
  assert.equal(formatServerTime(null), '-')
  assert.equal(formatServerTime(''), '-')
  assert.equal(formatServerTime('not-a-time'), '-')
})
