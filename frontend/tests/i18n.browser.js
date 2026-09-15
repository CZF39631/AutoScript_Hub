// Run with playwright-cli in a NEW isolated session against a static build on 5337.
// All API/Agent requests are synthetic; all other origins are blocked.
async page => {
  const origin = 'http://127.0.0.1:5337'
  const errors = [], writes = [], reads = [], layouts = []
  let rejectLogin = true
  const check = (ok, message) => { if (!ok) throw new Error(message) }
  const script = { id: 1, name: '原始脚本名称', description: '原始脚本说明', category: '合成分类', latest_version: 1, installed_version: 1, status: 'active', author_id: 1, config_json: JSON.stringify({ params: [{ key: 'region', label: '原始参数', type: 'text', required: true }, { key: 'archive', label: '启用归档', type: 'checkbox', default: false }] }) }
  const run = { id: 1, script_id: 1, script_name: script.name, script_version: 1, status: 'success', user_id: 1, username: 'synthetic', started_at: '2026-01-01T00:00:00Z', finished_at: '2026-01-01T00:00:01Z', created_at: '2026-01-01T00:00:00Z', duration_sec: 1, params: '{"region":"原始业务内容"}' }
  const task = { id: 1, name: '合成任务', device_id: 7, script_id: 1, script_version: 1, enabled: true, trigger: { kind: 'weekly', timezone: 'Asia/Shanghai', time: '09:00', weekdays: [0, 4] } }
  await page.goto('about:blank')
  await page.context().unrouteAll({ behavior: 'ignoreErrors' })
  page.on('pageerror', error => errors.push(error.message))
  await page.context().addInitScript(() => {
    if (location.origin === 'http://127.0.0.1:5337') window._AGENT_API_TOKEN = 'synthetic-only'
  })
  await page.context().route('**/*', async route => {
    const request = route.request(), parts = request.url().match(/^(https?:\/\/[^/]+)(\/[^?]*)/)
    if (!parts) return route.abort()
    const requestOrigin = parts[1], path = parts[2]
    const local = /^http:\/\/127\.0\.0\.1:18\d{3}$/.test(requestOrigin)
    if (requestOrigin !== origin && !local) return route.abort()
    const headers = { 'Access-Control-Allow-Origin': origin, 'Access-Control-Allow-Headers': '*', 'Access-Control-Allow-Methods': '*' }
    if (request.method() === 'OPTIONS') return route.fulfill({ status: 204, headers })
    if (path.startsWith('/api/') || path.startsWith('/local/') || path === '/detect-browsers') {
      let data = [], status = 200
      if (request.method() !== 'GET') writes.push({ path, method: request.method(), body: request.postDataJSON() })
      else reads.push(path)
      if (path === '/api/auth/login') {
        status = rejectLogin ? 401 : 200
        data = rejectLogin ? { detail: '用户名或密码错误' } : { token: 'synthetic-only', user: { id: 1, username: 'synthetic', display_name: '合成用户', role: 'admin' } }
      } else if (path === '/api/health') data = { status: 'ok' }
      else if (path === '/local/connection') data = { agent_id: 7, pending_sync_count: 0 }
      else if (path === '/local/update') data = { state: 'idle', version: '1.3.0-preview.1', install_flavor: 'preview' }
      else if (path === '/local/runtime') data = { environments: [] }
      else if (path === '/api/settings') data = { output_dir: '', update_manifest_urls: [], update_channel: 'stable' }
      else if (path === '/api/settings/diagnostics') data = { enabled: true, redact_logs: true, redact_params: true, redact_summary: true, custom_sensitive_fields: [], retention_days: 30, revision: 1 }
      else if (path === '/api/scripts' || path === '/api/scripts/marketplace' || path === '/local/scripts') data = [script]
      else if (path === '/api/scripts/1') data = script
      else if (path === '/api/scripts/1/versions') data = [{ version: 1, semantic_version: '1.0.0', config_json: script.config_json }]
      else if (path === '/api/scripts/1/versions/1/config') data = { config: JSON.parse(script.config_json) }
      else if (path === '/api/tasks' || path === '/local/schedules') data = request.method() === 'GET' ? [task] : { id: 2 }
      else if (path === '/api/task-devices') data = [{ id: 7, name: '合成电脑', status: 'online' }]
      else if (path === '/local/task-device') data = { id: 7, name: '合成电脑', registered: true }
      else if (path === '/api/runs') data = [run]
      else if (path === '/api/runs/1') data = run
      else if (path === '/api/runs/1/log') data = { log: '原始日志 / RAW LOG <script>not HTML</script>' }
      else if (path === '/api/dashboard/stats') data = { today_runs: 1, week_runs: 1, today_success: 1, today_failed: 0, today_success_rate: 100, online_users: 1, total_users: 1, week_success_rate: 100, week_success: 1, total_scripts: 1, total_runs: 1, script_ranking: [], recent_failed: [] }
      return route.fulfill({ status, headers, contentType: 'application/json', body: JSON.stringify(data) })
    }
    if (local) return route.abort()
    return route.continue()
  })
  const language = async (label, code) => {
    await page.locator('.language-select').click()
    await page.locator('.ant-select-item-option-content').getByText(label, { exact: true }).click()
    await page.waitForFunction(value => document.documentElement.lang === value, code)
  }
  const capture = async name => {
    await page.waitForFunction(() => !document.querySelector('.ant-message')?.textContent.trim())
    for (const width of [1440, 800]) {
      await page.setViewportSize({ width, height: 1000 })
      await page.screenshot({ path: `.playwright-cli/i18n-${name}-${width}.png`, fullPage: true, animations: 'disabled' })
      const layout = await page.evaluate(() => ({ width: innerWidth, scroll: document.documentElement.scrollWidth }))
      layouts.push({ page: name, ...layout })
      check(layout.scroll <= width + 2, `${name}: horizontal page overflow at ${width}`)
    }
  }
  await page.setViewportSize({ width: 1440, height: 1000 })
  await page.goto(origin + '/login')
  await page.evaluate(() => {
    for (const key of ['token', 'user', 'autoscript.ui.language']) localStorage.removeItem(key)
  })
  await page.reload()
  await page.getByLabel('账号', { exact: true }).fill('synthetic')
  await page.getByLabel('密码', { exact: true }).fill('synthetic-not-a-real-secret')
  await language('English', 'en-US')
  check(await page.getByLabel('Account', { exact: true }).inputValue() === 'synthetic', 'switch cleared username')
  check(await page.getByLabel('Password', { exact: true }).inputValue() === 'synthetic-not-a-real-secret', 'switch cleared password')
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  await page.getByRole('alert').filter({ hasText: 'Incorrect username or password' }).waitFor()
  await language('简体中文', 'zh-CN')
  await page.getByRole('alert').filter({ hasText: '用户名或密码错误' }).waitFor()
  await language('English', 'en-US')
  await capture('login-en')
  await page.reload()
  await page.getByRole('button', { name: 'Sign in', exact: true }).waitFor()
  check(await page.evaluate(() => localStorage.getItem('autoscript.ui.language')) === 'en-US', 'language was not persisted')
  rejectLogin = false
  await page.getByLabel('Account', { exact: true }).fill('synthetic')
  await page.getByLabel('Password', { exact: true }).fill('synthetic-not-a-real-secret')
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  await page.waitForURL('**/scripts')
  await page.getByText(script.name, { exact: true }).first().waitFor()

  await page.goto(origin + '/settings')
  await page.getByLabel('Output directory', { exact: true }).fill('C:\\synthetic\\keep-this-value')
  const settingsReads = reads.filter(value => value === '/api/settings').length
  await language('简体中文', 'zh-CN')
  check(await page.getByLabel('输出目录', { exact: true }).inputValue() === 'C:\\synthetic\\keep-this-value', 'settings value lost on switch')
  await language('English', 'en-US')
  check(await page.getByLabel('Output directory', { exact: true }).inputValue() === 'C:\\synthetic\\keep-this-value', 'settings value lost on return switch')
  check(reads.filter(value => value === '/api/settings').length === settingsReads, 'language switch reloaded settings')
  check(writes.every(value => value.path === '/api/auth/login'), 'language switch caused a business write')
  await capture('settings-en')

  await page.goto(origin + '/tasks')
  await page.getByText(task.name, { exact: true }).waitFor()
  await page.getByRole('button', { name: /New task/ }).click()
  await page.getByLabel('Task name', { exact: true }).fill('保留任务名称')
  await page.getByLabel('Target device ID', { exact: true }).click()
  await page.getByText('合成电脑 (#7, Online)', { exact: true }).last().click()
  await page.getByLabel('Script', { exact: true }).click()
  await page.getByText(script.name, { exact: true }).last().click()
  await page.getByLabel('原始参数', { exact: true }).fill('原始业务值')
  await page.getByRole('checkbox', { name: '启用归档', exact: true }).check()
  await page.getByLabel('Time zone', { exact: true }).fill('Asia/Tokyo')
  await page.getByRole('button', { name: 'Create task', exact: true }).click()
  await page.getByRole('dialog').waitFor({ state: 'hidden' })
  const created = writes.find(value => value.path === '/api/tasks')?.body
  check(created?.name === '保留任务名称' && created.script_id === 1 && created.script_version === 1 && created.device_id === 7, 'task identifiers changed')
  check(created.params.region === '原始业务值' && created.params.archive === true, 'parameter keys or values changed')
  check(created.trigger.timezone === 'Asia/Tokyo' && created.trigger.kind === 'manual', 'language changed trigger or time zone')
  await capture('tasks-en')
  await language('简体中文', 'zh-CN')
  await capture('tasks-zh')
  await language('English', 'en-US')

  await page.goto(origin + '/runs/1')
  await page.getByText('原始日志 / RAW LOG <script>not HTML</script>', { exact: true }).waitFor()
  await capture('run-en')
  await page.goto(origin + '/scripts/1')
  await page.getByLabel('原始参数', { exact: true }).fill('切换后保留的参数')
  await language('简体中文', 'zh-CN')
  check(await page.getByLabel('原始参数', { exact: true }).inputValue() === '切换后保留的参数', 'script form value lost on switch')
  await language('English', 'en-US')
  check(await page.getByLabel('原始参数', { exact: true }).inputValue() === '切换后保留的参数', 'script form value lost on return switch')
  await page.goto(origin + '/runs')
  await page.getByPlaceholder('Start date', { exact: true }).click()
  check(/[A-Za-z]/.test(await page.locator('.ant-picker-month-btn').first().innerText()), 'English calendar locale missing')
  await language('简体中文', 'zh-CN')
  await page.getByPlaceholder('开始日期', { exact: true }).click()
  check(/月/.test(await page.locator('.ant-picker-month-btn').first().innerText()), 'Chinese calendar locale missing')
  await language('English', 'en-US')
  for (const route of ['/dashboard', '/scripts/1', '/runs', '/users', '/audit', '/issues', '/environments', '/updates']) {
    await page.goto(origin + route)
    await page.locator('.app-content h2').first().waitFor()
    check((await page.locator('.app-content').innerText()).trim().length > 0, `blank route: ${route}`)
  }
  await page.setViewportSize({ width: 800, height: 600 })
  await page.waitForFunction(() => {
    const rect = document.querySelector('.language-select').getBoundingClientRect()
    return rect.top >= 0 && rect.bottom <= innerHeight && rect.width > 0
  })
  check(writes.filter(value => value.path !== '/api/auth/login').length === 1, 'unexpected business write after language changes')
  check(errors.length === 0, 'page errors: ' + errors.join('; '))
  return { passed: true, checks: ['login and error language switch', 'refresh persistence', 'settings and script form preservation', 'calendar locale', 'no language-triggered business writes', 'raw script labels and logs', 'unchanged task payload and time zone', 'all main routes render', 'short-window language selector'], layouts, pageErrors: errors }
}
