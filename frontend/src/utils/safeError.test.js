import test from 'node:test'
import assert from 'node:assert/strict'
import { safeError } from './safeError.js'

test('Pydantic errors and malformed objects always become safe text', () => {
  const error = detail => ({ response: { data: { detail } } })
  assert.equal(safeError(error([{ msg: '输入无效', input: 'private' }])), '输入无效')
  assert.equal(safeError(error([null, { msg: {} }])), '输入无效；输入无效')
  assert.equal(safeError(error({ message: '请重试' })), '请重试')
  assert.equal(safeError(error({ message: { secret: 'private' } }), '失败'), '失败')
  assert.equal(safeError(error('权限不足')), '权限不足')
  assert.equal(safeError({ message: {} }, '失败'), '失败')
})
