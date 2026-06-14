import React from 'react'
import { Form, Input, InputNumber, Select, Switch, Button, Space, Modal, message } from 'antd'
import { FolderOpenOutlined, FileOutlined } from '@ant-design/icons'

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
  const pick = async () => {
    const path = type === 'file' ? await nativeOpenFile() : await nativeOpenFolder()
    if (path) {
      onChange(path)
    } else {
      message.info('请在输入框中手动填写路径')
    }
  }

  return (
    <Space.Compact style={{ width: '100%' }}>
      <Input value={value} onChange={e => onChange(e.target.value)} placeholder={placeholder} />
      <Button icon={type === 'file' ? <FileOutlined /> : <FolderOpenOutlined />} onClick={pick}>
        {type === 'file' ? '选择文件' : '选择目录'}
      </Button>
    </Space.Compact>
  )
}

function buildRules(p) {
  const rules = []
  if (p.required) {
    rules.push({ required: true, message: `请填写${p.label || p.key}` })
  }

  if (p.type === 'number') {
    if (p.min != null || p.max != null) {
      rules.push({
        validator: (_, value) => {
          if (value == null) return Promise.resolve()
          if (p.min != null && value < p.min) return Promise.reject(new Error(`值不能小于${p.min}`))
          if (p.max != null && value > p.max) return Promise.reject(new Error(`值不能大于${p.max}`))
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
          if (!opts.includes(value)) return Promise.reject(new Error('无效选项'))
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
  const [form] = Form.useForm()
  const [remember, setRemember] = React.useState(true)
  const [selectedPresetKey, setSelectedPresetKey] = React.useState(null)
  const [savePresetModal, setSavePresetModal] = React.useState(false)
  const [presetForm] = Form.useForm()

  const developerPresets = presets?.developer || []
  const personalPresets = presets?.personal || []

  const presetOptions = [
    ...developerPresets.map((p, i) => ({
      label: `[开发者] ${p.name}`,
      value: `dev:${i}`,
    })),
    ...personalPresets.map(p => ({
      label: `[个人] ${p.name}`,
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
      message.success(`已应用预设: ${preset.name}`)
    }
  }

  const removePreset = () => {
    if (!selectedPresetKey || !selectedPresetKey.startsWith('per:')) {
      message.info('只能删除个人预设')
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
        message.error(e.response?.data?.detail || '保存失败')
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
        <div style={{ marginBottom: 16, padding: 12, background: '#fafafa', border: '1px solid #f0f0f0', borderRadius: 4 }}>
          <Space wrap>
            <span style={{ fontWeight: 500 }}>参数预设:</span>
            <Select
              style={{ width: 240 }}
              placeholder="选择预设以快速填充表单..."
              value={selectedPresetKey}
              onChange={setSelectedPresetKey}
              options={presetOptions}
              allowClear
            />
            <Button onClick={applyPreset} disabled={!selectedPresetKey}>应用</Button>
            {onDeletePreset && (
              <Button danger onClick={removePreset} disabled={!selectedPresetKey || !selectedPresetKey.startsWith('per:')}>删除</Button>
            )}
            {onSavePreset && (
              <Button onClick={() => setSavePresetModal(true)}>另存为预设</Button>
            )}
          </Space>
        </div>
      )}

      <Form form={form} layout="horizontal" onFinish={onFinish} initialValues={initVals}>
        {params.map(p => {
          const rules = buildRules(p)
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
                  extra={p.help || '选择文件或手动输入绝对路径'}>
                  <FilePicker type="file" placeholder="文件绝对路径,如 C:\data\urls.txt" />
                </Form.Item>
              )
            case 'folder':
              return (
                <Form.Item key={p.key} name={p.key} label={p.label} rules={rules}
                  extra={p.help || '选择目录或手动输入绝对路径'}>
                  <FilePicker type="folder" placeholder="目录绝对路径,如 C:\data\output" />
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
            <Button type="primary" htmlType="submit">执行脚本</Button>
            {onSave && (
              <Space>
                <Switch size="small" checked={remember} onChange={setRemember} />
                <span style={{ fontSize: 13 }}>记住参数</span>
              </Space>
            )}
          </Space>
        </Form.Item>
      </Form>

      <Modal title="保存为预设" open={savePresetModal} onCancel={() => setSavePresetModal(false)}
        onOk={() => presetForm.submit()} okText="保存">
        <Form form={presetForm} layout="vertical" onFinish={submitSavePreset}>
          <Form.Item name="name" label="预设名称" rules={[{ required: true, message: '请输入预设名称' }]}>
            <Input placeholder="例如:每日定时检查" />
          </Form.Item>
        </Form>
      </Modal>
    </>
  )
}
