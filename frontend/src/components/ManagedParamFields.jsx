import { Alert, Form, Input, InputNumber, Select, Switch } from 'antd'

function rulesFor(param) {
  const rules = []
  if (param.required && param.type !== 'checkbox') {
    rules.push({ required: true, message: `请填写${param.label || param.key}` })
  }
  if (param.type === 'number' && (param.min != null || param.max != null)) {
    rules.push({
      validator: (_, value) => {
        if (value == null) return Promise.resolve()
        if (param.min != null && value < param.min) return Promise.reject(new Error(`值不能小于 ${param.min}`))
        if (param.max != null && value > param.max) return Promise.reject(new Error(`值不能大于 ${param.max}`))
        return Promise.resolve()
      },
    })
  }
  return rules
}

function controlFor(param) {
  if (param.type === 'number') {
    return <InputNumber min={param.min} max={param.max} disabled={param.disabled} style={{ width: '100%' }} />
  }
  if (param.type === 'select') {
    return <Select disabled={param.disabled} options={(param.options || []).map(option => ({ label: option, value: option }))} />
  }
  if (param.type === 'checkbox') return <Switch disabled={param.disabled} />
  const isPath = param.type === 'file' || param.type === 'folder'
  return <Input disabled={param.disabled} placeholder={isPath ? '填写被控设备上的绝对路径' : undefined} />
}

export default function ManagedParamFields({ params = [], disabled = false }) {
  if (!params.length) {
    return <div className="managed-param-empty">此脚本无需配置参数</div>
  }

  const hasPath = params.some(param => param.type === 'file' || param.type === 'folder')
  return (
    <div className="managed-param-fields">
      {hasPath && (
        <Alert type="info" showIcon title="文件和目录必须使用被控设备上的绝对路径" />
      )}
      {params.map(param => (
        <Form.Item
          key={param.key}
          name={['params', param.key]}
          label={param.label || param.key}
          tooltip={param.help || undefined}
          rules={rulesFor(param)}
          valuePropName={param.type === 'checkbox' ? 'checked' : 'value'}
        >
          {controlFor({ ...param, disabled })}
        </Form.Item>
      ))}
    </div>
  )
}
