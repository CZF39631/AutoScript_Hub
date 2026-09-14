// playwright-cli -s=tasks-130 run-code --filename=frontend/tests/tasks.browser.js
// Vite on 5327 only. All API/Agent requests intercepted; no production or installed Agent access.
async page => {
  await page.goto('about:blank')
  await page.context().unrouteAll({ behavior: 'ignoreErrors' })
  const origin = 'http://127.0.0.1:5327'
  const errors = [], writes = []
  const check = (ok, label) => { if (!ok) throw new Error(label) }
  page.on('pageerror', e => errors.push(e.message))
  const task = { id: 1, name: '合成周报任务', device_id: 7, script_id: 1, script_version: 1, enabled: true, trigger: { kind: 'weekly', timezone: 'Asia/Shanghai', time: '09:00', weekdays: [0, 4] } }
  await page.context().addInitScript(() => {
    if (!location.origin.startsWith('http://127.0.0.1:5327')) return
    localStorage.setItem('token', 'synthetic-only')
    localStorage.setItem('user', JSON.stringify({ id: 1, username: 'synthetic', display_name: '合成测试', role: 'operator' }))
    window._AGENT_API_TOKEN = 'synthetic-only'
  })
  await page.context().route('**/*', async route => {
    const request = route.request(), parts = request.url().match(/^(https?:\/\/[^/]+)(\/[^?]*)/)
    if (!parts) return route.abort()
    const requestOrigin = parts[1], path = parts[2]
    const isAgent = /^http:\/\/127\.0\.0\.1:180(80|9[1-9])$/.test(requestOrigin)
    if (requestOrigin !== origin && !isAgent) return route.abort()
    if (path.startsWith('/api/') || path.startsWith('/local/')) {
      let data = []
      if (request.method() === 'OPTIONS') return route.fulfill({ status: 204, headers: { 'Access-Control-Allow-Origin': origin, 'Access-Control-Allow-Headers': '*', 'Access-Control-Allow-Methods': '*' } })
      if (request.method() === 'POST') { writes.push({ path, body: request.postDataJSON() }); data = { id: 2 } }
      else if (path === '/api/health') data = { status: 'ok' }
      else if (path === '/local/connection') data = { agent_id: 7, pending_sync_count: 0 }
      else if (path === '/api/tasks' || path === '/local/schedules') data = [task]
      else if (path === '/api/tasks/executions' || path === '/local/schedule-events') data = [{ id: 1, task_id: 1, task_name: task.name, run_id: path.startsWith('/local') ? 'L1' : 1, state: 'unknown', error_msg: '合成：设备失联，尚未确认停止' }]
      else if (path === '/api/task-devices') data = [{ id: 7, name: '合成电脑', status: 'online' }]
      else if (path === '/local/task-device') data = { id: 7, name: '合成电脑', registered: true }
      else if (path === '/api/tasks/grants' || path === '/local/device-grants') data = [{ id: 9, device_id: 7, requester_id: 1, script_id: 1, script_version: 1, status: path.startsWith('/local') ? 'pending' : 'accepted' }]
      else if (path === '/api/scripts/marketplace' || path === '/local/scripts') data = [{ id: 1, name: '合成报表', latest_version: 2, config: { params: [{ key: 'file', label: '输出目录', type: 'folder', required: true }] } }]
      else if (path === '/api/scripts/1/versions') data = [{ version: 2 }, { version: 1 }]
      else if (path.match(/^\/api\/scripts\/1\/versions\/\d+\/config$/)) data = { config: { params: [{ key: 'region', label: path.includes('/1/config') ? '旧版本参数' : '新版本参数', required: true, type: 'text' }, { key: 'archive', label: '启用归档', type: 'checkbox', default: false }] } }
      return route.fulfill({ status: 200, headers: { 'Access-Control-Allow-Origin': origin }, contentType: 'application/json', body: JSON.stringify(data) })
    }
    if (isAgent) return route.abort()
    return route.continue()
  })
  await page.setViewportSize({ width: 1440, height: 1000 })
  await page.goto(origin + '/tasks')
  await page.getByText('合成周报任务', { exact: true }).waitFor()
  await page.getByRole('button', { name: /新建任务/ }).click()
  await page.getByLabel('任务名称', { exact: true }).fill('合成固定版本任务')
  await page.getByLabel('目标设备编号', { exact: true }).click()
  await page.getByText('合成电脑（#7，在线）', { exact: true }).last().click()
  await page.getByLabel('脚本', { exact: true }).click()
  await page.getByText('合成报表', { exact: true }).last().click()
  await page.getByLabel('新版本参数', { exact: true }).waitFor()
  await page.getByLabel('固定版本编号', { exact: true }).click()
  await page.getByText('版本 #1', { exact: true }).last().click()
  await page.getByLabel('旧版本参数', { exact: true }).fill('合成值')
  await page.getByRole('checkbox', { name: '启用归档', exact: true }).check()
  await page.getByRole('button', { name: '创建任务', exact: true }).click()
  await page.getByRole('dialog').waitFor({ state: 'hidden' })
  const created = writes.find(w => w.path === '/api/tasks')
  check(created?.body.script_version === 1 && created.body.params.region === '合成值' && created.body.params.archive === true, 'selected version/config did not reach request')
  check(created.body.trigger.timezone && created.body.trigger.kind === 'manual', 'timezone missing')
  await page.getByRole('button', { name: '运行一次', exact: true }).click()
  await page.getByText('将在合成电脑（#7）运行脚本 #1 的固定版本 #1，使用已保存参数。', { exact: true }).waitFor()
  await page.getByRole('button', { name: /确\s*定/ }).click()
  await page.getByText('运行请求已接受，请在执行记录查看结果').waitFor()
  check(/^[0-9a-f-]{36}$/.test(writes.find(w => w.path === '/api/tasks/1/action')?.body.request_id), 'manual request lacks UUID')
  await page.getByRole('tab', { name: '最近执行', exact: true }).click()
  check(await page.getByText('结果未知', { exact: true }).isVisible(), 'unknown not visible')
  await page.getByRole('tab', { name: '本机任务', exact: true }).click()
  await page.getByText(/本机设备编号：7/).waitFor()
  await page.getByRole('tab', { name: '设备授权', exact: true }).click()
  await page.getByRole('button', { name: /允\s*许/ }).click()
  await page.getByText('允许该用户以你的电脑权限运行此脚本版本？').waitFor()
  check(!writes.some(w => w.path.includes('/decision')), 'grant sent before confirmation')
  await page.getByRole('button', { name: /确\s*定/ }).click()
  await page.getByText('允许该用户以你的电脑权限运行此脚本版本？').waitFor({ state: 'hidden' })
  await page.getByRole('tab', { name: '任务列表', exact: true }).click()
  await page.locator('.ant-message-notice').last().waitFor({ state: 'hidden' })
  for (const width of [1440, 800]) {
    await page.setViewportSize({ width, height: 1000 })
    await page.screenshot({ path: `.playwright-cli/tasks-${width}.png`, fullPage: true, animations: 'disabled' })
    check(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 2), 'page horizontal overflow: ' + width)
  }
  check(writes.some(w => w.path === '/local/device-grants/9/decision' && w.body.decision === 'accept'), 'local consent missing')
  check(!errors.length, 'page errors: ' + errors.join(';'))
  return { passed: true, checks: ['fixed-version parameters and checkbox', 'target-device confirmation', 'manual UUID', 'unknown state', 'local-only grant confirmation', '1440/800 overflow'], pageErrors: errors }
}
