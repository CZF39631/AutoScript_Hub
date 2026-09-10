// Run with playwright-cli -s=<local session> run-code --filename=<this file>.
// Requires the local Vite dev server on 5183. All APIs and external requests are mocked/blocked.
async page => {
  const origin = 'http://127.0.0.1:5183'
  const errors = []
  page.on('pageerror', e => errors.push(e.message))
  let scenario = 'race'
  const issue = (id, extra = {}) => ({ id, title: '合成工单' + id, username: 'synthetic', status: 'open', created_at: '2026-01-01', run_id: id, run_params: '{}', ...extra })
  await page.context().route('**/*', async route => {
    const raw = route.request().url()
    if (!raw.startsWith(origin + '/')) return route.abort()
    const path = raw.slice(origin.length).split('?')[0]
    if (path.startsWith('/api/') || path.startsWith('/local/')) {
      let data = []
      if (path === '/api/issues') data = [issue(1), issue(2), issue(3, { run_id: null, run_params: '{invalid historical json' })]
      if (path.endsWith('/log')) {
        const id = path.split('/')[3]
        await page.waitForTimeout(id === '1' ? 1500 : scenario === 'loading' ? 2400 : 50)
        if (id === '1' && scenario === 'loading') return route.fulfill({ status: 500, contentType: 'application/json', body: '{}' })
        data = { log: 'SYNTHETIC_LOG_' + id }
      }
      if (path === '/api/health') data = { status: 'ok' }
      if (path === '/local/connection') data = { agent_id: 'synthetic', pending_sync_count: 0 }
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(data) })
    }
    return route.continue()
  })
  await page.goto(origin)
  await page.evaluate(() => {
    localStorage.setItem('token', 'synthetic-only')
    localStorage.setItem('user', JSON.stringify({ id: 1, username: 'synthetic', role: 'user' }))
  })
  await page.goto(origin + '/issues')
  const details = page.getByRole('button', { name: '详情' })
  const dialog = page.getByRole('dialog')
  const close = () => page.getByRole('button', { name: 'Close', exact: true }).click()
  const check = (condition, label) => { if (!condition) throw new Error(label) }
  await details.nth(0).click(); await close(); await details.nth(1).click()
  await page.waitForTimeout(1800)
  check((await dialog.innerText()).includes('SYNTHETIC_LOG_2') && !(await dialog.innerText()).includes('SYNTHETIC_LOG_1'), 'late success replaced current log')
  await close()
  scenario = 'loading'
  await details.nth(0).click(); await close(); await details.nth(1).click()
  await page.waitForTimeout(1700)
  check((await dialog.innerText()).includes('加载中...'), 'old failure ended newer loading')
  await page.waitForTimeout(900)
  check((await dialog.innerText()).includes('SYNTHETIC_LOG_2'), 'new log missing')
  await close()
  scenario = 'race'
  await details.nth(0).click(); await close(); await details.nth(2).click()
  await page.waitForTimeout(1800)
  const text = await dialog.innerText()
  check(text.includes('历史执行参数不是有效 JSON') && text.includes('{invalid historical json'), 'invalid JSON fallback missing')
  check(!text.includes('SYNTHETIC_LOG_1') && !text.includes('加载中...'), 'no-run selection inherited log state')
  check(await page.getByRole('heading', { name: '我的反馈' }).isVisible(), 'page blank')
  await close()
  check(errors.length === 0, 'page errors: ' + errors.join(';'))
  console.log('PASS: late success, late error/loading, close, no-run, malformed JSON; pageerrors=0')
}
