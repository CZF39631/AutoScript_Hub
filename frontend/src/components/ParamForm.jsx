import React from 'react'
import { Form, Input, InputNumber, Select, Switch, Button, Space, message } from 'antd'
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

export default function ParamForm({ params, initialValues, onSubmit, onSave }) {
  const [form] = Form.useForm()
  const [remember, setRemember] = React.useState(true)

  const defaults = params.reduce((acc, p) => {
    if (p.default !== undefined) acc[p.key] = p.default
    return acc
  }, {})

  const initVals = { ...defaults, ...initialValues }

  const onFinish = (values) => {
    if (remember && onSave) onSave(values)
    onSubmit(values)
  }

  return (
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
                <FilePicker type="file" placeholder="文件绝对路径，如 C:\data\urls.txt" />
              </Form.Item>
            )
          case 'folder':
            return (
              <Form.Item key={p.key} name={p.key} label={p.label} rules={rules}
                extra={p.help || '选择目录或手动输入绝对路径'}>
                <FilePicker type="folder" placeholder="目录绝对路径，如 C:\data\output" />
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
  )
}
