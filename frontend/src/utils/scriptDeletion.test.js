import test from 'node:test'
import assert from 'node:assert/strict'
import { canDeleteMarketScript, canConfirmDeletion, deleteConfirmedScript, deletionError } from './scriptDeletion.js'

const valid = () => ({ user: { role: 'admin' }, online: true, target: { id: 42, name: '脚本 A' }, name: '脚本 A', pending: false })

test('only an online admin can see or confirm deletion', () => {
  for (const role of ['admin', 'developer', 'operator', undefined]) {
    for (const online of [true, false]) {
      const expected = role === 'admin' && online
      assert.equal(canDeleteMarketScript({ role }, online), expected)
      assert.equal(canConfirmDeletion({ ...valid(), user: { role }, online }), expected)
    }
  }
  assert.equal(canDeleteMarketScript(null, true), false)
})

test('confirmation requires exact name, target and no pending request', () => {
  assert.equal(canConfirmDeletion(valid()), true)
  for (const change of [{ name: '' }, { name: ' 脚本 A' }, { name: '脚本 a' }, { pending: true }, { target: null }, { target: { name: '脚本 A' } }]) {
    assert.equal(Boolean(canConfirmDeletion({ ...valid(), ...change })), false)
  }
})

test('only confirmed target reaches DELETE and invalid confirmations never call API', async () => {
  const calls = []
  const api = { delete: async url => { calls.push(url) } }
  for (const change of [{ online: false }, { user: { role: 'developer' } }, { pending: true }, { name: 'other' }]) {
    await assert.rejects(deleteConfirmedScript(api, { ...valid(), ...change }), /无效/)
  }
  assert.deepEqual(calls, [])
  const confirmation = valid()
  const request = deleteConfirmedScript(api, confirmation)
  confirmation.target.id = 99
  await request
  assert.deepEqual(calls, ['/api/scripts/42'])
})

test('409 reports safety refusal and other server errors are preserved', () => {
  const error = { response: { status: 409, data: { detail: '仍有活动任务' } } }
  assert.match(deletionError(error), /不会自动取消任务/)
  assert.match(deletionError(error), /仍有活动任务/)
  assert.equal(deletionError({ response: { status: 403, data: { detail: '无权限' } } }), '无权限')
  assert.match(deletionError(new Error('network')), /连接/)
  assert.equal(typeof deletionError({ response: { data: { detail: [] } } }), 'string')
})
