import test from 'node:test'
import assert from 'node:assert/strict'

import { checkUpdate, installUpdate, loadUpdateStatus } from './localUpdate.js'


function client() {
  const calls = []
  return {
    calls,
    async get(path) {
      calls.push(['get', path])
      return { data: { state: 'verified', version: '0.9.1' } }
    },
    async post(path) {
      calls.push(['post', path])
      return { data: { state: path.endsWith('install') ? 'installing' : 'verified' } }
    },
  }
}


test('desktop update actions use the local Agent and never the server API', async () => {
  const localApi = client()

  assert.equal((await loadUpdateStatus(localApi)).state, 'verified')
  assert.equal((await checkUpdate(localApi)).state, 'verified')
  assert.equal((await installUpdate(localApi)).state, 'installing')
  assert.deepEqual(localApi.calls, [
    ['get', '/local/update'],
    ['post', '/local/update/check'],
    ['post', '/local/update/install'],
  ])
})
