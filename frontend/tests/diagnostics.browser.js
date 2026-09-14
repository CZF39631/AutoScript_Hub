// Dedicated diagnostics-130 session; all API/Agent traffic mocked before navigation.
async page => {
  await page.goto('about:blank')
  await page.context().unrouteAll({ behavior: 'ignoreErrors' })
  const origin = 'http://127.0.0.1:5327'
  const writes = [], errors = []
  let agent = false, rejectPreview = false
  const check = (ok, reason) => { if (!ok) throw new Error(reason) }
  page.on('pageerror', e => errors.push(e.message))
  await page.context().addInitScript(() => {
    if (location.origin !== 'http://127.0.0.1:5327') return
    localStorage.setItem('token', 'synthetic-only')
    localStorage.setItem('user', JSON.stringify({ id: 1, username: 'synthetic', display_name: '合成诊断测试', role: 'operator' }))
    window._AGENT_API_TOKEN = 'synthetic-only'
  })
  await page.context().route('**/*', async route => {
    const request = route.request(), parts = request.url().match(/^(https?:\/\/[^/]+)(\/[^?]*)/)
    if (!parts) return route.abort()
    const url = { origin: parts[1], pathname: parts[2] }
    const isAgent = /^http:\/\/127\.0\.0\.1:180(80|9[1-9])$/.test(url.origin)
    if (url.origin !== origin && !isAgent) return route.abort()
    if (isAgent && !agent) return route.abort()
    if (url.pathname.startsWith('/api/') || url.pathname.startsWith('/local/')) {
      const headers = { 'Access-Control-Allow-Origin': origin, 'Access-Control-Allow-Headers': '*', 'Access-Control-Allow-Methods': '*' }
      if (request.method() === 'OPTIONS') return route.fulfill({ status: 204, headers })
      let data = [], status = 200
      if (request.method() === 'POST') {
        const body = request.postDataJSON()
        writes.push({ path: url.pathname, body })
        data = { id: 1 }
        if (url.pathname === '/api/issues/preview') {
          data = rejectPreview ? { detail: [{ msg: '合成校验错误', input: 'never-render' }] } : { preview: body, size_bytes: 100 }
          if (rejectPreview) status = 422
        }
      } else if (url.pathname === '/api/health') data = { status: 'ok' }
      else if (url.pathname === '/local/connection') data = { agent_id: 7, pending_sync_count: 0 }
      else if (url.pathname === '/local/diagnostics') data = { client_version: '1.3.0', agent_version: '1.3.0', collection_state: 'collected', application_logs: { agent: '合成 Agent 日志', desktop: '合成桌面日志' } }
      return route.fulfill({ status, headers, contentType: 'application/json', body: JSON.stringify(data) })
    }
    if (isAgent) return route.abort()
    return route.continue()
  })
  await page.goto(origin + '/issues')
  await page.getByRole('button', { name: '上报问题', exact: true }).click()
  await page.getByLabel('问题标题', { exact: true }).fill('无 Agent 报单')
  check(await page.getByRole('button', { name: /在本机采集/ }).isDisabled(), 'browser without Agent must not collect')
  await page.getByRole('button', { name: '发送服务器预览（不创建工单）' }).click()
  await page.getByText('服务器处理后的内容 · 100 字节').waitFor()
  check(!writes.some(w => w.path === '/api/issues'), 'preview persisted issue')
  check(writes[0].body.diagnostics === undefined && writes[0].body.diagnostics_consent === false, 'implicit collection')
  await page.getByRole('button', { name: /取\s*消/ }).click()
  check(!writes.some(w => w.path === '/api/issues'), 'cancel created issue')
  await page.getByRole('button', { name: '上报问题', exact: true }).click()
  await page.getByLabel('问题标题', { exact: true }).fill('校验错误测试')
  rejectPreview = true
  await page.getByRole('button', { name: '发送服务器预览（不创建工单）' }).click()
  await page.getByText('合成校验错误', { exact: true }).waitFor()
  check(!await page.getByText('never-render', { exact: true }).count(), 'validation input echoed')
  await page.getByRole('button', { name: /取\s*消/ }).click()
  agent = true; rejectPreview = false
  await page.reload()
  await page.getByRole('button', { name: '上报问题', exact: true }).click()
  await page.getByRole('button', { name: /在本机采集/ }).waitFor()
  await page.getByRole('button', { name: /在本机采集/ }).click()
  await page.getByText(/已采集（尚未上传）/).waitFor()
  await page.getByLabel('问题标题', { exact: true }).fill('所选日志测试')
  await page.getByRole('checkbox', { name: '附带 Agent 应用日志', exact: true }).check()
  const beforeConsent = writes.length
  await page.getByRole('button', { name: '发送服务器预览（不创建工单）' }).click()
  await page.getByText('请先确认将所选诊断内容发送服务器', { exact: true }).waitFor()
  check(writes.length === beforeConsent, 'uploaded without consent')
  await page.getByRole('checkbox', { name: /我同意将所选诊断/ }).check()
  await page.getByRole('button', { name: '发送服务器预览（不创建工单）' }).click()
  await page.getByText('服务器处理后的内容 · 100 字节').waitFor()
  await page.getByRole('checkbox', { name: /已检查预览/ }).check()
  await page.getByRole('button', { name: '确认提交工单', exact: true }).click()
  await page.getByRole('dialog').waitFor({ state: 'hidden' })
  const created = writes.filter(w => w.path === '/api/issues')
  check(created.length === 1 && created[0].body.diagnostics.application_logs.agent === '合成 Agent 日志', 'selected log missing')
  check(created[0].body.diagnostics.application_logs.desktop === undefined, 'unselected log sent')
  check(errors.length === 0, 'React errors: ' + errors.join(';'))
  console.log('PASS: no-Agent report, preview cancel, structured error, local collection, explicit consent, selected logs, pageerrors=0')
}
