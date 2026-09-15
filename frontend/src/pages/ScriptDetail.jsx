import { useCallback, useEffect, useRef, useState } from 'react'
import { Descriptions, Collapse, Tag, Spin, Button, Upload, Modal, Input, Form, Select, message } from 'antd'
import { UploadOutlined, PlusOutlined } from '@ant-design/icons'
import { useNavigate, useParams } from 'react-router-dom'
import { useConnection } from '../contexts/ConnectionContext'
import api from '../api/client'
import ParamForm from '../components/ParamForm'
import { formatScriptVersion } from '../utils/scriptVersion'
import { parseScriptConfig, shouldFallbackToLocal } from '../utils/groups'

import { useI18n } from '../i18n/useI18n'
import { safeError } from '../utils/safeError'

const PARAMS_STORAGE_KEY = 'autoscript_saved_params'

function loadSavedParams(scriptId) {
  try {
    const all = JSON.parse(localStorage.getItem(PARAMS_STORAGE_KEY) || '{}')
    return all[scriptId] || null
  } catch { return null }
}

function saveParams(scriptId, params) {
  try {
    const all = JSON.parse(localStorage.getItem(PARAMS_STORAGE_KEY) || '{}')
    all[scriptId] = params
    localStorage.setItem(PARAMS_STORAGE_KEY, JSON.stringify(all))
  } catch { /* ignore */ }
}

export default function ScriptDetail() {
  const { t } = useI18n()
  // Language changes must not reload the script and discard unsaved parameter edits.
  const loadT = useRef(t)
  useEffect(() => { loadT.current = t }, [t])
  const { id } = useParams()
  const nav = useNavigate()
  const { online, localApi } = useConnection()
  const [script, setScript] = useState(null)
  const [versions, setVersions] = useState([])
  const [presets, setPresets] = useState({ developer: [], personal: [] })
  const [loading, setLoading] = useState(true)
  const [savedParams, setSavedParams] = useState(null)
  const [verModalOpen, setVerModalOpen] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [environments, setEnvironments] = useState([])
  const [selectedEnvId, setSelectedEnvId] = useState(null)
  const [verForm] = Form.useForm()
  const [offlineMode, setOfflineMode] = useState(false)

  const canUpload = Boolean(script?.can_manage) && online

  const loadPresets = useCallback(() => {
    if (!online) return
    api.get(`/api/scripts/${id}/presets`).then(r => setPresets(r.data)).catch(() => {})
  }, [id, online])

  const loadFromLocal = useCallback(() => {
    localApi.get('/local/scripts').then(r => {
      const local = (r.data || []).find(s => s.id === parseInt(id))
      if (local) {
        const configJson = local.config_json || (local.config ? JSON.stringify(local.config) : '{}')
        setScript({
          id: local.id,
          name: local.name,
          description: local.description,
          category: local.category,
          latest_version: local.latest_version,
          latest_semantic_version: local.config?.version,
          status: 'active',
          type: 'local',
          updated_at: null,
          config_json: configJson,
        })
        setVersions([{ version: local.latest_version, semantic_version: local.config?.version, changelog: '', localCached: true }])
        setEnvironments([])
        setOfflineMode(true)
      } else {
        message.error(loadT.current('workspace.detail.notCached'))
      }
    }).catch(() => message.error(loadT.current('workspace.agentUnavailable'))).finally(() => setLoading(false))
  }, [id, localApi])

  const loadScript = useCallback(() => {
    setLoading(true)
    if (!online) {
      loadFromLocal()
      setSavedParams(loadSavedParams(id))
      return
    }
    api.get(`/api/scripts/${id}`).then(async s => {
      setScript(s.data)
      setOfflineMode(false)
      const [versionResult, environmentResult] = await Promise.allSettled([
        api.get(`/api/scripts/${id}/versions`),
        api.get('/api/environments'),
      ])
      if (versionResult.status === 'fulfilled') setVersions(versionResult.value.data)
      else {
        setVersions([])
        message.warning(loadT.current('workspace.detail.versionsLoadFailed'))
      }
      if (environmentResult.status === 'fulfilled') {
        const items = environmentResult.value.data
        setEnvironments(items)
        const defEnv = items.find(environment => environment.is_default)
        if (defEnv) setSelectedEnvId(defEnv.id)
      } else {
        setEnvironments([])
        message.warning(loadT.current('workspace.detail.environmentsLoadFailed'))
      }
    }).catch(error => {
      if (shouldFallbackToLocal(error)) return loadFromLocal()
      const status = error.response?.status
      if (status === 401) message.error(loadT.current('workspace.detail.sessionExpired'))
      else if (status === 403) message.error(loadT.current('workspace.detail.forbidden'))
      else if (status === 404) message.error(loadT.current('workspace.detail.notAccessible'))
      else message.error(safeError(error, loadT.current('workspace.detail.loadFailed')))
      setScript(null)
    }).finally(() => setLoading(false))

    setSavedParams(loadSavedParams(id))
    loadPresets()
  }, [id, online, loadFromLocal, loadPresets])

  useEffect(loadScript, [loadScript])

  const onSavePreset = async (name, values) => {
    await api.post(`/api/scripts/${id}/presets`, { name, values })
    message.success(t('workspace.detail.presetSaved'))
    loadPresets()
  }

  const onDeletePreset = async (presetId) => {
    try {
      await api.delete(`/api/presets/${presetId}`)
      message.success(t('workspace.detail.presetDeleted'))
      loadPresets()
    } catch (e) {
      message.error(safeError(e, t('workspace.deleteFailed')))
    }
  }

  // Offline: parse developer presets directly from the script's config_json
  // (personal presets require backend storage, so unavailable offline)
  useEffect(() => {
    if (offlineMode && script?.config_json) {
      try {
        const config = JSON.parse(script.config_json)
        const devPresets = (config.presets || []).map(p => ({
          name: p.name || '',
          values: p.values || {},
        }))
        setPresets({ developer: devPresets, personal: [] })
      } catch {
        setPresets({ developer: [], personal: [] })
      }
    }
  }, [offlineMode, script])

  const onExecute = async (params) => {
    // Offline path: submit directly to the local Agent (design §5.x offline)
    if (offlineMode || !online) {
      try {
        await localApi.post('/local/execute', {
          script_id: parseInt(id),
          params,
        })
        message.success(t('workspace.detail.offlineSubmitted'))
        nav('/runs')
      } catch (e) {
        message.error(safeError(e, t('workspace.detail.offlineFailed')))
      }
      return
    }
    try {
      await api.post('/api/runs/execute', {
        script_id: parseInt(id),
        params,
        environment_id: selectedEnvId || undefined,
      })
      message.success(t('workspace.detail.submitted'))
      nav('/runs')
    } catch (e) {
      message.error(safeError(e, t('workspace.detail.executeFailed')))
    }
  }

  const onSaveParams = (params) => {
    saveParams(id, params)
    setSavedParams(params)
    message.success(t('workspace.detail.paramsSaved'))
  }

  const onUploadVersion = async (values) => {
    const { file, changelog } = values
    if (!file || !file[0]) {
      message.error(t('workspace.chooseFileRequired'))
      return
    }
    setUploading(true)
    try {
      const formData = new FormData()
      formData.append('file', file[0].originFileObj)
      formData.append('changelog', changelog || '')
      await api.post(`/api/scripts/${id}/upload-version`, formData)
      message.success(t('workspace.detail.versionUploaded'))
      setVerModalOpen(false)
      verForm.resetFields()
      loadScript()
    } catch (e) {
      message.error(safeError(e, t('workspace.uploadFailed')))
    } finally {
      setUploading(false)
    }
  }

  if (loading) return <Spin />
  if (!script) return <div>{t('workspace.detail.notFound')}</div>

  const config = parseScriptConfig(script.config_json)
  const paramDefs = config.params || []

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <h2 style={{ margin: 0 }}>{script.name}</h2>
        {canUpload && (
          <Button icon={<PlusOutlined />} onClick={() => setVerModalOpen(true)}>{t('workspace.detail.uploadVersion')}</Button>
        )}
      </div>

      <Descriptions bordered size="small" column={1} style={{ marginBottom: 16 }}>
        <Descriptions.Item label={t('workspace.description')}>{script.description}</Descriptions.Item>
        <Descriptions.Item label={t('workspace.category')}>{script.category}</Descriptions.Item>
        <Descriptions.Item label={t('workspace.groups')}>{script.groups?.length ? script.groups.map(group => <Tag key={group.id}>{group.name}</Tag>) : <span style={{ color: '#999' }}>{t('workspace.ungrouped')}</span>}</Descriptions.Item>
        <Descriptions.Item label={t('workspace.version')}>{formatScriptVersion(script.latest_semantic_version, script.latest_version)}</Descriptions.Item>
        <Descriptions.Item label={t('workspace.status')}>
          <Tag color={script.status === 'active' ? 'green' : 'red'}>{t(`workspace.scriptState.${script.status}`, { defaultValue: script.status })}</Tag>
        </Descriptions.Item>
      </Descriptions>

      {paramDefs.length > 0 && (
        <div style={{ marginBottom: 16 }}>
          {environments.length > 0 && (
            <div style={{ marginBottom: 12 }}>
              <span style={{ marginRight: 8 }}>{t('workspace.detail.environment')}</span>
              <Select
                style={{ width: 300 }}
                placeholder={t('workspace.detail.noEnvironment')}
                allowClear
                value={selectedEnvId}
                onChange={setSelectedEnvId}
                options={environments.map(e => ({
                  label: e.is_default ? t('workspace.detail.defaultEnvironment', { name: e.name }) : e.name,
                  value: e.id,
                }))}
              />
            </div>
          )}
          <h3 style={{ marginBottom: 8 }}>{t('workspace.detail.params')}</h3>
          <ParamForm
            params={paramDefs}
            initialValues={savedParams}
            presets={presets}
            onSubmit={onExecute}
            onSave={onSaveParams}
            onSavePreset={onSavePreset}
            onDeletePreset={onDeletePreset}
          />
        </div>
      )}

      <Collapse items={versions.map(v => ({
        key: v.version,
        label: `${formatScriptVersion(v.semantic_version, v.version)} - ${(v.localCached ? t('workspace.detail.cachedVersion') : (v.changelog || '')).substring(0, 50)}`,
        children: <p>{v.localCached ? t('workspace.detail.cachedVersion') : v.changelog}</p>,
      }))} />

      <Modal title={t('workspace.detail.uploadVersion')} open={verModalOpen} onCancel={() => setVerModalOpen(false)}
        confirmLoading={uploading} onOk={() => verForm.submit()} okText={t('workspace.upload')}>
        <Form form={verForm} layout="vertical" onFinish={onUploadVersion}>
          <Form.Item name="file" label={t('workspace.scriptFile')} rules={[{ required: true }]}
            valuePropName="fileList" getValueFromEvent={(e) => Array.isArray(e) ? e : e?.fileList}>
            <Upload beforeUpload={() => false} maxCount={1} accept=".py,.zip">
              <Button icon={<UploadOutlined />}>{t('workspace.chooseFile')}</Button>
            </Upload>
          </Form.Item>
          <Form.Item name="changelog" label={t('workspace.changelog')}>
            <Input.TextArea rows={3} placeholder={t('workspace.detail.changelogPlaceholder')} />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
