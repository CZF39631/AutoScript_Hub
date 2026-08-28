import assert from 'node:assert/strict'
import test from 'node:test'

const removed = []
globalThis.localStorage = {
  getItem: () => null,
  setItem: () => {},
  removeItem: (key) => removed.push(key),
}
globalThis.window = { location: { href: '/current' } }

const { default: api } = await import('./client.js')

function rejectWith401(config) {
  return Promise.reject({
    config,
    response: { status: 401, data: { detail: '用户名或密码错误' } },
  })
}

test('登录失败保留当前页面以显示错误提示', async () => {
  removed.length = 0
  window.location.href = '/current'
  api.defaults.adapter = rejectWith401

  await assert.rejects(api.post('/api/auth/login', { username: 'x', password: 'bad' }))

  assert.equal(window.location.href, '/current')
  assert.deepEqual(removed, [])
})

test('其他接口返回 401 时仍清理登录状态并跳转', async () => {
  removed.length = 0
  window.location.href = '/current'
  api.defaults.adapter = rejectWith401

  await assert.rejects(api.get('/api/scripts'))

  assert.equal(window.location.href, '/login')
  assert.deepEqual(removed, ['token', 'user'])
})
