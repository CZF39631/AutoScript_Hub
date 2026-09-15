import React from 'react'
import { Form, Input, InputNumber, Select, Switch, Button, Space, Modal, message } from 'antd'
import { FolderOpenOutlined, FileOutlined } from '@ant-design/icons'
import { useI18n } from '../i18n/useI18n'
import { safeError } from '../utils/safeError'

async function nativeOpenFile() {
  if (window.pywebview && window.pywebview.api) {
    return await window.pywebview.api.openFileDialog()
  }
  return null
}

async function nativeOpenFolder() {
  if (window.pywebview && window.pywebview.api) {
    return await window.pywebview.api.openFolderDialog()
  }
  return null
}

function FilePicker({ type, value, onChange, placeholder }) {
  const { t } = useI18n()
  const pick = async () => {
    const path = type === 'file' ? await nativeOpenFile() : await nativeOpenFolder()
    if (path) {
      onChange(path)
    } else {
      message.info(t('workspace.params.manualPath'))
    }
  }

  return (
    <Space.Compact style={{ width: '100%' }}>
      <Input value={value} onChange={e => onChange(e.target.value)} placeholder={placeholder} />
      <Button icon={type === 'file' ? <FileOutlined /> : <FolderOpenOutlined />} onClick={pick}>
        {t(type === 'file' ? 'workspace.chooseFile' : 'workspace.params.chooseFolder')}
      </Button>
    </Space.Compact>
  )
}

function buildRules(p, t) {
  const rules = []
  if (p.required) {
    rules.push({ required: true, message: t('workspace.params.required', { name: p.label || p.key }) })
  }

  if (p.type === 'number') {
    if (p.min != null || p.max != null) {
      rules.push({
        validator: (_, value) => {
          if (value == null) return Promise.resolve()
          if (p.min != null && value < p.min) return Promise.reject(new Error(t('workspace.params.min', { min: p.min })))
          if (p.max != null && value > p.max) return Promise.reject(new Error(t('workspace.params.max', { max: p.max })))
          return Promise.resolve()
        },
      })
    }
  }

  if (p.type === 'select') {
    const opts = p.options || []
    if (opts.length > 0) {
      rules.push({
        validator: (_, value) => {
          if (!value) return Promise.resolve()
          if (!opts.includes(value)) return Promise.reject(new Error(t('workspace.params.invalidOption')))
          return Promise.resolve()
        },
      })
    }
  }

  return rules
}

/**
 * Parameter form with preset support (design §5.3).
 *
 * Presets come from two sources:
 *   - developer: baked into script's config_json "presets" array (read-only)
 *   - personal: stored per-user in user_presets table (CRUD via /api/scripts/{id}/presets)
 *
 * Optional props:
 *   - presets: { developer: [...], personal: [...] }   loaded by parent from /api/scripts/{id}/presets
 *   - onSavePreset(name, values): persist current form values as a new personal preset
 *   - onDeletePreset(presetId): remove a personal preset by id
 */
export default function ParamForm({ params, initialValues, presets, onSubmit, onSave, onSavePreset, onDeletePreset }) {
  const { t } = useI18n()
  const [form] = Form.useForm()
  const [remember, setRemember] = React.useState(true)
  const [selectedPresetKey, setSelectedPresetKey] = React.useState(null)
  const [savePresetModal, setSavePresetModal] = React.useState(false)
  const [presetForm] = Form.useForm()

  const developerPresets = presets?.developer || []
  const personalPresets = presets?.personal || []

  const presetOptions = [
    ...developerPresets.map((p, i) => ({
      label: t('workspace.params.developerPreset', { name: p.name || t('workspace.params.unnamedPreset') }),
      value: `dev:${i}`,
    })),
    ...personalPresets.map(p => ({
      label: t('workspace.params.personalPreset', { name: p.name || t('workspace.params.unnamedPreset') }),
      value: `per:${p.id}`,
    })),
  ]

  const findPreset = (key) => {
    if (!key) return null
    if (key.startsWith('dev:')) {
      const i = parseInt(key.slice(4))
      return developerPresets[i]
    }
    if (key.startsWith('per:')) {
      const id = parseInt(key.slice(4))
      return personalPresets.find(p => p.id === id)
    }
    return null
  }

  const applyPreset = () => {
    const preset = findPreset(selectedPresetKey)
    if (preset && preset.values) {
      form.setFieldsValue(preset.values)
      message.success(t('workspace.params.applied', { name: preset.name || t('workspace.params.unnamedPreset') }))
    }
  }

  const removePreset = () => {
    if (!selectedPresetKey || !selectedPresetKey.startsWith('per:')) {
      message.info(t('workspace.params.personalOnly'))
      return
    }
    const id = parseInt(selectedPresetKey.slice(4))
    if (onDeletePreset) onDeletePreset(id)
    setSelectedPresetKey(null)
  }

  const submitSavePreset = async (values) => {
    if (onSavePreset) {
      try {
        await onSavePreset(values.name, form.getFieldsValue())
        setSavePresetModal(false)
        presetForm.resetFields()
      } catch (e) {
        message.error(safeError(e, t('workspace.saveFailed')))
      }
    } else {
      setSavePresetModal(false)
    }
  }

  const defaults = params.reduce((acc, p) => {
    if (p.default !== undefined) acc[p.key] = p.default
    return acc
  }, {})

  const initVals = { ...defaults, ...initialValues }

  const onFinish = (values) => {
    if (remember && onSave) onSave(values)
    onSubmit(values)
  }

  const showPresetBar = presetOptions.length > 0 || onSavePreset

  return (
    <>
      {showPresetBar && (
        <div className="preset-bar">
          <Space wrap>
            <span style={{ fontWeight: 500 }}>{t('workspace.params.presets')}</span>
            <Select
              style={{ width: 240 }}
              placeholder={t('workspace.params.choosePreset')}
              value={selectedPresetKey}
              onChange={setSelectedPresetKey}
              options={presetOptions}
              allowClear
            />
            <Button onClick={applyPreset} disabled={!selectedPresetKey}>{t('workspace.params.apply')}</Button>
            {onDeletePreset && (
              <Button danger onClick={removePreset} disabled={!selectedPresetKey || !selectedPresetKey.startsWith('per:')}>{t('workspace.delete')}</Button>
            )}
            {onSavePreset && (
              <Button onClick={() => setSavePresetModal(true)}>{t('workspace.params.saveAs')}</Button>
            )}
          </Space>
        </div>
      )}

      <Form form={form} layout="horizontal" onFinish={onFinish} initialValues={initVals}>
        {params.map(p => {
          const rules = buildRules(p, t)
          switch (p.type) {
            case 'number':
              return (
                <Form.Item key={p.key} name={p.key} label={p.label} rules={rules} extra={p.help}>
                  <InputNumber min={p.min} max={p.max} style={{ width: '100%' }} />
                </Form.Item>
              )
            case 'select':
              return (
                <Form.Item key={p.key} name={p.key} label={p.label} rules={rules}>
                  <Select options={(p.options || []).map(o => ({ label: o, value: o }))} />
                </Form.Item>
              )
            case 'checkbox':
              return (
                <Form.Item key={p.key} name={p.key} label={p.label} valuePropName="checked">
                  <Switch />
                </Form.Item>
              )
            case 'file':
              return (
                <Form.Item key={p.key} name={p.key} label={p.label} rules={rules}
                  extra={p.help || t('workspace.params.fileHelp')}>
                  <FilePicker type="file" placeholder={t('workspace.params.fileExample')} />
                </Form.Item>
              )
            case 'folder':
              return (
                <Form.Item key={p.key} name={p.key} label={p.label} rules={rules}
                  extra={p.help || t('workspace.params.folderHelp')}>
                  <FilePicker type="folder" placeholder={t('workspace.params.folderExample')} />
                </Form.Item>
              )
            default:
              return (
                <Form.Item key={p.key} name={p.key} label={p.label} rules={rules}>
                  <Input />
                </Form.Item>
              )
          }
        })}
        <Form.Item>
          <Space>
            <Button type="primary" htmlType="submit">{t('workspace.params.execute')}</Button>
            {onSave && (
              <Space>
                <Switch size="small" checked={remember} onChange={setRemember} />
                <span style={{ fontSize: 13 }}>{t('workspace.params.remember')}</span>
              </Space>
            )}
          </Space>
        </Form.Item>
      </Form>

      <Modal title={t('workspace.params.savePreset')} open={savePresetModal} onCancel={() => setSavePresetModal(false)}
        onOk={() => presetForm.submit()} okText={t('workspace.save')}>
        <Form form={presetForm} layout="vertical" onFinish={submitSavePreset}>
          <Form.Item name="name" label={t('workspace.params.presetName')} rules={[{ required: true, message: t('workspace.params.presetNameRequired') }]}>
            <Input placeholder={t('workspace.params.presetExample')} />
          </Form.Item>
        </Form>
      </Modal>
    </>
  )
}
