import React, { useEffect, useState } from 'react'
import { Table, Button, Modal, Form, Input, Select, Tag, message, Space } from 'antd'
import { PlusOutlined } from '@ant-design/icons'
import api from '../api/client'

export default function Users() {
  const [users, setUsers] = useState([])
  const [loading, setLoading] = useState(true)
  const [modalOpen, setModalOpen] = useState(false)
  const [form] = Form.useForm()

  const load = () => {
    api.get('/api/users').then(r => setUsers(r.data)).catch(() => message.error('加载失败')).finally(() => setLoading(false))
  }

  useEffect(load, [])

  const onCreate = async (values) => {
    try {
      await api.post('/api/users', values)
      message.success('创建成功')
      setModalOpen(false)
      form.resetFields()
      load()
    } catch (e) {
      message.error(e.response?.data?.detail || '创建失败')
    }
  }

  const onToggleStatus = async (user) => {
    const newStatus = user.status === 'active' ? 'disabled' : 'active'
    try {
      await api.put(`/api/users/${user.id}`, { status: newStatus })
      message.success(newStatus === 'disabled' ? '已禁用' : '已启用')
      load()
    } catch (e) {
      message.error('操作失败')
    }
  }

  const columns = [
    { title: 'ID', dataIndex: 'id', key: 'id', width: 60 },
    { title: '用户名', dataIndex: 'username', key: 'username' },
    { title: '显示名', dataIndex: 'display_name', key: 'name' },
    {
      title: '角色', dataIndex: 'role', key: 'role', width: 100,
      render: (r) => {
        const map = { admin: 'red', developer: 'blue', operator: 'green' }
        const label = { admin: '管理员', developer: '开发者', operator: '操作员' }
        return <Tag color={map[r]}>{label[r] || r}</Tag>
      }
    },
    {
      title: '状态', dataIndex: 'status', key: 'status', width: 80,
      render: (s) => <Tag color={s === 'active' ? 'green' : 'red'}>{s === 'active' ? '正常' : '禁用'}</Tag>
    },
    {
      title: '最后登录', dataIndex: 'last_login_at', key: 'login', width: 180,
      render: (t) => t ? new Date(t).toLocaleString() : '-'
    },
    {
      title: '操作', key: 'action', width: 120,
      render: (_, r) => (
        <Space>
          <Button type="link" size="small" danger={r.status === 'active'}
            onClick={() => onToggleStatus(r)}>
            {r.status === 'active' ? '禁用' : '启用'}
          </Button>
        </Space>
      )
    },
  ]

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <h2 style={{ margin: 0 }}>用户管理</h2>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => setModalOpen(true)}>创建用户</Button>
      </div>

      <Table dataSource={users} columns={columns} rowKey="id" loading={loading} />

      <Modal title="创建用户" open={modalOpen} onCancel={() => setModalOpen(false)} onOk={() => form.submit()}>
        <Form form={form} layout="vertical" onFinish={onCreate} initialValues={{ role: 'operator' }}>
          <Form.Item name="username" label="用户名" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item name="password" label="密码" rules={[{ required: true, min: 4 }]}>
            <Input.Password />
          </Form.Item>
          <Form.Item name="display_name" label="显示名称" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item name="role" label="角色" rules={[{ required: true }]}>
            <Select options={[
              { label: '操作员', value: 'operator' },
              { label: '开发者', value: 'developer' },
              { label: '管理员', value: 'admin' },
            ]} />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
