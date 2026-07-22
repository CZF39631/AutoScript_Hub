import test from 'node:test'
import assert from 'node:assert/strict'

import {
  canOpenResultLocally,
  firstResultPath,
  loadRunDetail,
  loadRunList,
  loadRunLog,
  loadScriptCollections,
} from './offlineData.js'


function client(routes) {
  return {
    async get(path) {
      if (!(path in routes)) throw new Error(`unexpected route ${path}`)
      return { data: routes[path] }
    },
  }
}


test('offline script collection comes from the local Agent', async () => {
  const localApi = client({
    '/local/scripts': [{ id: 4, name: 'Cached', latest_version: 2 }],
  })

  const result = await loadScriptCollections({ online: false, api: null, localApi })

  assert.deepEqual(result, {
    mine: [{ id: 4, name: 'Cached', latest_version: 2, local_only: true }],
    marketplace: [],
  })
})


test('offline runs, detail and logs use local Agent routes', async () => {
  const local = {
    local_run_id: 'L2',
    script_id: 4,
    script_version: 2,
    script_name: 'Cached',
    status: 'success',
    params: { q: 'value' },
    started_at: 100,
    finished_at: 110,
    result_files: '[{"name":"report.xlsx","path":"C:/out/report.xlsx","exists":true}]',
  }
  const localApi = client({
    '/local/runs': [local],
    '/local/runs/L2': local,
    '/local/runs/L2/log': { log: 'finished' },
  })

  const runs = await loadRunList({ online: false, api: null, localApi })
  const detail = await loadRunDetail({ id: 'L2', online: false, api: null, localApi })
  const log = await loadRunLog({ id: 'L2', localOnly: true, api: null, localApi })

  assert.equal(runs[0].id, 'L2')
  assert.equal(runs[0].local_only, true)
  assert.equal(detail.params, JSON.stringify({ q: 'value' }))
  assert.deepEqual(log, { log: 'finished' })
})


test('result helpers support historical paths and require the executing Agent', () => {
  assert.equal(firstResultPath('"C:/out/old.xlsx"'), 'C:/out/old.xlsx')
  assert.equal(firstResultPath('["C:/out/old-list.xlsx"]'), 'C:/out/old-list.xlsx')
  assert.equal(
    firstResultPath('[{"name":"new.xlsx","path":"C:/out/new.xlsx"}]'),
    'C:/out/new.xlsx',
  )
  assert.equal(canOpenResultLocally({ local_only: true }, true, null), true)
  assert.equal(canOpenResultLocally({ agent_id: 7 }, true, 7), true)
  assert.equal(canOpenResultLocally({ agent_id: 8 }, true, 7), false)
  assert.equal(canOpenResultLocally({ agent_id: 7 }, false, 7), false)
})
