import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import execution from './locales/execution.js'
import { makeTrigger, triggerLabel, taskError, taskStates } from '../utils/taskScheduling.js'

const interpolate = language => (key, values = {}) => {
  assert.ok(Object.hasOwn(execution[language], key), `Missing ${language} key: ${key}`)
  return execution[language][key].replace(/\{\{(\w+)\}\}/g, (_, name) => String(values[name] ?? ''))
}

test('execution locales have matching flat keys and interpolation variables', () => {
  assert.deepEqual(Object.keys(execution.zh).sort(), Object.keys(execution.en).sort())
  const variables = value => [...value.matchAll(/\{\{(\w+)\}\}/g)].map(match => match[1]).sort()
  for (const [key, value] of Object.entries(execution.zh)) {
    assert.ok(key.startsWith('execution.'))
    assert.equal(typeof value, 'string')
    assert.equal(typeof execution.en[key], 'string')
    assert.ok(value.length && execution.en[key].length)
    assert.deepEqual(variables(value), variables(execution.en[key]), key)
  }
})

test('literal page keys and dynamic state keys exist in both languages', () => {
  for (const name of ['Tasks', 'Runs', 'RunDetail']) {
    const source = readFileSync(new URL(`../pages/${name}.jsx`, import.meta.url), 'utf8')
    for (const [, key] of source.matchAll(/['"](execution\.[\w.]+)['"]/g)) {
      for (const language of ['zh', 'en']) assert.ok(Object.hasOwn(execution[language], key), `${name}: ${key}`)
    }
    assert.doesNotMatch(source, /key=\{(?:language|i18n\.language)\}/)
  }
  for (const [key] of Object.values(taskStates)) for (const language of ['zh', 'en']) interpolate(language)(key)
  for (const state of ['pending', 'running', 'success', 'failed', 'cancelled', 'queued', 'claimed', 'preparing', 'cancel_requested', 'unknown', 'skipped']) {
    for (const language of ['zh', 'en']) interpolate(language)(`execution.runState.${state}`)
  }
})

test('schedule translations preserve time zone, offsets, weekday numbering and payload', () => {
  const values = { kind: 'weekly', timezone: 'Asia/Shanghai', misfire: 'run_once', grace_seconds: 300, weekdays: [0, 6], time: '09:30' }
  assert.deepEqual(makeTrigger(values, interpolate('zh')), makeTrigger(values, interpolate('en')))
  assert.equal(triggerLabel(values, interpolate('en')), 'Weekly on Mon, Sun 09:30 (Asia/Shanghai)')
  assert.equal(triggerLabel(values), '每周一、日 09:30 (Asia/Shanghai)')
  const once = { ...values, kind: 'once', start_at: '2026-09-14T09:00:00+08:00' }
  assert.equal(makeTrigger(once, interpolate('en')).start_at, once.start_at)
  assert.throws(() => makeTrigger({ ...once, start_at: '2026-09-14T09:00:00' }, interpolate('en')), /time zone/)
})

test('known client errors translate but server and user content remain verbatim', () => {
  let validation
  try { makeTrigger({ kind: 'manual', timezone: '' }) } catch (error) { validation = error }
  assert.equal(taskError(validation, interpolate('en')), 'Enter a time zone')
  assert.equal(taskError({ response: { data: { detail: '用户提供的错误 / server error' } } }, interpolate('en')), '用户提供的错误 / server error')
  assert.equal(taskError({ response: { data: { detail: [{ msg: '原始信息' }, {}] } } }, interpolate('en')), '原始信息; Invalid input')
  assert.equal(taskError({}, interpolate('en')), 'Operation failed. Refresh and try again.')
})
