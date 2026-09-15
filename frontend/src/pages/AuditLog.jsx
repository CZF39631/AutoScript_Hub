import { useEffect, useState } from 'react'
import { Table, Input, Select, Space, message } from 'antd'
import api from '../api/client'
import { formatServerTime } from '../utils/dateTime'
import { safeError } from '../utils/safeError'
import { useI18n } from '../i18n/useI18n'

// Values remain the API's audit action identifiers.
const actionKeys = {
  login: 'management.audit.login',
  login_failed: 'management.audit.loginFailed',
  logout: 'management.audit.logout',
  upload_script: 'management.audit.uploadScript',
  upload_version: 'management.audit.uploadVersion',
  disable_script: 'management.audit.disableScript',
  enable_script: 'management.audit.enableScript',
  execute_script: 'management.audit.executeScript',
  cancel_run: 'management.audit.cancelRun',
  create_user: 'management.createUser',
  update_user: 'management.audit.updateUser',
  delete_user: 'management.audit.deleteUser',
}

export default function AuditLog() {
  const { t } = useI18n()
  const actionOptions = Object.entries(actionKeys).map(([value, key]) => ({ label: t(key), value }))
  const [logs, setLogs] = useState([])
  const [loading, setLoading] = useState(true)
  const [action, setAction] = useState(undefined)
  const [username, setUsername] = useState('')

  const load = () => {
    setLoading(true)
    const params = new URLSearchParams()
    if (action) params.set('action', action)
    if (username) params.set('username', username)
    params.set('limit', '200')
    api.get(`/api/audit?${params.toString()}`)
      .then(r => setLogs(r.data))
      .catch(error => message.error(safeError(error, t('management.audit.loadFailed'))))
      .finally(() => setLoading(false))
  }

  // Language changes only rerender labels; keep the existing query lifecycle.
  useEffect(load, [action, username]) // eslint-disable-line react-hooks/exhaustive-deps

  const columns = [
    { title: t('management.time'), dataIndex: 'created_at', key: 'time', width: 170,
      render: formatServerTime },
    { title: t('management.user'), dataIndex: 'username', key: 'user', width: 100 },
    { title: t('management.actions'), dataIndex: 'action', key: 'action', width: 110,
      render: (a) => Object.hasOwn(actionKeys, a) ? t(actionKeys[a]) : a },
    { title: t('management.audit.target'), key: 'target', width: 100,
      render: (_, r) => r.target_type ? `${r.target_type} #${r.target_id}` : '-' },
    { title: t('management.details'), dataIndex: 'detail', key: 'detail', ellipsis: true },
    { title: 'IP', dataIndex: 'ip_address', key: 'ip', width: 130 },
  ]

  return (
    <div>
      <h2>{t('management.audit.title')}</h2>
      <Space style={{ marginBottom: 16 }}>
        <Select placeholder={t('management.audit.actionType')} value={action} onChange={setAction}
          options={actionOptions} style={{ width: 150 }} allowClear />
        <Input placeholder={t('management.username')} value={username}
          onChange={e => setUsername(e.target.value)} style={{ width: 150 }} allowClear />
      </Space>
      <Table locale={{ emptyText: t('management.empty') }} dataSource={logs} columns={columns} rowKey="id" loading={loading}
        size="small" pagination={{ pageSize: 20 }} />
    </div>
  )
}
