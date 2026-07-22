import { useEffect, useState, useMemo, useCallback } from 'react'
import { Table, Button, Tag, Upload, Modal, Input, Form, Space, Select, Tabs, message } from 'antd'
import { UploadOutlined, PlusOutlined, StopOutlined, CheckOutlined, SearchOutlined, DownloadOutlined, DeleteOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import { useConnection } from '../contexts/ConnectionContext'
import api from '../api/client'
import { loadScriptCollections } from '../api/offlineData'

export default function Scripts() {
  const [myScripts, setMyScripts] = useState([])
  const [marketScripts, setMarketScripts] = useState([])
  const [myLoading, setMyLoading] = useState(true)
  const [marketLoading, setMarketLoading] = useState(false)
  const [uploadOpen, setUploadOpen] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [search, setSearch] = useState('')
  const [category, setCategory] = useState(undefined)
  const [form] = Form.useForm()
  const nav = useNavigate()
  const { user } = useAuth()
  const { online, localApi } = useConnection()

  const canUpload = online && (user?.role === 'admin' || user?.role === 'developer')
  const isAdmin = user?.role === 'admin'

  const loadCollections = useCallback(() => {
    setMyLoading(true)
    setMarketLoading(true)
    loadScriptCollections({ online, api, localApi })
      .then(({ mine, marketplace }) => {
        setMyScripts(mine)
        setMarketScripts(marketplace)
      })
      .catch(() => message.error(online ? '加载失败' : '本地 Agent 不可用'))
      .finally(() => {
        setMyLoading(false)
        setMarketLoading(false)
      })
  }, [online, localApi])

  useEffect(loadCollections, [loadCollections])

  const categories = useMemo(() => {
    const all = [...myScripts, ...marketScripts]
    const set = new Set(all.map(s => s.category).filter(Boolean))
    return Array.from(set).map(c => ({ label: c, value: c }))
  }, [myScripts, marketScripts])

  const filterList = (list) => list.filter(s => {
    if (category && s.category !== category) return false
    if (search && !s.name.toLowerCase().includes(search.toLowerCase())) return false
    return true
  })

  const onInstall = async (script) => {
    try {
      await api.post(`/api/scripts/${script.id}/install`)
      message.success('已安装')
      loadCollections()
    } catch (e) {
      message.error(e.response?.data?.detail || '安装失败')
    }
  }

  const onUninstall = async (script) => {
    try {
      await api.post(`/api/scripts/${script.id}/uninstall`)
      message.success('已卸载')
      loadCollections()
    } catch (e) {
      message.error(e.response?.data?.detail || '卸载失败')
    }
  }

  const onUpload = async (values) => {
    const { file, changelog } = values
    if (!file || !file[0]) {
      message.error('请选择文件')
      return
    }
    setUploading(true)
    try {
      const formData = new FormData()
      formData.append('file', file[0].originFileObj)
      formData.append('changelog', changelog || '')
      await api.post('/api/scripts/upload', formData)
      message.success('上传成功')
      setUploadOpen(false)
      form.resetFields()
      loadCollections()
    } catch (e) {
      message.error(e.response?.data?.detail || '上传失败')
    } finally {
      setUploading(false)
    }
  }

  const onToggle = async (script) => {
    const action = script.status === 'active' ? 'disable' : 'enable'
    try {
      await api.post(`/api/scripts/${script.id}/${action}`)
      message.success(action === 'disable' ? '已禁用' : '已启用')
      loadCollections()
    } catch {
      message.error('操作失败')
    }
  }

  const myColumns = [
    { title: '名称', dataIndex: 'name', key: 'name',
      render: (name, r) => <Button type="link" style={{ padding: 0 }} onClick={() => nav(`/scripts/${r.id}`)}>{name}</Button> },
    { title: '分类', dataIndex: 'category', key: 'category', width: 120 },
    { title: '版本', dataIndex: 'latest_version', key: 'ver', width: 70 },
    {
      title: '状态', dataIndex: 'status', key: 'status', width: 70,
      render: (s) => <Tag color={s === 'active' ? 'green' : 'red'}>{s === 'active' ? '启用' : '禁用'}</Tag>
    },
    {
      title: '操作', key: 'action', width: canUpload ? 240 : 120,
      render: (_, r) => (
        <Space>
          <Button type="link" onClick={() => nav(`/scripts/${r.id}`)}>执行</Button>
          {!isAdmin && (
            <Button type="link" danger size="small" icon={<DeleteOutlined />} onClick={() => onUninstall(r)}>卸载</Button>
          )}
          {canUpload && (
            <Button type="link" size="small"
              icon={r.status === 'active' ? <StopOutlined /> : <CheckOutlined />}
              onClick={() => onToggle(r)}>
              {r.status === 'active' ? '禁用' : '启用'}
            </Button>
          )}
        </Space>
      )
    },
  ]

  const marketColumns = [
    { title: '名称', dataIndex: 'name', key: 'name' },
    { title: '描述', dataIndex: 'description', key: 'desc', ellipsis: true },
    { title: '分类', dataIndex: 'category', key: 'category', width: 120 },
    { title: '版本', dataIndex: 'latest_version', key: 'ver', width: 70 },
    {
      title: '操作', key: 'action', width: 120,
      render: (_, r) => (
        <Space>
          {isAdmin || r.installed ? (
            <Button type="link" onClick={() => nav(`/scripts/${r.id}`)}>查看</Button>
          ) : (
            <Button type="primary" size="small" icon={<DownloadOutlined />} onClick={() => onInstall(r)}>安装</Button>
          )}
        </Space>
      )
    },
  ]

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <h2 style={{ margin: 0 }}>脚本</h2>
        {canUpload && (
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setUploadOpen(true)}>上传脚本</Button>
        )}
      </div>

      <Space style={{ marginBottom: 16 }}>
        <Input placeholder="搜索脚本名称" prefix={<SearchOutlined />}
          value={search} onChange={e => setSearch(e.target.value)} style={{ width: 240 }} allowClear />
        <Select placeholder="全部分类" value={category} onChange={setCategory}
          options={categories} style={{ width: 160 }} allowClear />
      </Space>

      <Tabs items={[
        {
          key: 'mine',
          label: `我的脚本 (${filterList(myScripts).length})`,
          children: (
            <Table dataSource={filterList(myScripts)} columns={myColumns} rowKey="id"
              loading={myLoading} size="small" pagination={{ pageSize: 20 }} />
          )
        },
        ...(online ? [{
          key: 'market',
          label: `脚本市场`,
          children: (
            <Table dataSource={filterList(marketScripts)} columns={marketColumns} rowKey="id"
              loading={marketLoading} size="small" pagination={{ pageSize: 20 }}
              />
          )
        }] : []),
      ]} />

      <Modal title="上传脚本" open={uploadOpen} onCancel={() => setUploadOpen(false)}
        confirmLoading={uploading} onOk={() => form.submit()} okText="上传">
        <Form form={form} layout="vertical" onFinish={onUpload}>
          <Form.Item name="file" label="脚本文件 (.py 或 .zip)" rules={[{ required: true }]}
            valuePropName="fileList" getValueFromEvent={(e) => Array.isArray(e) ? e : e?.fileList}>
            <Upload beforeUpload={() => false} maxCount={1} accept=".py,.zip">
              <Button icon={<UploadOutlined />}>选择文件</Button>
            </Upload>
          </Form.Item>
          <Form.Item name="changelog" label="版本说明">
            <Input.TextArea rows={3} placeholder="本次上传的变更说明" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
