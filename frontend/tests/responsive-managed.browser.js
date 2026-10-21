// Run with playwright-cli -s=<local session> run-code --filename=<this file>.
// Requires the local Vite dev server on 5183. All APIs and external requests are mocked/blocked.
async page => {
  const origin = 'http://127.0.0.1:5183'
  const errors = []
  const expectedInjectedConsoleErrors = []
  const realConsoleErrors = []
  const expectedFailurePaths = [
    '/api/admin/managed-agent-batches',
    '/api/admin/managed-agents/7/options',
    '/api/scripts/11',
  ]
  let showAgent = false
  let failNextOptions = true
  let detailAttempts = 0
  let thumbnailRequests = 0
  let batchExecuteAttempts = 0
  const batchExecuteKeys = []
  let groups = []
  const agent = {
    id: 7, machine_name: '验收设备', machine_ip: '127.0.0.7', agent_version: 'test',
    enabled: true, status: 'online', pending_count: 0, current_run: null, latest_run: null,
    groups: [], thumbnail_updated_at: '2026-10-21T08:00:00Z', thumbnail_size: 128,
  }
  page.on('pageerror', error => errors.push(error.message))
  page.on('console', message => {
    if (message.type() !== 'error') return
    const text = message.text()
    const locationUrl = message.location().url || ''
    if (/503/.test(text) && expectedFailurePaths.some(path => locationUrl.includes(path))) {
      expectedInjectedConsoleErrors.push(`${locationUrl}: ${text}`)
    } else {
      realConsoleErrors.push(`${locationUrl}: ${text}`)
    }
  })
  await page.context().route('**/*', async route => {
    const raw = route.request().url()
    if (!raw.startsWith(origin + '/')) {
      if (/^http:\/\/127\.0\.0\.1:\d+\/local\/connection/.test(raw)) {
        return route.fulfill({ json: { agent_id: 'synthetic', pending_sync_count: 0 } })
      }
      if (/^http:\/\/127\.0\.0\.1:\d+\/local\/update/.test(raw)) {
        return route.fulfill({ json: { current_version: 'test', state: 'idle', update_available: false } })
      }
      if (/^http:\/\/127\.0\.0\.1:\d+\/local\/runtime/.test(raw)) {
        return route.fulfill({ json: { status: 'ready', version: '3.11.9' } })
      }
      return route.abort()
    }
    const path = raw.slice(origin.length).split('?')[0]
    if (!path.startsWith('/api/') && !path.startsWith('/local/')) return route.continue()
    if (path === '/api/health') return route.fulfill({ json: { status: 'ok' } })
    if (path === '/local/connection') return route.fulfill({ json: { agent_id: 'synthetic', pending_sync_count: 0 } })
    if (path === '/local/update') return route.fulfill({ json: { current_version: 'test', state: 'idle', update_available: false } })
    if (path === '/api/dashboard/stats') return route.fulfill({ json: {
      today_runs: 0, week_runs: 0, today_success: 0, today_success_rate: 0, today_failed: 0,
      online_users: 0, total_users: 0, week_success_rate: 0, week_success: 0,
      total_scripts: 0, total_runs: 0, script_ranking: [], recent_failed: [],
    } })
    if (path === '/api/settings') return route.fulfill({ json: { update_manifest_urls: [] } })
    if (path === '/api/audit') return route.fulfill({ json: [{
      id: 1, username: 'admin', action: 'managed_thumbnail.view',
      target_type: 'agent', target_id: 7, target_name: '验收设备',
      detail: 'synthetic', created_at: '2026-10-21T08:00:00Z',
    }] })
    if (path === '/api/admin/managed-agents') return route.fulfill({ json: showAgent ? [agent] : [] })
    if (path === '/api/admin/managed-agents/paged') return route.fulfill({ json: {
      items: showAgent ? [agent] : [], total: showAgent ? 2 : 0, page: 1, page_size: 24, pages: 1,
    } })
    if (path === '/api/admin/managed-agent-groups') {
      if (route.request().method() === 'POST') {
        const body = route.request().postDataJSON()
        const group = { id: 31, name: body.name, description: null, member_count: 0, created_at: new Date().toISOString(), updated_at: new Date().toISOString() }
        groups = [group]
        return route.fulfill({ json: group })
      }
      return route.fulfill({ json: groups })
    }
    if (path === '/api/admin/managed-agents/7/groups') {
      const body = route.request().postDataJSON()
      agent.groups = groups.filter(group => body.group_ids.includes(group.id)).map(({ id, name }) => ({ id, name }))
      return route.fulfill({ json: agent.groups })
    }
    if (path === '/api/admin/managed-schedules') return route.fulfill({ json: [] })
    if (path === '/api/admin/managed-agents/7/thumbnail') {
      thumbnailRequests += 1
      return route.fulfill({ status: 200, contentType: 'image/jpeg', body: 'synthetic-jpeg' })
    }
    if (path === '/api/admin/managed-agents/7/impact') return route.fulfill({ json: {
      action: raw.includes('action=delete') ? 'delete' : 'disable', agent_id: 7, machine_name: '验收设备', version: 'impact-v1',
      pending_count: 1, running_count: 1, enabled_schedule_count: 1, paused_schedule_count: 0,
      thumbnail_exists: true, history_policy: { message: '运行历史和计划记录均保留。' },
      identity_recovery: { message: '删除后需要重新授权。' },
    } })
    if (path === '/api/admin/managed-agent-batches/preview') {
      const body = route.request().postDataJSON()
      return route.fulfill({ json: {
        operation: body.operation, total: 1, success: 1, failed: 0, skipped: 0,
        items: [{ agent_id: 7, machine_name: '验收设备', result: 'success', reason: '验证通过' }], replayed: false,
      } })
    }
    if (path === '/api/admin/managed-agent-batches') {
      batchExecuteAttempts += 1
      batchExecuteKeys.push(route.request().headers()['idempotency-key'])
      if (batchExecuteAttempts === 1) return route.fulfill({ status: 503, json: { detail: '合成网络不确定故障' } })
      const body = route.request().postDataJSON()
      return route.fulfill({ json: {
        batch_id: 91, operation: body.operation, total: 1, success: 1, failed: 0, skipped: 0,
        items: [{ agent_id: 7, machine_name: '验收设备', result: 'success', reason: '操作成功' }], replayed: true,
      } })
    }
    if (path === '/api/admin/managed-agents/7/options') {
      if (failNextOptions) {
        failNextOptions = false
        return route.fulfill({ status: 503, json: { detail: '合成选项故障' } })
      }
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

  await page.goto(origin + '/audit?target_type=agent&target_id=7')
  await page.getByRole('status', { name: '当前对象筛选' }).getByText('验收设备 #7').waitFor()
  await page.getByText('验收设备（agent #7）').waitFor()
  await page.getByRole('button', { name: '清除对象筛选' }).click()
  if (page.url().includes('target_id=')) throw new Error('audit target filter was not cleared visibly')

  showAgent = true
  await login(390)
  await page.getByText('画面已遮罩，查看操作会记录审计').waitFor()
  if (thumbnailRequests !== 0) throw new Error(`first viewport requested ${thumbnailRequests} thumbnails before user action`)
  const deviceCheckbox = page.getByLabel('选择设备 验收设备')
  const touchBox = await deviceCheckbox.evaluate(node => {
    const box = node.closest('label')?.getBoundingClientRect()
    return box ? { width: box.width, height: box.height } : null
  })
  if (!touchBox || touchBox.width < 44 || touchBox.height < 44) throw new Error(`390px device checkbox target below 44x44: ${JSON.stringify(touchBox)}`)

  await page.getByRole('button', { name: '选中全部筛选结果（2 台）' }).click()
  if (!await deviceCheckbox.isChecked()) throw new Error('all-filtered mode did not visually check the page device')
  if (!await page.getByRole('checkbox', { name: '选中本页（1 台）' }).isChecked()) throw new Error('all-filtered mode did not visually check the page checkbox')
  const search = page.getByPlaceholder('搜索设备名、IP、版本或设备 ID')
  await search.fill('验收')
  if (await deviceCheckbox.isChecked()) throw new Error('filter change did not clear explicit/all selection')
  await search.clear()
  await deviceCheckbox.check()
  await page.getByRole('button', { name: '发布临时任务' }).waitFor()
  const selectionBar = page.locator('.managed-selection-bar')
  const selectionBox = await selectionBar.boundingBox()
  if (!selectionBox || selectionBox.x < -1 || selectionBox.x + selectionBox.width > 391) throw new Error('390px batch bar overflow')
  await assertNoDocumentOverflow('390px batch bar')

  await login(1280)
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
  await dispatchDrawer.getByRole('button', { name: '关闭' }).click()
  await dispatchDrawer.waitFor({ state: 'hidden' })

  await page.getByRole('button', { name: '管理分组' }).click()
  const groupManager = page.getByRole('dialog', { name: '设备分组管理' })
  await groupManager.getByPlaceholder('新分组名称').fill('浏览器验收组')
  await groupManager.getByRole('button', { name: '创建分组' }).click()
  await groupManager.getByText('浏览器验收组', { exact: true }).waitFor()
  await groupManager.getByRole('button', { name: /关\s*闭/ }).click()
  await page.locator('.managed-agent-card__groups').getByRole('button').click()
  const assignGroup = page.getByRole('dialog', { name: /调整“验收设备”的分组/ })
  await assignGroup.locator('.ant-select').first().click()
  await page.getByText('浏览器验收组', { exact: true }).last().click()
  await assignGroup.getByRole('button', { name: '保存设备分组' }).click()
  await page.locator('.managed-agent-card__groups').getByText('浏览器验收组', { exact: true }).waitFor()

  await page.getByLabel('选择设备 验收设备').check()
  await page.locator('.managed-selection-bar').getByRole('button', { name: '暂停接单' }).click()
  const dangerBatch = page.getByRole('dialog', { name: '批量暂停接单' })
  await dangerBatch.getByRole('button', { name: '预览影响' }).click()
  const confirmBatch = dangerBatch.getByRole('button', { name: '确认执行' })
  await confirmBatch.waitFor()
  if (!await confirmBatch.evaluate(node => node.classList.contains('ant-btn-dangerous'))) throw new Error('dangerous batch confirmation is not visually dangerous')
  await confirmBatch.click()
  await page.waitForTimeout(120)
  await confirmBatch.click()
  await dangerBatch.getByText('批次 #91 已完成').waitFor()
  if (batchExecuteKeys.length !== 2 || !batchExecuteKeys[0] || batchExecuteKeys[0] !== batchExecuteKeys[1]) {
    throw new Error(`batch retry did not reuse Idempotency-Key: ${JSON.stringify(batchExecuteKeys)}`)
  }
  await dangerBatch.getByRole('button', { name: /完\s*成/ }).click()

  await page.getByLabel('删除设备验收设备').click()
  const deleteModal = page.getByRole('dialog', { name: '删除设备前确认影响' })
  const deleteConfirm = deleteModal.getByRole('button', { name: '永久删除设备' })
  if (!await deleteConfirm.isDisabled()) throw new Error('delete confirmation was enabled before exact device name')
  await deleteModal.getByLabel(/输入设备名/).fill('验收设备')
  if (await deleteConfirm.isDisabled()) throw new Error('delete confirmation stayed disabled after exact device name')
  await deleteModal.getByRole('button', { name: /取\s*消/ }).click()

  failNextOptions = true
  await page.getByLabel('选择设备 验收设备').check()
  await page.getByRole('button', { name: '发布临时任务' }).click()
  const batchDispatch = page.getByRole('dialog', { name: '批量发布临时任务' })
  await batchDispatch.getByText('批量任务选项加载失败').waitFor()
  const batchParams = batchDispatch.locator('textarea')
  await batchParams.fill('{"keep":"value"}')
  await batchDispatch.getByRole('button', { name: '重试加载' }).click()
  await batchDispatch.getByText('批量任务选项加载失败').waitFor({ state: 'hidden' })
  if (await batchParams.inputValue() !== '{"keep":"value"}') throw new Error('batch options retry cleared configuration')
  await batchDispatch.getByRole('button', { name: /取\s*消/ }).click()

  if (errors.length) throw new Error('page errors: ' + errors.join('; '))
  if (realConsoleErrors.length) throw new Error('real console errors: ' + realConsoleErrors.join('; '))
  console.log(`PASS: responsive layout, zero first-load thumbnails, groups, selection, dangerous/delete modals, idempotent retry and option recovery; pageerrors=0; real-console-errors=0; expected-injected-console-errors=${expectedInjectedConsoleErrors.length}`)
}
