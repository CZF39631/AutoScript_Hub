import { useEffect, useState } from 'react'
import { Alert, Table, Button, Modal, Form, Input, InputNumber, Switch, Tag, Select, Spin, Collapse, Space, Popconfirm, message } from 'antd'
import { PlusOutlined, EditOutlined, DeleteOutlined, DesktopOutlined } from '@ant-design/icons'
import api from '../api/client'
import { useConnection } from '../contexts/ConnectionContext'

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
  const { agentOnline, localApi } = useConnection()
  const [runtimeInfo, setRuntimeInfo] = useState(null)

  // Browser detection
  const [browsers, setBrowsers] = useState([])
  const [detectingBrowser, setDetectingBrowser] = useState(false)

  const load = () => {
    setLoading(true)
    api.get('/api/environments').then(r => setEnvs(r.data))
      .catch(() => message.error('加载失败'))
      .finally(() => setLoading(false))
  }

  useEffect(load, [])

  useEffect(() => {
    if (!agentOnline) {
      setRuntimeInfo(null)
      return
    }
    localApi.get('/local/runtime').then(r => setRuntimeInfo(r.data)).catch(() => setRuntimeInfo(null))
  }, [agentOnline, localApi])

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

  // --- Modal handlers ---

  const openCreate = () => {
    setEditingId(null)
    form.resetFields()
    form.setFieldsValue(emptyForm)
    setModalOpen(true)
    if (browsers.length === 0) detectBrowsers()
  }

  const openEdit = (record) => {
    setEditingId(record.id)
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
        python_version: null,
        venv_path: null,
        venv_status: 'managed',
        python_executable: null,
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
      render: () => <Tag color="green">自动隔离</Tag>,
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
        <Alert
          type={runtimeInfo?.status === 'ready' ? 'success' : 'info'}
          showIcon
          message="私有 Python 3.11.9"
          description={runtimeInfo?.status === 'ready'
            ? `已就绪：${runtimeInfo.path}。脚本依赖会按指纹自动创建、校验并复用独立环境。`
            : '请在 Windows 客户端中查看运行时状态；安装器会提供私有 Python，脚本不使用系统 Python。'}
        />
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
