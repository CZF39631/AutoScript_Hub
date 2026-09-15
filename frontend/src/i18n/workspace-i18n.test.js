import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import workspace from './locales/workspace.js'

const paths = [
  '../pages/Settings.jsx',
  '../pages/Scripts.jsx',
  '../pages/ScriptDetail.jsx',
  '../components/ParamForm.jsx',
  '../components/DiagnosticSettings.jsx',
  '../components/DiagnosticReport.jsx',
]
const source = path => readFileSync(new URL(path, import.meta.url), 'utf8')
const placeholders = text => [...text.matchAll(/{{\s*(\w+)\s*}}/g)].map(match => match[1]).sort()

test('workspace resources have matching flat keys and interpolation contracts', () => {
  assert.deepEqual(Object.keys(workspace.zh).sort(), Object.keys(workspace.en).sort())
  for (const key of Object.keys(workspace.zh)) {
    assert.ok(key.startsWith('workspace.'), key)
    assert.ok(workspace.zh[key].trim(), key)
    assert.ok(workspace.en[key].trim(), key)
    assert.deepEqual(placeholders(workspace.zh[key]), placeholders(workspace.en[key]), key)
    assert.doesNotMatch(workspace.en[key], /[\u3400-\u9fff]/, key)
  }
})

test('every static workspace key in the six components has both translations', () => {
  for (const path of paths) {
    const text = source(path)
    assert.match(text, /useI18n\(\)/, path)
    assert.doesNotMatch(text, /[\u3400-\u9fff]/, path)
    for (const [, key] of text.matchAll(/['"](workspace\.[\w.-]+)['"]/g)) {
      assert.ok(Object.hasOwn(workspace.zh, key), `${path}: ${key}`)
      assert.ok(Object.hasOwn(workspace.en, key), `${path}: ${key}`)
    }
  }
})

test('script metadata, parameter keys, help and diagnostic payloads stay raw', () => {
  const params = source('../components/ParamForm.jsx')
  assert.match(params, /name=\{p\.key\} label=\{p\.label\}/)
  assert.match(params, /extra=\{p\.help\}/)
  assert.match(params, /p\.help \|\| t\('workspace\.params\.fileHelp'\)/)
  assert.match(params, /label: o, value: o/)
  const detail = source('../pages/ScriptDetail.jsx')
  assert.match(detail, /\{script\.name\}/)
  assert.match(detail, /\{script\.category\}/)
  assert.match(detail, /: v\.changelog/)
  const report = source('../components/DiagnosticReport.jsx')
  assert.match(report, /JSON\.stringify\(selectedLocal, null, 2\)/)
  assert.match(report, /JSON\.stringify\(preview\.preview, null, 2\)/)
})

test('state messages are translated at render time rather than stored in a language', () => {
  assert.match(source('../pages/Settings.jsx'), /t\(updateStateSummary\[updateState\.state\]\)/)
  assert.match(source('../components/DiagnosticReport.jsx'), /agentOnline \? t\(collection\)/)
  assert.match(source('../pages/ScriptDetail.jsx'), /v\.localCached \? t\('workspace\.detail\.cachedVersion'\)/)
  assert.equal(workspace.en['workspace.params.required'], 'Please enter {{name}}')
  assert.equal(workspace.zh['workspace.params.required'], '请填写{{name}}')
})
