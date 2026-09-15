import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import management from './management.js'

const components = [
  'pages/Dashboard.jsx', 'pages/Users.jsx', 'pages/AuditLog.jsx',
  'pages/Issues.jsx', 'pages/Environments.jsx', 'pages/Updates.jsx',
  'components/ImportantUpdateNotice.jsx',
]
const source = path => readFileSync(new URL(`../../${path}`, import.meta.url), 'utf8')
const variables = text => [...text.matchAll(/{{\s*(\w+)\s*}}/g)].map(match => match[1]).sort()

async function translator(language) {
  const { createInstance } = await import('i18next')
  const instance = createInstance()
  await instance.init({
    lng: language, fallbackLng: 'zh', keySeparator: false,
    interpolation: { escapeValue: false },
    resources: {
      zh: { translation: management.zh },
      en: { translation: management.en },
    },
  })
  return instance
}

test('管理词条均使用 flat management 前缀且中英文键和插值一致', () => {
  assert.deepEqual(Object.keys(management.zh).sort(), Object.keys(management.en).sort())
  for (const [key, value] of Object.entries(management.zh)) {
    assert.ok(key.startsWith('management.'), key)
    assert.equal(typeof value, 'string', key)
    assert.equal(typeof management.en[key], 'string', key)
    assert.ok(value.trim() && management.en[key].trim(), key)
    assert.deepEqual(variables(value), variables(management.en[key]), key)
    assert.doesNotMatch(management.en[key], /\p{Script=Han}/u, key)
  }
})

test('七个组件引用的固定词条均已登记，无硬编码中文或语言 key 重挂载', () => {
  for (const path of components) {
    const text = source(path)
    assert.match(text, /useI18n\(\)/, path)
    assert.doesNotMatch(text, /\p{Script=Han}/u, path)
    assert.doesNotMatch(text, /key=\{(?:language|i18n\.language)\}/, path)
    for (const [, key] of text.matchAll(/['"](management\.[\w.]+)['"]/g)) {
      assert.ok(Object.hasOwn(management.zh, key), `${path}: ${key}`)
      assert.ok(Object.hasOwn(management.en, key), `${path}: ${key}`)
    }
  }
})

test('真实 i18next 支持 flat 键、计数和语言切换，不产生未替换插值', async () => {
  const instance = await translator('zh')
  assert.equal(instance.t('management.dashboard'), '仪表盘')
  assert.equal(instance.t('management.weekRuns', { count: 2 }), '本周共执行 2 次')
  await instance.changeLanguage('en')
  assert.equal(instance.t('management.dashboard'), 'Dashboard')
  for (const count of [0, 1, 2, 1000]) {
    assert.equal(instance.t('management.weekRuns', { count }), `Total runs this week: ${count}`)
    assert.equal(instance.t('management.weekSuccess', { count }), `Successful runs: ${count}`)
  }
  assert.equal(instance.t('management.deleteUserConfirm', { username: '<用户 & name>' }), 'Delete user “<用户 & name>”?')
  assert.equal(instance.t('management.updates.version', { version: '1.2.4' }), 'Version v1.2.4')
  assert.equal(instance.t('management.env.outputExample'), 'e.g. D:\\output')
})

test('审计动作、工单筛选与用户权限仍提交原始标识', () => {
  const audit = source('pages/AuditLog.jsx')
  for (const action of ['login', 'login_failed', 'logout', 'upload_script', 'upload_version', 'disable_script', 'enable_script', 'execute_script', 'cancel_run', 'create_user', 'update_user', 'delete_user']) {
    assert.match(audit, new RegExp(`\\b${action}: 'management\\.`))
  }
  assert.ok(audit.includes("params.set('action', action)"))
  assert.ok(audit.includes("params.set('username', username)"))
  const users = source('pages/Users.jsx')
  for (const role of ['operator', 'developer', 'admin']) assert.ok(users.includes(`${role}: 'management.role.${role}'`))
  assert.ok(users.includes("status: target.status === 'active' ? 'disabled' : 'active'"))
  const issues = source('pages/Issues.jsx')
  assert.ok(issues.includes("value: 'open'"))
  assert.ok(issues.includes("value: 'resolved'"))
  assert.ok(issues.includes('`/api/issues/${resolveModal.id}/resolve`, values'))
  const envs = source('pages/Environments.jsx')
  assert.ok(envs.includes("venv_status: 'managed'"))
  assert.ok(envs.includes('extra_env: Object.keys(extraEnv).length > 0 ? extraEnv : null'))
})

test('历史发布内容和工单用户内容直接显示，不送入翻译函数', () => {
  for (const path of ['pages/Updates.jsx', 'components/ImportantUpdateNotice.jsx']) {
    const text = source(path)
    assert.ok(text.includes('{currentRelease.title}'))
    assert.ok(text.includes('{currentRelease.summary}'))
    assert.ok(text.includes('{section.title}'))
    assert.ok(text.includes('{item}'))
    assert.doesNotMatch(text, /\bt\((?:currentRelease|release|section|item)[.,)]/)
  }
  const issues = source('pages/Issues.jsx')
  for (const field of ['title', 'description', 'error_msg', 'resolve_note']) {
    assert.ok(issues.includes(`{detailModal.${field}}`), field)
  }
  assert.ok(issues.includes('{detailParams.text}'))
  assert.ok(issues.includes("Symbol('emptyIssueLog')"))
  assert.ok(issues.includes("Symbol('failedIssueLog')"))
  assert.ok(issues.includes("t('management.issues.logFailed') : detailLog"))
})

test('可提交表单和表格提供翻译后的确认、取消与空状态', () => {
  for (const path of ['pages/Users.jsx', 'pages/Issues.jsx', 'pages/Environments.jsx']) {
    const text = source(path)
    assert.ok(text.includes("cancelText={t('management.cancel')}"), path)
    assert.ok(text.includes('okText={t('), path)
  }
  for (const path of components.filter(path => !path.includes('Updates') && !path.includes('ImportantUpdateNotice'))) {
    assert.ok(source(path).includes("locale={{ emptyText: t('management.empty') }}"), path)
  }
})
