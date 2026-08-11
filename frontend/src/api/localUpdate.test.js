import test from 'node:test'
import assert from 'node:assert/strict'

import { checkUpdate, downloadAndInstallUpdate, loadUpdateStatus } from './localUpdate.js'


function client() {
  const calls = []
  return {
    calls,
    async get(path) {
      calls.push(['get', path])
      return { data: { state: 'verified', version: '0.9.1', current_version: '0.9.0' } }
    },
    async post(path) {
      calls.push(['post', path])
      return {
        data: {
          state: path.endsWith('install') ? 'installing' : 'available',
          current_version: '0.9.0',
        },
      }
    },
  }
}


test('desktop update actions use the local Agent and never the server API', async () => {
  const localApi = client()

  const status = await loadUpdateStatus(localApi)
  assert.equal(status.state, 'verified')
  assert.equal(status.current_version, '0.9.0')
  assert.equal((await checkUpdate(localApi)).state, 'available')
  assert.equal((await downloadAndInstallUpdate(localApi)).state, 'installing')
  assert.deepEqual(localApi.calls, [
    ['get', '/local/update'],
    ['post', '/local/update/check'],
    ['post', '/local/update/install'],
  ])
})
