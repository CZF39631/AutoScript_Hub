import test from 'node:test'
import assert from 'node:assert/strict'
import { browserOptions, loadLocalBrowsers, normalizeBrowsers } from './localBrowsers.js'

const browser = { name: 'Chrome', path: 'C:\\Browser\\chrome.exe' }

test('calls the local detection endpoint, shares in-flight work and refreshes afterward', async () => {
  const calls = []
  const api = { get: async path => { calls.push(path); return { data: [browser] } } }
  const first = loadLocalBrowsers(api)
  assert.equal(first, loadLocalBrowsers(api))
  assert.deepEqual(await first, [browser])
  await loadLocalBrowsers(api)
  assert.deepEqual(calls, ['/detect-browsers', '/detect-browsers'])
})

test('filters bad rows, deduplicates Windows paths and keeps original spelling', () => {
  assert.deepEqual(normalizeBrowsers([
    null, {}, { name: 1, path: 'x' }, { name: 'X', path: ' ' },
    { name: '', path: 'x' }, browser,
    { name: 'Duplicate', path: 'c:/browser/CHROME.exe' },
  ]), [browser])
  assert.deepEqual(normalizeBrowsers([]), [])
  for (const value of [null, undefined, {}, 'invalid']) {
    assert.throws(() => normalizeBrowsers(value), /格式/)
  }
})

test('failure can retry without caching a rejected request', async () => {
  let attempts = 0
  const api = { get: async () => {
    attempts += 1
    if (attempts === 1) throw new Error('offline')
    return { data: [] }
  } }
  await assert.rejects(loadLocalBrowsers(api), /offline/)
  assert.deepEqual(await loadLocalBrowsers(api), [])
})

test('different local clients do not share pending responses', async () => {
  let finish
  const oldApi = { get: () => new Promise(resolve => { finish = resolve }) }
  const newApi = { get: async () => ({ data: [] }) }
  const oldRequest = loadLocalBrowsers(oldApi)
  assert.deepEqual(await loadLocalBrowsers(newApi), [])
  finish({ data: [browser] })
  assert.deepEqual(await oldRequest, [browser])
})

test('legacy/manual value stays selectable even with empty or different detection results', () => {
  const legacy = 'D:\\Portable\\old.exe'
  const options = browserOptions([browser], legacy)
  assert.equal(options[0].value, legacy)
  assert.equal(options[0].path, legacy)
  assert.equal(browserOptions([], legacy)[0].value, legacy)
  assert.equal(browserOptions([browser], browser.path).length, 1)
  assert.deepEqual(browserOptions([], ''), [])
  assert.deepEqual(browserOptions([], undefined), [])
  assert.deepEqual(browser, { name: 'Chrome', path: 'C:\\Browser\\chrome.exe' })
})
