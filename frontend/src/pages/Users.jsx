import { useCallback, useEffect, useState } from 'react'
import { Alert, Button, Form, Input, Modal, Popconfirm, Select, Space, Table, Tag, Tooltip, message } from 'antd'
import { DeleteOutlined, EditOutlined, PlusOutlined, SearchOutlined, TeamOutlined } from '@ant-design/icons'
import api from '../api/client'
import { useAuth } from '../contexts/AuthContext'
import { formatServerTime } from '../utils/dateTime'
import { activeGroupOptions, defaultGroupIds, groupIds } from '../utils/groups'
import { safeError } from '../utils/safeError'
import { useI18n } from '../i18n/useI18n'

const roleKeys = {
  operator: 'management.role.operator', developer: 'management.role.developer', admin: 'management.role.admin',
}

export default function Users() {
  const { t } = useI18n()
  const roleOptions = Object.entries(roleKeys).map(([value, key]) => ({ label: t(key), value }))
  const groupTags = groups => groups?.length
    ? <Space size={[0, 4]} wrap>{groups.map(g => <Tag key={g.id} style={{ marginInlineEnd: 4 }}>{g.name}</Tag>)}</Space>
    : <span style={{ color: '#999', whiteSpace: 'nowrap' }}>{t('management.ungrouped')}</span>
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
    message.warning(t('management.groupsUnavailable'))
  }), [t])
  const load = useCallback((keyword = search, selectedGroup = groupFilter) => {
    setLoading(true)
    const params = {}
    if (keyword.trim()) params.search = keyword.trim()
    if (selectedGroup !== undefined) params.group_id = selectedGroup
    api.get('/api/users', { params }).then(r => setUsers(r.data)).catch(() => message.error(t('management.loadFailed'))).finally(() => setLoading(false))
  }, [search, groupFilter, t])

  useEffect(() => { load('', undefined); loadGroups() }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const saveUser = async (values, target) => {
    const payload = { ...values }
    if (!groupsReady) delete payload.group_ids
    try {
      if (target) await api.put(`/api/users/${target.id}`, payload)
      else await api.post('/api/users', payload)
      message.success(t(target ? 'management.userUpdated' : 'management.created'))
      setEditingUser(null); setCreateOpen(false); createForm.resetFields(); load()
    } catch (e) { message.error(safeError(e, t(target ? 'management.updateFailed' : 'management.createFailed'))) }
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
    try { await api.put(`/api/users/${target.id}`, { status: target.status === 'active' ? 'disabled' : 'active' }); message.success(t('management.operationSucceeded')); load() }
    catch (e) { message.error(safeError(e, t('management.operationFailed'))) }
  }
  const onDelete = async target => {
    try { await api.delete(`/api/users/${target.id}`); message.success(t('management.userDeleted')); load() }
    catch (e) { message.error(safeError(e, t('management.deleteFailed'))) }
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
      message.success(t(editingGroup ? 'management.groupUpdated' : 'management.groupCreated')); setEditingGroup(null); setGroupEditorOpen(false); groupForm.resetFields(); await loadGroups(); load()
    } catch (e) { message.error(safeError(e, t('management.groupSaveFailed'))) }
  }
  const deleteGroup = async group => {
    try { await api.delete(`/api/groups/${group.id}`); message.success(t('management.groupDeleted')); loadGroups(); load() }
    catch (e) { message.error(safeError(e, t('management.groupDeleteFailed'))) }
  }

  const columns = [
    { title: 'ID', dataIndex: 'id', width: 60 },
    { title: t('management.username'), dataIndex: 'username', width: 120 }, { title: t('management.displayName'), dataIndex: 'display_name', width: 140 },
    { title: t('management.role'), dataIndex: 'role', width: 100, render: role => <Tag color={{ admin: 'red', developer: 'blue', operator: 'green' }[role]}>{Object.hasOwn(roleKeys, role) ? t(roleKeys[role]) : role}</Tag> },
    { title: t('management.groups'), dataIndex: 'groups', width: 180, render: groupTags },
    { title: t('management.source'), dataIndex: 'auth_source', width: 90, render: source => <Tag>{source === 'external' ? t('management.externalAuth') : source === 'local' ? t('management.local') : source}</Tag> },
    { title: t('management.status'), dataIndex: 'status', width: 80, render: status => <Tag color={status === 'active' ? 'green' : 'red'}>{status === 'active' ? t('management.activeUser') : status === 'disabled' ? t('management.disabled') : status}</Tag> },
    { title: t('management.lastLogin'), dataIndex: 'last_login_at', width: 180, render: formatServerTime },
    { title: t('management.actions'), width: 230, fixed: 'right', render: (_, target) => { const self = target.id === currentUser?.id; return <Space size={4}>
      <Button type="link" size="small" icon={<EditOutlined />} onClick={() => openEdit(target)}>{t('management.edit')}</Button>
      <Tooltip title={self ? t('management.cannotDisableSelf') : ''}><Button type="link" size="small" disabled={self} danger={target.status === 'active'} onClick={() => onToggleStatus(target)}>{t(target.status === 'active' ? 'management.disable' : 'management.enable')}</Button></Tooltip>
      <Popconfirm title={t('management.deleteUserConfirm', { username: target.username })} description={t('management.historyRetained')} okText={t('management.delete')} cancelText={t('management.cancel')} disabled={self} onConfirm={() => onDelete(target)}><Tooltip title={self ? t('management.cannotDeleteSelf') : ''}><Button type="link" size="small" danger disabled={self} icon={<DeleteOutlined />}>{t('management.delete')}</Button></Tooltip></Popconfirm>
    </Space> } },
  ]
  const userFields = <>
    <Form.Item name="display_name" label={t('management.displayNameLabel')} rules={[{ required: true, message: t('management.required') }]}><Input maxLength={100} /></Form.Item>
    <Form.Item name="role" label={t('management.permissionLevel')} rules={[{ required: true, message: t('management.required') }]}><Select options={roleOptions} disabled={editingUser?.id === currentUser?.id} /></Form.Item>
    <Form.Item name="group_ids" label={t('management.memberGroups')} extra={!groupsReady ? t('management.groupsUnchanged') : undefined}><Select mode="multiple" allowClear disabled={!groupsReady} placeholder={t('management.selectGroups')} options={activeGroupOptions(groups)} /></Form.Item>
  </>

  return <div>
    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}><h2 style={{ margin: 0 }}>{t('management.usersTitle')}</h2><Space><Button icon={<TeamOutlined />} disabled={!groupsReady} onClick={() => setGroupsOpen(true)}>{t('management.groupsTitle')}</Button><Button type="primary" icon={<PlusOutlined />} onClick={() => { createForm.setFieldsValue({ role: 'operator', group_ids: groupsReady ? defaultGroupIds(groups) : undefined }); setCreateOpen(true) }}>{t('management.createUser')}</Button></Space></div>
    <Space style={{ marginBottom: 16 }}><Input.Search value={search} onChange={e => { setSearch(e.target.value); if (!e.target.value) load('', groupFilter) }} onSearch={value => load(value, groupFilter)} placeholder={t('management.searchUsers')} enterButton={<SearchOutlined />} allowClear style={{ width: 320 }} /><Select placeholder={t('management.allGroups')} allowClear value={groupFilter} options={activeGroupOptions(groups)} style={{ width: 180 }} onChange={value => { setGroupFilter(value); load(search, value) }} /></Space>
    <Table locale={{ emptyText: t('management.empty') }} dataSource={users} columns={columns} rowKey="id" loading={loading} scroll={{ x: 1100 }} />
    <Modal title={t('management.createUser')} okText={t('management.confirm')} cancelText={t('management.cancel')} open={createOpen} onCancel={() => setCreateOpen(false)} onOk={() => createForm.submit()}><Form form={createForm} layout="vertical" onFinish={values => saveUser(values)}><Form.Item name="username" label={t('management.username')} rules={[{ required: true, message: t('management.required') }]}><Input maxLength={50} /></Form.Item><Form.Item name="password" label={t('management.password')} rules={[{ required: true, min: 4, message: t('management.passwordMin') }]}><Input.Password maxLength={200} /></Form.Item>{userFields}</Form></Modal>
    <Modal title={t('management.editUserTitle', { username: editingUser?.username || '' })} okText={t('management.confirm')} cancelText={t('management.cancel')} open={Boolean(editingUser)} onCancel={() => setEditingUser(null)} onOk={() => editForm.submit()}><Form form={editForm} layout="vertical" onFinish={values => saveUser(values, editingUser)}>{userFields}<Form.Item name="status" label={t('management.accountStatus')} rules={[{ required: true, message: t('management.required') }]}><Select disabled={editingUser?.id === currentUser?.id} options={[{ label: t('management.activeUser'), value: 'active' }, { label: t('management.disabled'), value: 'disabled' }]} /></Form.Item>{editingUser?.auth_source === 'external' && <Alert type="info" showIcon message={t('management.externalAuthHint')} />}</Form></Modal>
    <Modal width={760} title={t('management.groupsTitle')} open={groupsOpen} onCancel={() => { setGroupsOpen(false); setEditingGroup(null); setGroupEditorOpen(false) }} footer={null}><Space direction="vertical" style={{ width: '100%' }} size="middle"><Alert type="info" showIcon message={t('management.groupScopeHint')} /><Button type="primary" icon={<PlusOutlined />} onClick={() => openGroupEditor(null)}>{t('management.createGroup')}</Button><Table locale={{ emptyText: t('management.empty') }} size="small" pagination={false} rowKey="id" dataSource={groups} columns={[{ title: t('management.name'), dataIndex: 'name' }, { title: t('management.description'), dataIndex: 'description', ellipsis: true }, { title: t('management.user'), dataIndex: 'user_count', width: 70 }, { title: t('management.script'), dataIndex: 'script_count', width: 70 }, { title: t('management.status'), dataIndex: 'status', width: 80, render: s => <Tag color={s === 'active' ? 'green' : 'default'}>{s === 'active' ? t('management.activeGroup') : s === 'disabled' ? t('management.disabledGroup') : s}</Tag> }, { title: t('management.actions'), width: 140, render: (_, g) => <Space><Button type="link" onClick={() => openGroupEditor(g)}>{t('management.edit')}</Button><Popconfirm title={t('management.deleteGroupConfirm')} okText={t('management.confirm')} cancelText={t('management.cancel')} onConfirm={() => deleteGroup(g)}><Button type="link" danger>{t('management.delete')}</Button></Popconfirm></Space> }]} />{groupEditorOpen && <Form form={groupForm} layout="vertical" onFinish={saveGroup}><h3>{t(editingGroup ? 'management.editGroup' : 'management.createGroup')}</h3><Form.Item name="name" label={t('management.name')} rules={[{ required: true, message: t('management.required') }]}><Input maxLength={100} /></Form.Item><Form.Item name="description" label={t('management.description')}><Input.TextArea rows={2} /></Form.Item><Space><Form.Item name="status" label={t('management.status')}><Select style={{ width: 120 }} options={[{ label: t('management.activeGroup'), value: 'active' }, { label: t('management.disabledGroup'), value: 'disabled' }]} /></Form.Item><Form.Item name="is_default" label={t('management.defaultGroup')}><Select style={{ width: 120 }} options={[{ label: t('management.yes'), value: true }, { label: t('management.no'), value: false }]} /></Form.Item></Space><Space><Button type="primary" htmlType="submit">{t('management.save')}</Button><Button onClick={() => { setEditingGroup(null); setGroupEditorOpen(false); groupForm.resetFields() }}>{t('management.cancel')}</Button></Space></Form>}</Space></Modal>
  </div>
}
