import test from 'node:test'
import assert from 'node:assert/strict'
import { createIssueLogLoader, formatIssueParams } from './issueDetail.js'

test('historical parameters: malformed, empty, object and JSON scalar inputs', () => {
  assert.deepEqual(formatIssueParams('{invalid'), { text: '{invalid', invalid: true })
  for (const value of [null, undefined, '']) assert.equal(formatIssueParams(value).text, '')
  for (const value of ['{}', '[]', 'null', 'false', '0', '"text"']) {
    assert.deepEqual(formatIssueParams(value), { text: JSON.stringify(JSON.parse(value), null, 2), invalid: false })
  }
  assert.equal(formatIssueParams({ a: 1 }).text, '{\n  "a": 1\n}')
  assert.equal(formatIssueParams('   ').invalid, true)
})

function fixture() {
  const pending = []
  const state = { log: '', loading: false }
  const loader = createIssueLogLoader(() => new Promise((resolve, reject) => pending.push({ resolve, reject })),
    log => { state.log = log }, loading => { state.loading = loading })
  return { loader, pending, state }
}

for (const reject of [false, true]) {
  test(`old ${reject ? 'failure' : 'success'} cannot alter newer loading or log`, async () => {
    const { loader, pending, state } = fixture()
    const first = loader.open({ id: 1, run_id: 1 })
    const second = loader.open({ id: 2, run_id: 2 })
    if (reject) pending[0].reject(new Error('old'))
    else pending[0].resolve({ data: { log: 'old' } })
    await first
    assert.deepEqual(state, { log: '', loading: true })
    pending[1].resolve({ data: { log: 'new' } })
    await second
    assert.deepEqual(state, { log: 'new', loading: false })
  })
}

test('late success after newer success is ignored', async () => {
  const { loader, pending, state } = fixture()
  const first = loader.open({ id: 1, run_id: 1 })
  const second = loader.open({ id: 2, run_id: 2 })
  pending[1].resolve({ data: { log: 'new' } }); await second
  pending[0].resolve({ data: { log: 'old' } }); await first
  assert.deepEqual(state, { log: 'new', loading: false })
})

for (const selection of [null, { id: 3 }]) {
  test(`close/no-run resets and invalidates requests: ${JSON.stringify(selection)}`, async () => {
    const { loader, pending, state } = fixture()
    const first = loader.open({ id: 1, run_id: 1 })
    await loader.open(selection)
    pending[0].reject(new Error('late')); await first
    assert.deepEqual(state, { log: '', loading: false })
  })
}

test('unmount cancellation prevents all updates; current failure and empty log finish loading', async () => {
  const { loader, pending, state } = fixture()
  const first = loader.open({ id: 1, run_id: 1 })
  loader.cancel()
  pending[0].resolve({ data: { log: 'old' } }); await first
  assert.deepEqual(state, { log: '', loading: true })
  const second = loader.open({ id: 2, run_id: 2 })
  pending[1].reject(new Error('current')); await second
  assert.match(state.log, /日志加载失败/)
  assert.equal(state.loading, false)
  const third = loader.open({ id: 3, run_id: 3 })
  pending[2].resolve({ data: { log: '' } }); await third
  assert.deepEqual(state, { log: '(暂无日志)', loading: false })
})
