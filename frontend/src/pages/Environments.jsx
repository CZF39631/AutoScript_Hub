import { useEffect, useState } from 'react'
import { Alert, Table, Button, Modal, Form, Input, InputNumber, Switch, Tag, Select, Spin, Collapse, Space, Popconfirm, message } from 'antd'
import { PlusOutlined, EditOutlined, DeleteOutlined, DesktopOutlined } from '@ant-design/icons'
import api from '../api/client'
import { useConnection } from '../contexts/ConnectionContext'
import { useI18n } from '../i18n/useI18n'
import { safeError } from '../utils/safeError'

const emptyForm = {
  name: '', browser_port: null, browser_path: null,
  python_version: null, venv_path: null, venv_status: 'none', python_executable: null,
  output_dir: null, proxy: null, extra_env: null, is_default: false,
}

export default function Environments() {
  const { t } = useI18n()
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
      .catch(() => message.error(t('management.loadFailed')))
      .finally(() => setLoading(false))
  }

  // Language changes only rerender labels; keep the existing query lifecycle.
  useEffect(load, []) // eslint-disable-line react-hooks/exhaustive-deps

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
      const resp = await localApi.get('/detect-browsers')
      const data = resp.data || []
      setBrowsers(data)
      if (data.length === 0) message.info(t('management.env.noBrowsers'))
    } catch {
      message.error(t('management.env.detectFailed'))
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
        message.success(t('management.updated'))
      } else {
        await api.post('/api/environments', payload)
        message.success(t('management.created'))
      }
      setModalOpen(false)
      load()
    } catch (e) {
      message.error(safeError(e, t('management.operationFailed')))
    }
  }

  const onDelete = async (id) => {
    try {
      await api.delete(`/api/environments/${id}`)
      message.success(t('management.deleted'))
      load()
    } catch (e) {
      message.error(safeError(e, t('management.deleteFailed')))
    }
  }

  // --- Table columns ---

  const columns = [
    { title: t('management.name'), dataIndex: 'name', key: 'name', width: 140 },
    {
      title: 'Python', key: 'python', width: 120,
      render: () => <Tag color="green">{t('management.env.isolated')}</Tag>,
    },
    { title: t('management.env.browserPort'), dataIndex: 'browser_port', key: 'port', width: 90, render: v => v || '-' },
    { title: t('management.env.browserPath'), dataIndex: 'browser_path', key: 'bpath', ellipsis: true, render: v => v || '-' },
    { title: t('management.env.outputDir'), dataIndex: 'output_dir', key: 'odir', ellipsis: true, render: v => v || '-' },
    { title: t('management.env.proxy'), dataIndex: 'proxy', key: 'proxy', width: 130, render: v => v || '-' },
    {
      title: t('management.default'), dataIndex: 'is_default', key: 'def', width: 60,
      render: v => v ? <Tag color="blue">{t('management.default')}</Tag> : '-',
    },
    {
      title: t('management.actions'), key: 'action', width: 100,
      render: (_, r) => (
        <Space>
          <Button type="link" size="small" aria-label={t('management.edit')} icon={<EditOutlined />} onClick={() => openEdit(r)} />
          <Popconfirm title={t('management.env.deleteConfirm')} onConfirm={() => onDelete(r.id)} okText={t('management.delete')} cancelText={t('management.cancel')}>
            <Button type="link" size="small" aria-label={t('management.delete')} danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ]

  // --- Collapse sections ---

  const collapseItems = [
    {
      key: 'python',
      label: t('management.env.python'),
      children: (
        <Alert
          type={runtimeInfo?.status === 'ready' ? 'success' : 'info'}
          showIcon
          message={t('management.env.privatePython')}
          description={runtimeInfo?.status === 'ready'
            ? t('management.env.runtimeReady', { path: runtimeInfo.path })
            : t('management.env.runtimeHint')}
        />
      ),
    },
    {
      key: 'browser',
      label: t('management.env.browserConfig'),
      children: (
        <>
          <Form.Item name="browser_port" label={t('management.env.debugPort')}>
            <InputNumber min={0} max={65535} placeholder={t('management.env.portExample')} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item label={t('management.env.browserPath')}>
            <Form.Item name="browser_path" noStyle>
              <Input placeholder={t('management.env.pathPlaceholder')} />
            </Form.Item>
            <div style={{ marginTop: 4 }}>
              {detectingBrowser ? <Spin size="small" /> : (
                browsers.length > 0 ? (
                  <Select
                    style={{ width: '100%' }}
                    placeholder={t('management.env.detectedBrowsers')}
                    allowClear
                    onChange={path => form.setFieldsValue({ browser_path: path })}
                    options={browsers.map(b => ({ label: `${b.name} - ${b.path}`, value: b.path }))}
                  />
                ) : (
                  <Button size="small" icon={<DesktopOutlined />} onClick={detectBrowsers}>{t('management.env.detectBrowsers')}</Button>
                )
              )}
            </div>
          </Form.Item>
        </>
      ),
    },
    {
      key: 'network',
      label: t('management.env.network'),
      children: (
        <Form.Item name="proxy" label={t('management.env.proxyAddress')}>
          <Input placeholder={t('management.env.proxyExample')} />
        </Form.Item>
      ),
    },
    {
      key: 'advanced',
      label: t('management.env.advanced'),
      children: (
        <>
          <Form.Item name="output_dir" label={t('management.env.outputDir')}>
            <Input placeholder={t('management.env.outputExample')} />
          </Form.Item>
          <Form.List name="extra_env">
            {(fields, { add, remove }) => (
              <>
                <div style={{ marginBottom: 8 }}>
                  <Button size="small" onClick={() => add()} icon={<PlusOutlined />}>{t('management.env.addVariable')}</Button>
                </div>
                {fields.map(({ key, name, ...restField }) => (
                  <Space key={key} style={{ display: 'flex', marginBottom: 8 }} align="baseline">
                    <Form.Item {...restField} name={[name, 'key']} rules={[{ required: true, message: t('management.env.variableName') }]}>
                      <Input placeholder={t('management.env.variableName')} style={{ width: 160 }} />
                    </Form.Item>
                    <Form.Item {...restField} name={[name, 'value']}>
                      <Input placeholder={t('management.env.variableValue')} style={{ width: 240 }} />
                    </Form.Item>
                    <Button type="link" danger size="small" onClick={() => remove(name)}>{t('management.delete')}</Button>
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
        <h2 style={{ margin: 0 }}>{t('management.env.title')}</h2>
        <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>{t('management.env.create')}</Button>
      </div>

      <Table locale={{ emptyText: t('management.empty') }} dataSource={envs} columns={columns} rowKey="id" loading={loading} />

      <Modal
        title={t(editingId ? 'management.env.edit' : 'management.env.create')}
        open={modalOpen}
        onCancel={() => setModalOpen(false)}
        onOk={() => form.submit()}
        okText={t(editingId ? 'management.save' : 'management.create')}
        cancelText={t('management.cancel')}
        width={600}
      >
        <Form form={form} layout="vertical" onFinish={onSubmit} initialValues={emptyForm}>
          <Form.Item name="name" label={t('management.env.name')} rules={[{ required: true, message: t('management.env.nameRequired') }]}>
            <Input placeholder={t('management.env.nameExample')} />
          </Form.Item>
          <Form.Item name="is_default" label={t('management.env.setDefault')} valuePropName="checked">
            <Switch />
          </Form.Item>
          <Collapse ghost items={collapseItems} defaultActiveKey={['python']} style={{ marginBottom: 16 }} />
        </Form>
      </Modal>
    </div>
  )
}
