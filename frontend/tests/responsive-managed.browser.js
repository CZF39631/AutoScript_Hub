// Run with playwright-cli -s=<local session> run-code --filename=<this file>.
// Requires the local Vite dev server on 5183. All APIs and external requests are mocked/blocked.
async page => {
  const origin = 'http://127.0.0.1:5183'
  const errors = []
  let showAgent = false
  let optionsAttempts = 0
  let detailAttempts = 0
  const agent = {
    id: 7, machine_name: '验收设备', machine_ip: '127.0.0.7', agent_version: 'test',
    enabled: true, status: 'online', pending_count: 0, current_run: null, latest_run: null,
  }
  page.on('pageerror', error => errors.push(error.message))
  await page.context().route('**/*', async route => {
    const raw = route.request().url()
    if (!raw.startsWith(origin + '/')) {
      if (/^http:\/\/127\.0\.0\.1:\d+\/local\/connection/.test(raw)) {
        return route.fulfill({ json: { agent_id: 'synthetic', pending_sync_count: 0 } })
      }
      return route.abort()
    }
    const path = raw.slice(origin.length).split('?')[0]
    if (!path.startsWith('/api/') && !path.startsWith('/local/')) return route.continue()
    if (path === '/api/health') return route.fulfill({ json: { status: 'ok' } })
    if (path === '/local/connection') return route.fulfill({ json: { agent_id: 'synthetic', pending_sync_count: 0 } })
    if (path === '/api/dashboard/stats') return route.fulfill({ json: {
      today_runs: 0, week_runs: 0, today_success: 0, today_success_rate: 0, today_failed: 0,
      online_users: 0, total_users: 0, week_success_rate: 0, week_success: 0,
      total_scripts: 0, total_runs: 0, script_ranking: [], recent_failed: [],
    } })
    if (path === '/api/settings') return route.fulfill({ json: { update_manifest_urls: [] } })
    if (path === '/api/admin/managed-agents') return route.fulfill({ json: showAgent ? [agent] : [] })
    if (path === '/api/admin/managed-schedules') return route.fulfill({ json: [] })
    if (path === '/api/admin/managed-agents/7/options') {
      optionsAttempts += 1
      if (optionsAttempts === 1) return route.fulfill({ status: 503, json: { detail: '合成选项故障' } })
      return route.fulfill({ json: { scripts: [{ id: 11, name: '安全测试脚本', status: 'active' }], environments: [] } })
    }
    if (path === '/api/scripts/11') {
      detailAttempts += 1
      if (detailAttempts === 1) return route.fulfill({ status: 503, json: { detail: '合成详情故障' } })
      return route.fulfill({ json: { id: 11, name: '安全测试脚本', config_json: '{"params":[]}' } })
    }
    return route.fulfill({ json: [] })
  })

  const login = async width => {
    await page.setViewportSize({ width, height: 900 })
    await page.goto(origin)
    await page.evaluate(() => {
      localStorage.setItem('token', 'synthetic-only')
      localStorage.setItem('user', JSON.stringify({ id: 1, username: 'admin', display_name: '验收管理员', role: 'admin' }))
    })
    await page.goto(origin + '/managed-agents')
    await page.getByRole('heading', { name: '设备托管' }).waitFor()
  }
  const assertNoDocumentOverflow = async label => {
    const dimensions = await page.evaluate(() => ({ width: document.documentElement.clientWidth, scroll: document.documentElement.scrollWidth }))
    if (dimensions.scroll > dimensions.width + 1) throw new Error(`${label} document overflow: ${JSON.stringify(dimensions)}`)
  }
  const assertNoHiddenFocusable = async label => {
    const offenders = await page.evaluate(() => [...document.querySelectorAll('[aria-hidden="true"]')].flatMap(node =>
      [...node.querySelectorAll('a[href],button,input,select,textarea,[tabindex]')]
        .filter(item => !item.disabled && item.tabIndex >= 0)
        .map(item => item.outerHTML.slice(0, 160))))
    if (offenders.length) throw new Error(`${label} aria-hidden contains focusable content: ${offenders.join('; ')}`)
  }

  const mainRoutes = ['/dashboard', '/scripts', '/runs', '/issues', '/environments', '/settings', '/updates', '/managed-agents', '/users', '/audit']
  for (const width of [390, 640, 900, 1280]) {
    await login(width)
    for (const path of mainRoutes) {
      await page.goto(origin + path)
      await page.waitForTimeout(80)
      await assertNoDocumentOverflow(`${width}px ${path}`)
      await assertNoHiddenFocusable(`${width}px ${path}`)
    }
  }

  for (const width of [390, 640]) {
    await login(width)
    await page.getByRole('heading', { name: '连接第一台设备' }).waitFor()
    const menu = page.getByRole('button', { name: '打开主导航菜单' })
    const box = await menu.boundingBox()
    if (!box || box.width < 44 || box.height < 44) throw new Error(`${width}px menu target below 44x44`)
    await menu.click()
    await page.getByRole('navigation', { name: '主导航' }).waitFor()
    await page.keyboard.press('Escape')
    await page.getByRole('button', { name: '打开主导航菜单' }).waitFor()
    if (!await page.getByRole('button', { name: '打开主导航菜单' }).evaluate(node => node === document.activeElement)) {
      throw new Error(`${width}px menu focus was not restored`)
    }
    await assertNoDocumentOverflow(`${width}px`)
    await assertNoHiddenFocusable(`${width}px`)
  }

  await login(900)
  await page.getByRole('button', { name: '展开侧边导航' }).waitFor()
  await assertNoDocumentOverflow('900px')
  await assertNoHiddenFocusable('900px')

  await login(1280)
  showAgent = true
  await page.locator('.managed-section-heading').getByRole('button').click()
  await page.getByRole('button', { name: '发布任务' }).click()
  const dispatchDrawer = page.getByRole('dialog', { name: /向 验收设备 发布任务/ })
  await dispatchDrawer.getByText('可用选项读取失败').waitFor()
  await dispatchDrawer.getByText('定时任务', { exact: true }).click()
  await dispatchDrawer.getByLabel('任务名称').fill('保留的试运行')
  await dispatchDrawer.getByRole('button', { name: '重试读取' }).click()
  await dispatchDrawer.getByText('可用选项读取失败').waitFor({ state: 'hidden' })
  if (await dispatchDrawer.getByLabel('任务名称').inputValue() !== '保留的试运行') throw new Error('options retry cleared form content')
  await dispatchDrawer.getByLabel('脚本').click()
  await page.getByText('安全测试脚本', { exact: true }).last().click()
  await dispatchDrawer.getByText('脚本详情读取失败').waitFor()
  if (await dispatchDrawer.getByLabel('任务名称').inputValue() !== '保留的试运行') throw new Error('detail failure cleared form content')
  await dispatchDrawer.locator('.ant-alert-error').filter({ hasText: '脚本详情读取失败' }).getByRole('button').click()
  await dispatchDrawer.getByText('此脚本无需额外参数').waitFor()
  await assertNoDocumentOverflow('desktop drawer')
  await assertNoHiddenFocusable('desktop drawer')

  if (errors.length) throw new Error('page errors: ' + errors.join('; '))
  console.log('PASS: 390/640 mobile drawer, 900 collapsible sidebar, first-device onboarding, option/detail recovery, focus and overflow')
}
