import test from 'node:test'
import assert from 'node:assert/strict'

import { loadManagedThumbnail } from './managedThumbnails.js'

test('managed thumbnail makes no initial request and loads only the clicked device', async () => {
  const requests = []
  const revoked = []
  const http = {
    async get(path, options) {
      requests.push({ path, options })
      return { data: { device: 12 } }
    },
  }
  const urlApi = {
    createObjectURL: blob => `blob:device-${blob.device}`,
    revokeObjectURL: url => revoked.push(url),
  }

  assert.deepEqual(requests, [])
  const loaded = await loadManagedThumbnail(http, 12, { urlApi })
  assert.equal(loaded.url, 'blob:device-12')
  assert.deepEqual(requests.map(item => item.path), [
    '/api/admin/managed-agents/12/thumbnail',
  ])

  loaded.release()
  loaded.release()
  assert.deepEqual(revoked, ['blob:device-12'])
})
