import test from 'node:test'
import assert from 'node:assert/strict'
import { activeGroupOptions, defaultGroupIds, groupIds, parseScriptConfig, shouldFallbackToLocal } from './groups.js'

test('groupIds extracts valid integer ids', () => {
  assert.deepEqual(groupIds([{ id: 2 }, { id: 5 }, { id: '7' }]), [2, 5])
})

test('defaultGroupIds only returns active defaults', () => {
  assert.deepEqual(defaultGroupIds([
    { id: 1, is_default: true, status: 'active' },
    { id: 2, is_default: true, status: 'disabled' },
  ]), [1])
})

test('activeGroupOptions excludes disabled groups', () => {
  assert.deepEqual(activeGroupOptions([
    { id: 1, name: '默认组', status: 'active' },
    { id: 2, name: '停用组', status: 'disabled' },
  ]), [{ label: '默认组', value: 1 }])
})

test('parseScriptConfig safely handles invalid persisted JSON', () => {
  assert.deepEqual(parseScriptConfig('{"params":[]}'), { params: [] })
  assert.deepEqual(parseScriptConfig('{invalid'), {})
  assert.deepEqual(parseScriptConfig('[]'), {})
})

test('HTTP errors never fall back while network errors do', () => {
  assert.equal(shouldFallbackToLocal({ response: { status: 401 } }), false)
  assert.equal(shouldFallbackToLocal({ response: { status: 403 } }), false)
  assert.equal(shouldFallbackToLocal({ response: { status: 404 } }), false)
  assert.equal(shouldFallbackToLocal(new Error('Network Error')), true)
})
