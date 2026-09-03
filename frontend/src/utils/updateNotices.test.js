import test from 'node:test'
import assert from 'node:assert/strict'
import {
  dismissUpdateNotice,
  importantUpdatesHidden,
  setImportantUpdatesHidden,
  shouldShowUpdateNotice,
} from './updateNotices.js'

function memoryStorage() {
  const values = new Map()
  return {
    getItem: key => values.has(key) ? values.get(key) : null,
    setItem: (key, value) => values.set(key, value),
  }
}

const importantRelease = { id: 'release-a', important: true }

test('important update popup is enabled by default and appears only once', () => {
  const storage = memoryStorage()

  assert.equal(importantUpdatesHidden(storage), false)
  assert.equal(shouldShowUpdateNotice({ release: importantRelease, version: '1.2.0', storage }), true)
  assert.equal(dismissUpdateNotice('release-a', '1.2.0', storage), true)
  assert.equal(shouldShowUpdateNotice({ release: importantRelease, version: '1.2.0', storage }), false)
  assert.equal(shouldShowUpdateNotice({ release: importantRelease, version: '1.2.1', storage }), true)
})

test('default-hide preference suppresses all automatic important update popups', () => {
  const storage = memoryStorage()

  assert.equal(setImportantUpdatesHidden(true, storage), true)
  assert.equal(importantUpdatesHidden(storage), true)
  assert.equal(shouldShowUpdateNotice({ release: importantRelease, version: '1.2.0', storage }), false)
})

test('ordinary updates never trigger the first-run popup', () => {
  const storage = memoryStorage()
  assert.equal(shouldShowUpdateNotice({
    release: { id: 'release-b', important: false },
    version: '1.2.0',
    storage,
  }), false)
})
