import { useCallback, useEffect, useState } from 'react'
import { Alert, Button, Form, Input, Modal, Popconfirm, Select, Space, Table, Tag, Tooltip, message } from 'antd'
import { DeleteOutlined, EditOutlined, PlusOutlined, SearchOutlined, TeamOutlined } from '@ant-design/icons'
import api from '../api/client'
import { useAuth } from '../contexts/AuthContext'
import { formatServerTime } from '../utils/dateTime'
import { activeGroupOptions, defaultGroupIds, groupIds } from '../utils/groups'

const roleOptions = [
  { label: '操作员', value: 'operator' }, { label: '开发者', value: 'developer' }, { label: '管理员', value: 'admin' },
]
const groupTags = groups => groups?.length
  ? <Space size={[0, 4]} wrap>{groups.map(g => <Tag key={g.id} style={{ marginInlineEnd: 4 }}>{g.name}</Tag>)}</Space>
  : <span style={{ color: '#999', whiteSpace: 'nowrap' }}>未分组</span>

export default function Users() {
  const { user: currentUser } = useAuth()
  const [users, setUsers] = useState([])
  const [groups, setGroups] = useState([])
  const [groupsReady, setGroupsReady] = useState(false)
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [groupFilter, setGroupFilter] = useState(undefined)
  const [createOpen, setCreateOpen] = useState(false)
  const [editingUser, setEditingUser] = useState(null)
  const [groupsOpen, setGroupsOpen] = useState(false)
  const [editingGroup, setEditingGroup] = useState(null)
  const [groupEditorOpen, setGroupEditorOpen] = useState(false)
  const [createForm] = Form.useForm()
  const [editForm] = Form.useForm()
  const [groupForm] = Form.useForm()

  const loadGroups = useCallback(() => api.get('/api/groups').then(r => {
    setGroups(r.data)
    setGroupsReady(true)
    return r.data
  }).catch(() => {
    setGroupsReady(false)
    message.warning('分组服务暂不可用，仍可编辑用户基础信息')
  }), [])
  const load = useCallback((keyword = search, selectedGroup = groupFilter) => {
    setLoading(true)
    const params = {}
    if (keyword.trim()) params.search = keyword.trim()
    if (selectedGroup !== undefined) params.group_id = selectedGroup
    api.get('/api/users', { params }).then(r => setUsers(r.data)).catch(() => message.error('加载失败')).finally(() => setLoading(false))
  }, [search, groupFilter])

  useEffect(() => { load('', undefined); loadGroups() }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const saveUser = async (values, target) => {
    const payload = { ...values }
    if (!groupsReady) delete payload.group_ids
    try {
      if (target) await api.put(`/api/users/${target.id}`, payload)
      else await api.post('/api/users', payload)
      message.success(target ? '用户信息已更新' : '创建成功')
      setEditingUser(null); setCreateOpen(false); createForm.resetFields(); load()
    } catch (e) { message.error(e.response?.data?.detail || (target ? '修改失败' : '创建失败')) }
  }
  const openEdit = target => {
    const activeIds = new Set(activeGroupOptions(groups).map(option => option.value))
    setEditingUser(target)
    editForm.setFieldsValue({
      display_name: target.display_name,
      role: target.role,
      status: target.status,
      group_ids: groupsReady ? groupIds(target.groups).filter(id => activeIds.has(id)) : undefined,
    })
  }
  const onToggleStatus = async target => {
    try { await api.put(`/api/users/${target.id}`, { status: target.status === 'active' ? 'disabled' : 'active' }); message.success('操作成功'); load() }
    catch (e) { message.error(e.response?.data?.detail || '操作失败') }
  }
  const onDelete = async target => {
    try { await api.delete(`/api/users/${target.id}`); message.success('用户已删除'); load() }
    catch (e) { message.error(e.response?.data?.detail || '删除失败') }
  }
  const openGroupEditor = group => {
    setEditingGroup(group || null)
    setGroupEditorOpen(true)
    groupForm.resetFields()
    groupForm.setFieldsValue(group ? { name: group.name, description: group.description, status: group.status, is_default: group.is_default } : { status: 'active', is_default: false })
  }
  const saveGroup = async values => {
    try {
      if (editingGroup) await api.put(`/api/groups/${editingGroup.id}`, values)
      else await api.post('/api/groups', values)
      message.success(editingGroup ? '分组已更新' : '分组已创建'); setEditingGroup(null); setGroupEditorOpen(false); groupForm.resetFields(); await loadGroups(); load()
    } catch (e) { message.error(e.response?.data?.detail || '保存分组失败') }
  }
  const deleteGroup = async group => {
    try { await api.delete(`/api/groups/${group.id}`); message.success('分组已删除'); loadGroups(); load() }
    catch (e) { message.error(e.response?.data?.detail || '删除分组失败') }
  }

  const columns = [
    { title: 'ID', dataIndex: 'id', width: 60 },
    { title: '用户名', dataIndex: 'username', width: 120 }, { title: '显示名', dataIndex: 'display_name', width: 140 },
    { title: '角色', dataIndex: 'role', width: 100, render: role => <Tag color={{ admin: 'red', developer: 'blue', operator: 'green' }[role]}>{{ admin: '管理员', developer: '开发者', operator: '操作员' }[role] || role}</Tag> },
    { title: '分组', dataIndex: 'groups', width: 180, render: groupTags },
    { title: '来源', dataIndex: 'auth_source', width: 90, render: source => <Tag>{source === 'external' ? '外部认证' : '本地'}</Tag> },
    { title: '状态', dataIndex: 'status', width: 80, render: status => <Tag color={status === 'active' ? 'green' : 'red'}>{status === 'active' ? '正常' : '禁用'}</Tag> },
    { title: '最后登录', dataIndex: 'last_login_at', width: 180, render: formatServerTime },
    { title: '操作', width: 230, fixed: 'right', render: (_, target) => { const self = target.id === currentUser?.id; return <Space size={4}>
      <Button type="link" size="small" icon={<EditOutlined />} onClick={() => openEdit(target)}>编辑</Button>
      <Tooltip title={self ? '不能禁用自己的账号' : ''}><Button type="link" size="small" disabled={self} danger={target.status === 'active'} onClick={() => onToggleStatus(target)}>{target.status === 'active' ? '禁用' : '启用'}</Button></Tooltip>
      <Popconfirm title={`确认删除用户“${target.username}”？`} description="历史记录仍会保留。" okText="删除" cancelText="取消" disabled={self} onConfirm={() => onDelete(target)}><Tooltip title={self ? '不能删除自己的账号' : ''}><Button type="link" size="small" danger disabled={self} icon={<DeleteOutlined />}>删除</Button></Tooltip></Popconfirm>
    </Space> } },
  ]
  const userFields = <>
    <Form.Item name="display_name" label="显示名称" rules={[{ required: true }]}><Input maxLength={100} /></Form.Item>
    <Form.Item name="role" label="权限等级" rules={[{ required: true }]}><Select options={roleOptions} disabled={editingUser?.id === currentUser?.id} /></Form.Item>
    <Form.Item name="group_ids" label="所属分组" extra={!groupsReady ? '分组服务暂不可用，本次保存不会修改所属分组。' : undefined}><Select mode="multiple" allowClear disabled={!groupsReady} placeholder="请选择分组" options={activeGroupOptions(groups)} /></Form.Item>
  </>

  return <div>
    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}><h2 style={{ margin: 0 }}>用户管理</h2><Space><Button icon={<TeamOutlined />} disabled={!groupsReady} onClick={() => setGroupsOpen(true)}>分组管理</Button><Button type="primary" icon={<PlusOutlined />} onClick={() => { createForm.setFieldsValue({ role: 'operator', group_ids: groupsReady ? defaultGroupIds(groups) : undefined }); setCreateOpen(true) }}>创建用户</Button></Space></div>
    <Space style={{ marginBottom: 16 }}><Input.Search value={search} onChange={e => { setSearch(e.target.value); if (!e.target.value) load('', groupFilter) }} onSearch={value => load(value, groupFilter)} placeholder="搜索用户名或显示名" enterButton={<SearchOutlined />} allowClear style={{ width: 320 }} /><Select placeholder="全部分组" allowClear value={groupFilter} options={activeGroupOptions(groups)} style={{ width: 180 }} onChange={value => { setGroupFilter(value); load(search, value) }} /></Space>
    <Table dataSource={users} columns={columns} rowKey="id" loading={loading} scroll={{ x: 1100 }} />
    <Modal title="创建用户" open={createOpen} onCancel={() => setCreateOpen(false)} onOk={() => createForm.submit()}><Form form={createForm} layout="vertical" onFinish={values => saveUser(values)}><Form.Item name="username" label="用户名" rules={[{ required: true }]}><Input maxLength={50} /></Form.Item><Form.Item name="password" label="密码" rules={[{ required: true, min: 4, message: '密码至少需要 4 个字符' }]}><Input.Password maxLength={200} /></Form.Item>{userFields}</Form></Modal>
    <Modal title={`编辑用户：${editingUser?.username || ''}`} open={Boolean(editingUser)} onCancel={() => setEditingUser(null)} onOk={() => editForm.submit()}><Form form={editForm} layout="vertical" onFinish={values => saveUser(values, editingUser)}>{userFields}<Form.Item name="status" label="账号状态" rules={[{ required: true }]}><Select disabled={editingUser?.id === currentUser?.id} options={[{ label: '正常', value: 'active' }, { label: '禁用', value: 'disabled' }]} /></Form.Item>{editingUser?.auth_source === 'external' && <Alert type="info" showIcon message="外部认证仅负责身份验证；用户角色和所属分组仍由本系统在此管理。" />}</Form></Modal>
    <Modal width={760} title="分组管理" open={groupsOpen} onCancel={() => { setGroupsOpen(false); setEditingGroup(null); setGroupEditorOpen(false) }} footer={null}><Space direction="vertical" style={{ width: '100%' }} size="middle"><Alert type="info" showIcon message="分组用于控制用户可见的脚本市场范围；删除前请先确认组内用户和脚本。" /><Button type="primary" icon={<PlusOutlined />} onClick={() => openGroupEditor(null)}>新建分组</Button><Table size="small" pagination={false} rowKey="id" dataSource={groups} columns={[{ title: '名称', dataIndex: 'name' }, { title: '说明', dataIndex: 'description', ellipsis: true }, { title: '用户', dataIndex: 'user_count', width: 70 }, { title: '脚本', dataIndex: 'script_count', width: 70 }, { title: '状态', dataIndex: 'status', width: 80, render: s => <Tag color={s === 'active' ? 'green' : 'default'}>{s === 'active' ? '有效' : '停用'}</Tag> }, { title: '操作', width: 140, render: (_, g) => <Space><Button type="link" onClick={() => openGroupEditor(g)}>编辑</Button><Popconfirm title="确认删除该分组？" onConfirm={() => deleteGroup(g)}><Button type="link" danger>删除</Button></Popconfirm></Space> }]} />{groupEditorOpen && <Form form={groupForm} layout="vertical" onFinish={saveGroup}><h3>{editingGroup ? '编辑分组' : '新建分组'}</h3><Form.Item name="name" label="名称" rules={[{ required: true }]}><Input maxLength={100} /></Form.Item><Form.Item name="description" label="说明"><Input.TextArea rows={2} /></Form.Item><Space><Form.Item name="status" label="状态"><Select style={{ width: 120 }} options={[{ label: '有效', value: 'active' }, { label: '停用', value: 'disabled' }]} /></Form.Item><Form.Item name="is_default" label="默认组"><Select style={{ width: 120 }} options={[{ label: '是', value: true }, { label: '否', value: false }]} /></Form.Item></Space><Space><Button type="primary" htmlType="submit">保存</Button><Button onClick={() => { setEditingGroup(null); setGroupEditorOpen(false); groupForm.resetFields() }}>取消</Button></Space></Form>}</Space></Modal>
  </div>
}
