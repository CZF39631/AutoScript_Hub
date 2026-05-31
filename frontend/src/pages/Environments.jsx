import React, { useEffect, useState } from 'react'
import { Table, Button, Modal, Form, Input, InputNumber, Switch, Tag, Select, Radio, Spin, Collapse, Space, Popconfirm, message } from 'antd'
import { PlusOutlined, EditOutlined, DeleteOutlined, DesktopOutlined, PythonOutlined } from '@ant-design/icons'
import api from '../api/client'

const AGENT_URL = 'http://127.0.0.1:18080'

const emptyForm = {
  name: '', browser_port: null, browser_path: null,
  python_version: null, venv_path: null, venv_status: 'none', python_executable: null,
  output_dir: null, proxy: null, extra_env: null, is_default: false,
}

export default function Environments() {
  const [envs, setEnvs] = useState([])
  const [loading, setLoading] = useState(true)
  const [modalOpen, setModalOpen] = useState(false)
  const [editingId, setEditingId] = useState(null)
  const [form] = Form.useForm()

  // Browser detection
  const [browsers, setBrowsers] = useState([])
  const [detectingBrowser, setDetectingBrowser] = useState(false)

  // Python detection
  const [pythonVersions, setPythonVersions] = useState([])
  const [detectingPython, setDetectingPython] = useState(false)

  // Venv management
  const [venvMode, setVenvMode] = useState('default')
  const [creatingVenv, setCreatingVenv] = useState(false)
  const [venvStatus, setVenvStatus] = useState('none')

  const load = () => {
    setLoading(true)
    api.get('/api/environments').then(r => setEnvs(r.data))
      .catch(() => message.error('加载失败'))
      .finally(() => setLoading(false))
  }

  useEffect(load, [])

  // --- Detection helpers ---

  const detectBrowsers = async () => {
    setDetectingBrowser(true)
    try {
      const resp = await fetch(`${AGENT_URL}/detect-browsers`)
      if (!resp.ok) throw new Error()
      const data = await resp.json()
      setBrowsers(data)
      if (data.length === 0) message.info('未检测到浏览器')
    } catch {
      message.error('检测失败，请确认 Agent 已启动')
    } finally {
      setDetectingBrowser(false)
    }
  }

  const detectPythonVersions = async () => {
    setDetectingPython(true)
    try {
      const resp = await fetch(`${AGENT_URL}/detect-python-versions`)
      if (!resp.ok) throw new Error()
      const data = await resp.json()
      setPythonVersions(data)
      if (data.length === 0) message.info('未检测到 Python')
    } catch {
      message.error('检测失败，请确认 Agent 已启动')
    } finally {
      setDetectingPython(false)
    }
  }

  // --- Venv management ---

  const createVenv = async () => {
    const pythonPath = form.getFieldValue('selected_python_path')
    const envName = form.getFieldValue('name') || 'env'
    if (!pythonPath) {
      message.error('请先选择 Python 版本')
      return
    }
    setCreatingVenv(true)
    setVenvStatus('creating')
    try {
      const slug = envName.replace(/[^a-zA-Z0-9_-]/g, '_')
      const venvPath = form.getFieldValue('venv_path') || `D:\\python项目\\AutoScript_Hub\\.envs\\${slug}`

      const resp = await fetch(`${AGENT_URL}/create-venv`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ python_executable: pythonPath, venv_path: venvPath }),
      })
      const data = await resp.json()
      if (!resp.ok) {
        message.error(data.error || '创建失败')
        setVenvStatus('none')
        return
      }
      // Find the version label for the selected python
      const selected = pythonVersions.find(v => v.path === pythonPath)
      form.setFieldsValue({
        venv_path: venvPath,
        python_executable: data.venv_python,
        python_version: selected?.version || '',
      })
      setVenvStatus('ready')
      // Save to backend immediately if editing
      if (editingId) {
        await api.put(`/api/environments/${editingId}`, {
          venv_path: venvPath,
          python_executable: data.venv_python,
          python_version: selected?.version || '',
          venv_status: 'ready',
        })
      }
      message.success('虚拟环境创建成功')
    } catch (e) {
      message.error('创建失败: ' + (e.message || '未知错误'))
      setVenvStatus('none')
    } finally {
      setCreatingVenv(false)
    }
  }

  const deleteVenv = async () => {
    const venvPath = form.getFieldValue('venv_path')
    if (!venvPath) return
    try {
      await fetch(`${AGENT_URL}/delete-venv`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ venv_path: venvPath }),
      })
      form.setFieldsValue({
        venv_path: null, python_executable: null, python_version: null,
      })
      setVenvStatus('none')
      if (editingId) {
        await api.put(`/api/environments/${editingId}`, {
          venv_path: null, python_executable: null, python_version: null, venv_status: 'none',
        })
      }
      message.success('虚拟环境已删除')
    } catch {
      message.error('删除失败')
    }
  }

  // --- Modal handlers ---

  const openCreate = () => {
    setEditingId(null)
    form.resetFields()
    form.setFieldsValue(emptyForm)
    setVenvMode('default')
    setVenvStatus('none')
    setModalOpen(true)
    if (browsers.length === 0) detectBrowsers()
    if (pythonVersions.length === 0) detectPythonVersions()
  }

  const openEdit = (record) => {
    setEditingId(record.id)
    setVenvMode(record.python_executable ? 'custom' : 'default')
    setVenvStatus(record.venv_status || (record.python_executable ? 'ready' : 'none'))
    form.setFieldsValue({
      name: record.name,
      browser_port: record.browser_port,
      browser_path: record.browser_path,
      python_version: record.python_version,
      venv_path: record.venv_path,
      venv_status: record.venv_status || 'none',
      python_executable: record.python_executable,
      output_dir: record.output_dir,
      proxy: record.proxy,
      extra_env: record.extra_env
        ? Object.entries(record.extra_env).map(([k, v]) => ({ key: k, value: v }))
        : [],
      is_default: record.is_default,
    })
    setModalOpen(true)
    if (browsers.length === 0) detectBrowsers()
    if (pythonVersions.length === 0) detectPythonVersions()
  }

  const onSubmit = async (values) => {
    try {
      const extraEnvArr = values.extra_env
      const extraEnv = {}
      if (Array.isArray(extraEnvArr)) {
        extraEnvArr.forEach(item => {
          if (item && item.key) extraEnv[item.key] = item.value || ''
        })
      }
      const payload = {
        ...values,
        venv_status: venvStatus,
        extra_env: Object.keys(extraEnv).length > 0 ? extraEnv : null,
      }
      delete payload.extra_env_raw
      delete payload.selected_python_path

      if (editingId) {
        await api.put(`/api/environments/${editingId}`, payload)
        message.success('更新成功')
      } else {
        await api.post('/api/environments', payload)
        message.success('创建成功')
      }
      setModalOpen(false)
      load()
    } catch (e) {
      message.error(e.response?.data?.detail || '操作失败')
    }
  }

  const onDelete = async (id) => {
    try {
      const env = envs.find(e => e.id === id)
      if (env?.venv_path) {
        try {
          await fetch(`${AGENT_URL}/delete-venv`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ venv_path: env.venv_path }),
          })
        } catch { /* ignore */ }
      }
      await api.delete(`/api/environments/${id}`)
      message.success('已删除')
      load()
    } catch (e) {
      message.error(e.response?.data?.detail || '删除失败')
    }
  }

  // --- Table columns ---

  const columns = [
    { title: '名称', dataIndex: 'name', key: 'name', width: 140 },
    {
      title: 'Python', key: 'python', width: 120,
      render: (_, r) => {
        if (r.venv_status === 'ready' && r.python_version)
          return <Tag color="green">venv {r.python_version}</Tag>
        if (r.venv_status === 'creating')
          return <Tag color="blue">创建中</Tag>
        return <Tag>默认</Tag>
      },
    },
    { title: '浏览器端口', dataIndex: 'browser_port', key: 'port', width: 90, render: v => v || '-' },
    { title: '浏览器路径', dataIndex: 'browser_path', key: 'bpath', ellipsis: true, render: v => v || '-' },
    { title: '输出目录', dataIndex: 'output_dir', key: 'odir', ellipsis: true, render: v => v || '-' },
    { title: '代理', dataIndex: 'proxy', key: 'proxy', width: 130, render: v => v || '-' },
    {
      title: '默认', dataIndex: 'is_default', key: 'def', width: 60,
      render: v => v ? <Tag color="blue">默认</Tag> : '-',
    },
    {
      title: '操作', key: 'action', width: 100,
      render: (_, r) => (
        <Space>
          <Button type="link" size="small" icon={<EditOutlined />} onClick={() => openEdit(r)} />
          <Popconfirm title="确定删除？关联的venv也会被删除" onConfirm={() => onDelete(r.id)} okText="删除" cancelText="取消">
            <Button type="link" size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ]

  // --- Collapse sections ---

  const collapseItems = [
    {
      key: 'python',
      label: 'Python 虚拟环境',
      children: (
        <>
          <Form.Item label="环境模式">
            <Radio.Group value={venvMode} onChange={e => setVenvMode(e.target.value)}>
              <Radio value="default">使用项目默认 (.venv)</Radio>
              <Radio value="custom">使用自定义虚拟环境</Radio>
            </Radio.Group>
          </Form.Item>
          {venvMode === 'custom' && (
            <>
              <Form.Item label="选择 Python 版本">
                <Space.Compact style={{ width: '100%' }}>
                  <Form.Item name="selected_python_path" noStyle>
                    <Select
                      placeholder="选择检测到的 Python 版本"
                      style={{ width: '100%' }}
                      options={pythonVersions.map(v => ({
                        label: `Python ${v.version} - ${v.path}`,
                        value: v.path,
                      }))}
                    />
                  </Form.Item>
                </Space.Compact>
                <div style={{ marginTop: 4 }}>
                  {detectingPython ? <Spin size="small" /> : (
                    <Button size="small" icon={<DesktopOutlined />} onClick={detectPythonVersions}>检测 Python 版本</Button>
                  )}
                </div>
              </Form.Item>
              <Form.Item name="venv_path" label="虚拟环境路径">
                <Input placeholder="如：D:\项目\.envs\my-env（留空自动生成）" />
              </Form.Item>
              <div style={{ marginBottom: 16 }}>
                {venvStatus === 'ready' ? (
                  <Space>
                    <Tag color="green">已就绪</Tag>
                    <span style={{ fontSize: 12, color: '#888' }}>{form.getFieldValue('python_executable')}</span>
                    <Popconfirm title="确定删除虚拟环境？" onConfirm={deleteVenv} okText="删除" cancelText="取消">
                      <Button size="small" danger>删除环境</Button>
                    </Popconfirm>
                  </Space>
                ) : venvStatus === 'creating' ? (
                  <Spin tip="创建中..." />
                ) : (
                  <Button type="primary" size="small" loading={creatingVenv} onClick={createVenv}>
                    创建虚拟环境
                  </Button>
                )}
              </div>
            </>
          )}
        </>
      ),
    },
    {
      key: 'browser',
      label: '浏览器配置',
      children: (
        <>
          <Form.Item name="browser_port" label="调试端口">
            <InputNumber min={0} max={65535} placeholder="如：9222" style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item label="浏览器路径">
            <Form.Item name="browser_path" noStyle>
              <Input placeholder="手动输入或从下方选择" />
            </Form.Item>
            <div style={{ marginTop: 4 }}>
              {detectingBrowser ? <Spin size="small" /> : (
                browsers.length > 0 ? (
                  <Select
                    style={{ width: '100%' }}
                    placeholder="检测到以下浏览器，点击选择"
                    allowClear
                    onChange={path => form.setFieldsValue({ browser_path: path })}
                    options={browsers.map(b => ({ label: `${b.name} - ${b.path}`, value: b.path }))}
                  />
                ) : (
                  <Button size="small" icon={<DesktopOutlined />} onClick={detectBrowsers}>检测浏览器</Button>
                )
              )}
            </div>
          </Form.Item>
        </>
      ),
    },
    {
      key: 'network',
      label: '网络配置',
      children: (
        <Form.Item name="proxy" label="代理地址">
          <Input placeholder="如：http://127.0.0.1:7890" />
        </Form.Item>
      ),
    },
    {
      key: 'advanced',
      label: '高级设置',
      children: (
        <>
          <Form.Item name="output_dir" label="输出目录">
            <Input placeholder="如：D:\output" />
          </Form.Item>
          <Form.List name="extra_env">
            {(fields, { add, remove }) => (
              <>
                <div style={{ marginBottom: 8 }}>
                  <Button size="small" onClick={() => add()} icon={<PlusOutlined />}>添加环境变量</Button>
                </div>
                {fields.map(({ key, name, ...restField }) => (
                  <Space key={key} style={{ display: 'flex', marginBottom: 8 }} align="baseline">
                    <Form.Item {...restField} name={[name, 'key']} rules={[{ required: true, message: '变量名' }]}>
                      <Input placeholder="变量名" style={{ width: 160 }} />
                    </Form.Item>
                    <Form.Item {...restField} name={[name, 'value']}>
                      <Input placeholder="变量值" style={{ width: 240 }} />
                    </Form.Item>
                    <Button type="link" danger size="small" onClick={() => remove(name)}>删除</Button>
                  </Space>
                ))}
              </>
            )}
          </Form.List>
        </>
      ),
    },
  ]

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <h2 style={{ margin: 0 }}>环境管理</h2>
        <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>创建环境</Button>
      </div>

      <Table dataSource={envs} columns={columns} rowKey="id" loading={loading} />

      <Modal
        title={editingId ? '编辑环境' : '创建环境'}
        open={modalOpen}
        onCancel={() => setModalOpen(false)}
        onOk={() => form.submit()}
        okText={editingId ? '保存' : '创建'}
        width={600}
      >
        <Form form={form} layout="vertical" onFinish={onSubmit} initialValues={emptyForm}>
          <Form.Item name="name" label="环境名称" rules={[{ required: true, message: '请输入名称' }]}>
            <Input placeholder="如：Chrome生产环境" />
          </Form.Item>
          <Form.Item name="is_default" label="设为默认环境" valuePropName="checked">
            <Switch />
          </Form.Item>
          <Collapse ghost items={collapseItems} defaultActiveKey={['python']} style={{ marginBottom: 16 }} />
        </Form>
      </Modal>
    </div>
  )
}
