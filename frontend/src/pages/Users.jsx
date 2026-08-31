import { useCallback, useEffect, useState } from 'react'
import { Table, Button, Modal, Form, Input, Select, Tag, message, Space, Popconfirm, Tooltip } from 'antd'
import { DeleteOutlined, EditOutlined, PlusOutlined, SearchOutlined } from '@ant-design/icons'
import api from '../api/client'
import { useAuth } from '../contexts/AuthContext'
import { formatServerTime } from '../utils/dateTime'

const roleOptions = [
  { label: '操作员', value: 'operator' },
  { label: '开发者', value: 'developer' },
  { label: '管理员', value: 'admin' },
]

export default function Users() {
  const { user: currentUser } = useAuth()
  const [users, setUsers] = useState([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [createOpen, setCreateOpen] = useState(false)
  const [editingUser, setEditingUser] = useState(null)
  const [createForm] = Form.useForm()
  const [editForm] = Form.useForm()

  const load = useCallback((keyword = search) => {
    setLoading(true)
    api.get('/api/users', { params: keyword.trim() ? { search: keyword.trim() } : {} })
      .then(r => setUsers(r.data))
      .catch(() => message.error('加载失败'))
      .finally(() => setLoading(false))
  }, [search])

  useEffect(() => { load('') }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const onCreate = async (values) => {
    try {
      await api.post('/api/users', values)
      message.success('创建成功')
      setCreateOpen(false)
      createForm.resetFields()
      load()
    } catch (e) {
      message.error(e.response?.data?.detail || '创建失败')
    }
  }

  const openEdit = (target) => {
    setEditingUser(target)
    editForm.setFieldsValue({
      display_name: target.display_name,
      role: target.role,
      status: target.status,
    })
  }

  const onUpdate = async (values) => {
    try {
      await api.put(`/api/users/${editingUser.id}`, values)
      message.success('用户信息已更新')
      setEditingUser(null)
      load()
    } catch (e) {
      message.error(e.response?.data?.detail || '修改失败')
    }
  }

  const onToggleStatus = async (target) => {
    const newStatus = target.status === 'active' ? 'disabled' : 'active'
    try {
      await api.put(`/api/users/${target.id}`, { status: newStatus })
      message.success(newStatus === 'disabled' ? '已禁用' : '已启用')
      load()
    } catch (e) {
      message.error(e.response?.data?.detail || '操作失败')
    }
  }

  const onDelete = async (target) => {
    try {
      await api.delete(`/api/users/${target.id}`)
      message.success('用户已删除')
      load()
    } catch (e) {
      message.error(e.response?.data?.detail || '删除失败')
    }
  }

  const columns = [
    { title: 'ID', dataIndex: 'id', key: 'id', width: 60 },
    { title: '用户名', dataIndex: 'username', key: 'username' },
    { title: '显示名', dataIndex: 'display_name', key: 'name' },
    {
      title: '角色', dataIndex: 'role', key: 'role', width: 100,
      render: (role) => {
        const colors = { admin: 'red', developer: 'blue', operator: 'green' }
        const labels = { admin: '管理员', developer: '开发者', operator: '操作员' }
        return <Tag color={colors[role]}>{labels[role] || role}</Tag>
      },
    },
    {
      title: '来源', dataIndex: 'auth_source', key: 'source', width: 90,
      render: (source) => <Tag>{source === 'external' ? '外部认证' : '本地'}</Tag>,
    },
    {
      title: '状态', dataIndex: 'status', key: 'status', width: 80,
      render: (status) => <Tag color={status === 'active' ? 'green' : 'red'}>{status === 'active' ? '正常' : '禁用'}</Tag>,
    },
    {
      title: '最后登录', dataIndex: 'last_login_at', key: 'login', width: 180,
      render: formatServerTime,
    },
    {
      title: '操作', key: 'action', width: 230,
      render: (_, target) => {
        const isSelf = target.id === currentUser?.id
        return (
          <Space size={4}>
            <Button type="link" size="small" icon={<EditOutlined />} onClick={() => openEdit(target)}>编辑</Button>
            <Tooltip title={isSelf ? '不能禁用自己的账号' : ''}>
              <Button type="link" size="small" disabled={isSelf} danger={target.status === 'active'}
                onClick={() => onToggleStatus(target)}>
                {target.status === 'active' ? '禁用' : '启用'}
              </Button>
            </Tooltip>
            <Popconfirm
              title={`确认删除用户“${target.username}”？`}
              description="删除后该账号将无法登录，历史记录仍会保留。"
              okText="删除"
              cancelText="取消"
              okButtonProps={{ danger: true }}
              disabled={isSelf}
              onConfirm={() => onDelete(target)}
            >
              <Tooltip title={isSelf ? '不能删除自己的账号' : ''}>
                <Button type="link" size="small" danger disabled={isSelf} icon={<DeleteOutlined />}>删除</Button>
              </Tooltip>
            </Popconfirm>
          </Space>
        )
      },
    },
  ]

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <h2 style={{ margin: 0 }}>用户管理</h2>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>创建用户</Button>
      </div>

      <Input.Search
        value={search}
        onChange={event => {
          const value = event.target.value
          setSearch(value)
          if (!value) load('')
        }}
        onSearch={load}
        placeholder="搜索用户名或显示名"
        enterButton={<SearchOutlined />}
        allowClear
        style={{ width: 360, marginBottom: 16 }}
      />

      <Table dataSource={users} columns={columns} rowKey="id" loading={loading} />

      <Modal title="创建用户" open={createOpen} onCancel={() => setCreateOpen(false)} onOk={() => createForm.submit()}>
        <Form form={createForm} layout="vertical" onFinish={onCreate} initialValues={{ role: 'operator' }}>
          <Form.Item name="username" label="用户名" rules={[{ required: true, message: '请输入用户名' }]}>
            <Input maxLength={50} />
          </Form.Item>
          <Form.Item name="password" label="密码" rules={[{ required: true, min: 4, message: '密码至少需要 4 个字符' }]}>
            <Input.Password maxLength={200} />
          </Form.Item>
          <Form.Item name="display_name" label="显示名称" rules={[{ required: true, message: '请输入显示名称' }]}>
            <Input maxLength={100} />
          </Form.Item>
          <Form.Item name="role" label="权限等级" rules={[{ required: true }]}>
            <Select options={roleOptions} />
          </Form.Item>
        </Form>
      </Modal>

      <Modal title={`编辑用户：${editingUser?.username || ''}`} open={Boolean(editingUser)}
        onCancel={() => setEditingUser(null)} onOk={() => editForm.submit()}>
        <Form form={editForm} layout="vertical" onFinish={onUpdate}>
          <Form.Item name="display_name" label="显示名称" rules={[{ required: true, message: '请输入显示名称' }]}>
            <Input maxLength={100} />
          </Form.Item>
          <Form.Item name="role" label="权限等级" rules={[{ required: true }]}>
            <Select options={roleOptions} disabled={editingUser?.id === currentUser?.id} />
          </Form.Item>
          <Form.Item name="status" label="账号状态" rules={[{ required: true }]}>
            <Select disabled={editingUser?.id === currentUser?.id} options={[
              { label: '正常', value: 'active' },
              { label: '禁用', value: 'disabled' },
            ]} />
          </Form.Item>
          {editingUser?.auth_source === 'external' && (
            <div style={{ color: '#999' }}>外部认证只负责验证身份，此处设置的权限等级由本系统管理。</div>
          )}
        </Form>
      </Modal>
    </div>
  )
}
