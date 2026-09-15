import { useEffect, useRef, useState } from 'react'
import { Alert, Card, Form, Input, InputNumber, Button, message, Spin, Popconfirm, Select, Space, Tag } from 'antd'
import { DownloadOutlined, NotificationOutlined, ReloadOutlined, SaveOutlined, UndoOutlined, SettingOutlined } from '@ant-design/icons'
import { Link } from 'react-router-dom'
import api from '../api/client'
import { checkUpdate, downloadAndInstallUpdate, loadUpdateStatus } from '../api/localUpdate'
import { useConnection } from '../contexts/ConnectionContext'
import { useAuth } from '../contexts/AuthContext'
import DiagnosticSettings from '../components/DiagnosticSettings'
import { useI18n } from '../i18n/useI18n'
import { safeError } from '../utils/safeError'

const updateStateSummary = {
  available: 'workspace.update.available',
  downloading: 'workspace.update.downloading',
  verified: 'workspace.update.verified',
  'waiting-for-idle': 'workspace.update.waiting',
  installing: 'workspace.update.installing',
}

const updateStateColor = {
  available: 'blue',
  downloading: 'processing',
  verified: 'green',
  'waiting-for-idle': 'orange',
  installing: 'processing',
}

export default function Settings() {
  const { t } = useI18n()
  // Keep async notifications current without reloading an edited form on language changes.
  const loadT = useRef(t)
  useEffect(() => { loadT.current = t }, [t])
  const { user } = useAuth()
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [updateBusy, setUpdateBusy] = useState(false)
  const [updateState, setUpdateState] = useState({ state: 'idle' })
  const [form] = Form.useForm()
  const { agentOnline, localApi } = useConnection()

  useEffect(() => {
    setLoading(true)
    api.get('/api/settings')
      .then(r => form.setFieldsValue({
        gitee_update_repository: 'chuzifeng/auto-script_-hub',
        update_channel: 'stable',
        ...r.data,
        update_manifest_urls: (r.data.update_manifest_urls || []).join('\n'),
      }))
      .catch(() => message.error(loadT.current('workspace.settings.loadFailed')))
      .finally(() => setLoading(false))
  }, [form])

  useEffect(() => {
    if (!agentOnline) return
    loadUpdateStatus(localApi).then(setUpdateState).catch(() => {})
  }, [agentOnline, localApi])

  useEffect(() => {
    if (!agentOnline || updateState.state !== 'downloading') return undefined
    const interval = setInterval(() => {
      loadUpdateStatus(localApi).then(setUpdateState).catch(() => {})
    }, 1000)
    return () => clearInterval(interval)
  }, [agentOnline, localApi, updateState.state])

  const runUpdateAction = async (action) => {
    setUpdateBusy(true)
    try {
      const result = action === 'install'
        ? await downloadAndInstallUpdate(localApi)
        : await checkUpdate(localApi)
      setUpdateState(result)
      if (action === 'check') {
        if (result.state === 'available') message.info(t('workspace.update.found'))
        else message.info(t('workspace.update.checked'))
      } else if (result.state === 'downloading') message.info(t('workspace.update.background'))
      else if (result.state === 'installing') message.success(t('workspace.update.restarting'))
      else if (result.state === 'waiting-for-idle') message.info(t('workspace.update.waitNotice'))
      else message.info(t('workspace.update.none'))
    } catch (error) {
      const detail = safeError(error, t('workspace.actionFailed'))
      message.error(t('workspace.update.failed', { detail }))
    } finally {
      setUpdateBusy(false)
    }
  }

  const onSave = async (values) => {
    setSaving(true)
    try {
      const payload = {
        ...values,
        update_manifest_urls: (values.update_manifest_urls || '')
          .split(/\r?\n/)
          .map(value => value.trim())
          .filter(Boolean),
      }
      await api.put('/api/settings', payload)
      message.success(t('workspace.settings.saved'))
    } catch (e) {
      message.error(safeError(e, t('workspace.saveFailed')))
    } finally {
      setSaving(false)
    }
  }

  const onReset = async () => {
    try {
      await api.delete('/api/settings')
      form.resetFields()
      message.success(t('workspace.settings.resetDone'))
    } catch {
      message.error(t('workspace.settings.resetFailed'))
    }
  }

  const canInstallUpdate = ['available', 'verified', 'waiting-for-idle'].includes(updateState.state)
  const updateSummary = updateState.error
    ? t('workspace.update.unknown')
    : updateStateSummary[updateState.state]
      ? t(updateStateSummary[updateState.state])
      : t(updateState.version ? 'workspace.update.latest' : 'workspace.update.unchecked')

  if (loading) return <Spin size="large" style={{ display: 'block', marginTop: 100 }} />

  return (
    <div>
      <h2 style={{ marginBottom: 16 }}><SettingOutlined /> {t('workspace.settings.title')}</h2>

      <Card style={{ maxWidth: 600 }}>
        <Form form={form} layout="vertical" onFinish={onSave}>
          <Form.Item name="server_url" label={t('workspace.settings.server')}>
            <Input placeholder={t('workspace.settings.serverExample')} />
          </Form.Item>
          <Form.Item name="script_download_dir" label={t('workspace.settings.downloadDir')}>
            <Input placeholder={t('workspace.settings.downloadExample')} />
          </Form.Item>
          <Form.Item name="output_dir" label={t('workspace.settings.outputDir')}>
            <Input placeholder={t('workspace.settings.outputExample')} />
          </Form.Item>
          <Form.Item name="default_browser_path" label={t('workspace.settings.browser')}>
            <Input placeholder={t('workspace.settings.browserExample')} />
          </Form.Item>
          <Form.Item name="browser_debug_port" label={t('workspace.settings.debugPort')}>
            <InputNumber min={0} max={65535} style={{ width: '100%' }} placeholder="9222" />
          </Form.Item>
          <Form.Item name="proxy" label={t('workspace.settings.proxy')}>
            <Input placeholder={t('workspace.settings.proxyExample')} />
          </Form.Item>
          <Form.Item name="pip_index_url" label={t('workspace.settings.pip')}>
            <Input placeholder={t('workspace.settings.pipExample')} />
          </Form.Item>
          <Form.Item
            name="gitee_update_repository"
            label={t('workspace.settings.repository')}
            extra={t('workspace.settings.repositoryHelp')}
          >
            <Input placeholder="chuzifeng/auto-script_-hub" />
          </Form.Item>
          <Form.Item name="update_channel" label={t('workspace.settings.channel')}>
            <Select options={[{ value: 'stable', label: t('workspace.settings.stable') }, { value: 'beta', label: t('workspace.settings.beta') }]} />
          </Form.Item>
          <Form.Item
            name="update_manifest_urls"
            label={t('workspace.settings.manifests')}
            extra={t('workspace.settings.manifestsHelp')}
          >
            <Input.TextArea rows={4} placeholder={'http://server.example.com/releases/autoscript-hub-update.json\nhttps://gitee.com/.../autoscript-hub-update.json'} />
          </Form.Item>

          <div style={{ display: 'flex', gap: 8 }}>
            <Button type="primary" htmlType="submit" icon={<SaveOutlined />} loading={saving}>
              {t('workspace.settings.save')}
            </Button>
            <Popconfirm
              title={t('workspace.settings.resetConfirm')}
              onConfirm={onReset}
              okText={t('workspace.settings.confirmReset')}
              cancelText={t('workspace.cancel')}
            >
              <Button icon={<UndoOutlined />}>{t('workspace.settings.reset')}</Button>
            </Popconfirm>
          </div>
        </Form>
      </Card>

      {user?.role === 'admin' && <DiagnosticSettings />}

      <Card
        title={t('workspace.update.title')}
        extra={<Link to="/updates"><NotificationOutlined /> {t('workspace.update.notes')}</Link>}
        style={{ maxWidth: 600, marginTop: 16 }}
      >
        {!agentOnline && <Alert type="info" showIcon message={t('workspace.update.windowsOnly')} />}
        {agentOnline && (
          <Space direction="vertical" style={{ width: '100%' }}>
            <div>
              {t('workspace.statusColon')}<Tag>{t(`workspace.update.state.${updateState.state || 'idle'}`, { defaultValue: updateState.state || 'idle' })}</Tag>
              <Tag color={updateStateColor[updateState.state] || (updateState.error ? 'orange' : 'green')}>
                {updateSummary}
              </Tag>
            </div>
            <Space size="large" wrap>
              <span>{t('workspace.update.installedVersion')}{updateState.current_version || '-'}</span>
              <span>{t('workspace.update.latestVersion')}{updateState.version || t('workspace.update.notChecked')}</span>
            </Space>
            {updateState.error && <Alert type="warning" showIcon message={updateState.error} />}
            <Space>
              <Button icon={<ReloadOutlined />} loading={updateBusy} onClick={() => runUpdateAction('check')}>
                {t('workspace.update.check')}
              </Button>
              <Button
                type="primary"
                icon={<DownloadOutlined />}
                loading={updateBusy || updateState.state === 'downloading'}
                disabled={!canInstallUpdate}
                onClick={() => runUpdateAction('install')}
              >
                {t('workspace.update.install')}
              </Button>
            </Space>
            <div style={{ color: '#888' }}>{t('workspace.update.installHelp')}</div>
          </Space>
        )}
      </Card>
    </div>
  )
}
