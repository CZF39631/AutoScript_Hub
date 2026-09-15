import test from 'node:test'
import assert from 'node:assert/strict'
import { readdirSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { createInstance } from 'i18next'
import { dictionaries, resources } from './resources.js'
import { DEFAULT_LANGUAGE, LANGUAGE_STORAGE_KEY, normalizeLanguage, readLanguage, saveLanguage } from './preference.js'
import { describeLoginError, renderLoginError } from './loginError.js'

const canonicalKey = key => key.replace(/_(zero|one|two|few|many|other)$/, '')
const variables = text => [...text.matchAll(/\{\{\s*([\w.]+)\s*\}\}/g)].map(match => match[1]).sort()

function translator(language) {
  const instance = createInstance()
  instance.init({ resources, lng: language, fallbackLng: 'zh-CN', keySeparator: false, initAsync: false, interpolation: { escapeValue: false } })
  return instance
}

test('language preference defaults to Chinese and normalizes supported English locales', () => {
  assert.equal(readLanguage({ getItem: () => null }), DEFAULT_LANGUAGE)
  for (const value of [null, undefined, {}, 'fr-FR', 'zh-TW']) assert.equal(normalizeLanguage(value), 'zh-CN')
  for (const value of ['en', 'en-US', 'en-GB', 'EN-us']) assert.equal(normalizeLanguage(value), 'en-US')
  const values = new Map([['token', 'untouched']])
  const storage = { getItem: key => values.get(key), setItem: (key, value) => values.set(key, value) }
  assert.equal(saveLanguage('en', storage), 'en-US')
  assert.equal(values.get(LANGUAGE_STORAGE_KEY), 'en-US')
  assert.equal(readLanguage(storage), 'en-US')
  assert.equal(values.get('token'), 'untouched')
})

test('blocked storage does not prevent language selection', () => {
  const blocked = { getItem() { throw new Error('blocked') }, setItem() { throw new Error('quota') } }
  assert.equal(readLanguage(blocked), 'zh-CN')
  assert.equal(saveLanguage('en-US', blocked), 'en-US')
})

test('all dictionaries have matching keys and interpolation variables', () => {
  const seen = new Set()
  for (const [name, dictionary] of Object.entries(dictionaries)) {
    const zhKeys = new Set(Object.keys(dictionary.zh).map(canonicalKey))
    const enKeys = new Set(Object.keys(dictionary.en).map(canonicalKey))
    assert.deepEqual([...zhKeys].sort(), [...enKeys].sort(), name)
    for (const key of zhKeys) {
      assert.ok(!seen.has(key), `duplicate key across dictionaries: ${key}`)
      seen.add(key)
    }
    for (const [key, text] of Object.entries(dictionary.en)) {
      assert.equal(typeof text, 'string', key)
      assert.ok(text.trim(), key)
      const chinese = dictionary.zh[key] ?? dictionary.zh[canonicalKey(key)]
      assert.equal(typeof chinese, 'string', key)
      assert.ok(chinese.trim(), key)
      assert.deepEqual(variables(text), variables(chinese), `interpolation mismatch: ${key}`)
    }
  }
})

test('literal translation calls resolve in both languages', () => {
  const root = fileURLToPath(new URL('../', import.meta.url))
  const visit = directory => readdirSync(directory, { withFileTypes: true }).flatMap(entry => {
    const path = join(directory, entry.name)
    if (entry.isDirectory()) return entry.name === 'i18n' ? [] : visit(path)
    return /\.(jsx|js)$/.test(entry.name) && !entry.name.includes('.test.') ? [path] : []
  })
  const zh = translator('zh-CN'), en = translator('en-US')
  let count = 0
  for (const path of visit(root)) {
    const source = readFileSync(path, 'utf8')
    for (const match of source.matchAll(/\bt\(\s*['"]((?:shell|execution|workspace|management)\.[^'"]+)['"]/g)) {
      const key = match[1]
      assert.ok(zh.exists(key, { count: 2 }), `${path}: missing Chinese ${key}`)
      assert.ok(en.exists(key, { count: 2, fallbackLng: false }), `${path}: missing English ${key}`)
      count++
    }
  }
  assert.ok(count > 30, 'translation call coverage unexpectedly empty')
})

test('language changes, plural forms, and missing keys are deterministic', async () => {
  const instance = translator('zh-CN')
  assert.equal(instance.t('shell.login'), '登录')
  await instance.changeLanguage('en-US')
  assert.equal(instance.t('shell.login'), 'Sign in')
  assert.equal(instance.t('shell.pendingSync', { count: 1 }), ' (1 record pending sync)')
  assert.equal(instance.t('shell.pendingSync', { count: 2 }), ' (2 records pending sync)')
  instance.addResource('zh-CN', 'translation', 'test.chineseFallback', '中文回退')
  assert.equal(instance.t('test.chineseFallback'), '中文回退')
  assert.equal(instance.t('test.unknown'), 'test.unknown')
})

test('authentication errors translate without changing unknown details or rendering objects', () => {
  const en = translator('en-US'), zh = translator('zh-CN')
  const described = describeLoginError({ response: { status: 401, data: { detail: '用户名或密码错误' } } })
  assert.equal(renderLoginError(described, en.t.bind(en)), 'Incorrect username or password')
  assert.equal(renderLoginError(described, zh.t.bind(zh)), '用户名或密码错误')
  assert.equal(renderLoginError(describeLoginError({ response: { status: 422, data: { detail: [{ input: 'do not render' }] } } }), en.t.bind(en)), 'Sign-in failed (HTTP 422)')
  assert.equal(renderLoginError(describeLoginError({ response: { status: 400, data: { detail: 'External provider detail' } } }), en.t.bind(en)), 'External provider detail')
  assert.equal(renderLoginError(describeLoginError(new Error('offline')), en.t.bind(en)), 'Cannot connect to the server. Check that the service is running.')
})
