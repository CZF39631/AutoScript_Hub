import test from 'node:test'
import assert from 'node:assert/strict'
import { diagnosticRequest, createDiagnosticPreview, MAX_DIAGNOSTIC_BYTES } from './diagnosticReport.js'

const values = { title: '网页问题' }
const local = { client_version: '1.3.0', agent_version: '1.3.0', collection_state: 'partial', private_config: 'do-not-send', application_logs: { agent: 'agent log', desktop: 'desktop log', other: 'private' } }

test('网页无 Agent 默认只提交文字；日志逐项选择且需要 consent', () => {
  const plain = diagnosticRequest({ values, selection: {}, consent: false })
  assert.equal(plain.diagnostics, undefined)
  assert.equal(plain.diagnostics_consent, false)
  assert.throws(() => diagnosticRequest({ values, local, selection: { agent: true }, consent: false }), /确认/)
  const chosen = diagnosticRequest({ values, local, runId: 3, selection: { agent: true }, consent: true })
  assert.deepEqual(chosen.diagnostics, { application_logs: { agent: 'agent log' } })
  assert.equal(chosen.include_run_summary, false)
  const summary = diagnosticRequest({ values, local, runId: 3, selection: { summary: true }, consent: true })
  assert.equal(summary.diagnostics.private_config, undefined)
  assert.equal(summary.diagnostics.application_logs, undefined)
  assert.equal(summary.include_run_summary, true)
})

test('中文按 UTF-8 字节限界而非字符数', () => {
  assert.throws(() => diagnosticRequest({ values, local: { application_logs: { agent: '中'.repeat(MAX_DIAGNOSTIC_BYTES / 2) } }, selection: { agent: true }, consent: true }), /192 KiB/)
})

test('取消正在进行的服务器预览不会创建工单，迟到结果不可提交', async () => {
  const calls = []
  let resolve
  const flow = createDiagnosticPreview({ post: (url, data) => { calls.push([url, data]); return new Promise(r => { resolve = r }) } })
  const pending = flow.preview({ title: 'preview only' })
  flow.cancel()
  resolve({ data: { preview: {} } })
  assert.equal(await pending, null)
  await assert.rejects(flow.submit(), /重新预览/)
  assert.deepEqual(calls.map(([url]) => url), ['/api/issues/preview'])
})

test('确认后仅发送冻结请求一次，取消已有预览不可提交', async () => {
  const calls = []
  const flow = createDiagnosticPreview({ post: async (url, data) => { calls.push([url, data]); return { data: { preview: data } } } })
  const request = { title: 'original', diagnostics: { application_logs: { agent: 'selected' } } }
  await flow.preview(request)
  request.title = 'changed'
  request.diagnostics.application_logs.agent = 'changed'
  await flow.submit()
  assert.equal(calls[1][0], '/api/issues')
  assert.equal(calls[1][1].title, 'original')
  assert.equal(calls[1][1].diagnostics.application_logs.agent, 'selected')
  await assert.rejects(flow.submit(), /重新预览/)
  await flow.preview(request)
  flow.cancel()
  await assert.rejects(flow.submit(), /重新预览/)
  assert.equal(calls.filter(([url]) => url === '/api/issues').length, 1)
})
