import { useEffect, useState, useMemo, useCallback, useRef } from 'react'
import { Table, Button, Tag, Upload, Modal, Input, Form, Space, Select, Tabs, message } from 'antd'
import { UploadOutlined, PlusOutlined, StopOutlined, CheckOutlined, SearchOutlined, DownloadOutlined, DeleteOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import { useConnection } from '../contexts/ConnectionContext'
import api from '../api/client'
import { loadScriptCollections } from '../api/offlineData'
import { formatScriptVersion } from '../utils/scriptVersion'
import { activeGroupOptions, defaultGroupIds, groupIds } from '../utils/groups'

import { useI18n } from '../i18n/useI18n'
import { safeError } from '../utils/safeError'

export default function Scripts() {
  const { t } = useI18n()
  const loadT = useRef(t)
  useEffect(() => { loadT.current = t }, [t])
  const renderGroups = groups => groups?.length ? groups.map(group => <Tag key={group.id}>{group.name}</Tag>) : <span style={{ color: '#999' }}>{t('workspace.ungrouped')}</span>
  const [myScripts, setMyScripts] = useState([])
  const [marketScripts, setMarketScripts] = useState([])
  const [manageableScripts, setManageableScripts] = useState([])
  const [myLoading, setMyLoading] = useState(true)
  const [marketLoading, setMarketLoading] = useState(false)
  const [manageLoading, setManageLoading] = useState(false)
  const [uploadOpen, setUploadOpen] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [groups, setGroups] = useState([])
  const [groupsReady, setGroupsReady] = useState(false)
  const [managingScript, setManagingScript] = useState(null)
  const [search, setSearch] = useState('')
  const [category, setCategory] = useState(undefined)
  const [form] = Form.useForm()
  const [groupsForm] = Form.useForm()
  const nav = useNavigate()
  const { user } = useAuth()
  const { online, localApi } = useConnection()

  const canUpload = online && (user?.role === 'admin' || user?.role === 'developer')
  const loadCollections = useCallback(() => {
    setMyLoading(true)
    setMarketLoading(true)
    loadScriptCollections({ online, api, localApi })
      .then(({ mine, marketplace }) => {
        setMyScripts(mine)
        setMarketScripts(marketplace)
      })
      .catch(() => message.error(loadT.current(online ? 'workspace.loadFailed' : 'workspace.agentUnavailable')))
      .finally(() => {
        setMyLoading(false)
        setMarketLoading(false)
      })
    if (canUpload) {
      setManageLoading(true)
      api.get('/api/scripts/manageable')
        .then(response => setManageableScripts(response.data))
        .catch(() => message.warning(loadT.current('workspace.scripts.manageLoadFailed')))
        .finally(() => setManageLoading(false))
    } else {
      setManageableScripts([])
    }
  }, [online, localApi, canUpload])

  useEffect(loadCollections, [loadCollections])
  useEffect(() => {
    if (!online || !canUpload) return
    api.get('/api/groups/available').then(r => {
      setGroups(r.data)
      setGroupsReady(true)
    }).catch(() => {
      setGroupsReady(false)
      message.error(loadT.current('workspace.scripts.groupsLoadFailed'))
    })
  }, [online, canUpload])

  const categories = useMemo(() => {
    const all = [...myScripts, ...marketScripts, ...manageableScripts]
    const set = new Set(all.map(s => s.category).filter(Boolean))
    return Array.from(set).map(c => ({ label: c, value: c }))
  }, [myScripts, marketScripts, manageableScripts])

  const filterList = (list) => list.filter(s => {
    if (category && s.category !== category) return false
    if (search && !s.name.toLowerCase().includes(search.toLowerCase())) return false
    return true
  })

  const onInstall = async (script) => {
    try {
      await api.post(`/api/scripts/${script.id}/install`)
      message.success(t('workspace.scripts.installed'))
      loadCollections()
    } catch (e) {
      message.error(safeError(e, t('workspace.scripts.installFailed')))
    }
  }

  const onUninstall = async (script) => {
    try {
      await api.post(`/api/scripts/${script.id}/uninstall`)
      message.success(t('workspace.scripts.uninstalled'))
      loadCollections()
    } catch (e) {
      message.error(safeError(e, t('workspace.scripts.uninstallFailed')))
    }
  }

  const onUpload = async (values) => {
    const { file, changelog, group_ids = [] } = values
    if (!groupsReady) {
      message.error(t('workspace.scripts.groupsNotReady'))
      return
    }
    if (!file || !file[0]) {
      message.error(t('workspace.chooseFileRequired'))
      return
    }
    setUploading(true)
    try {
      const formData = new FormData()
      formData.append('file', file[0].originFileObj)
      formData.append('changelog', changelog || '')
      formData.append('group_ids', JSON.stringify(group_ids))
      await api.post('/api/scripts/upload', formData)
      message.success(t('workspace.scripts.uploaded'))
      setUploadOpen(false)
      form.resetFields()
      loadCollections()
    } catch (e) {
      message.error(safeError(e, t('workspace.uploadFailed')))
    } finally {
      setUploading(false)
    }
  }

  const openGroupManager = script => {
    if (!groupsReady) return
    setManagingScript(script)
    groupsForm.setFieldsValue({ group_ids: groupIds(script.groups) })
  }

  const updateScriptGroups = async ({ group_ids }) => {
    if (!groupsReady) {
      message.error(t('workspace.scripts.groupsNotReady'))
      return
    }
    try {
      await api.put(`/api/scripts/${managingScript.id}/groups`, { group_ids })
      message.success(t('workspace.scripts.groupsUpdated'))
      setManagingScript(null)
      loadCollections()
    } catch (e) { message.error(safeError(e, t('workspace.scripts.groupsUpdateFailed'))) }
  }

  const onToggle = async (script) => {
    const action = script.status === 'active' ? 'disable' : 'enable'
    try {
      await api.post(`/api/scripts/${script.id}/${action}`)
      message.success(t(action === 'disable' ? 'workspace.scripts.disabled' : 'workspace.scripts.enabled'))
      loadCollections()
    } catch {
      message.error(t('workspace.actionFailed'))
    }
  }

  const myColumns = [
    { title: t('workspace.name'), dataIndex: 'name', key: 'name',
      render: (name, r) => <Button type="link" style={{ padding: 0 }} onClick={() => nav(`/scripts/${r.id}`)}>{name}</Button> },
    { title: t('workspace.category'), dataIndex: 'category', key: 'category', width: 120 },
    { title: t('workspace.version'), key: 'ver', width: 85, render: (_, r) => formatScriptVersion(r.latest_semantic_version, r.latest_version) },
    { title: t('workspace.groups'), dataIndex: 'groups', key: 'groups', render: renderGroups },
    {
      title: t('workspace.status'), dataIndex: 'status', key: 'status', width: 70,
      render: (s) => <Tag color={s === 'active' ? 'green' : 'red'}>{t(s === 'active' ? 'workspace.enable' : 'workspace.disable')}</Tag>
    },
    {
      title: t('workspace.actions'), key: 'action', width: canUpload ? 240 : 120,
      render: (_, r) => (
        <Space>
          <Button type="link" onClick={() => nav(`/scripts/${r.id}`)}>{t('workspace.execute')}</Button>
          <Button type="link" danger size="small" icon={<DeleteOutlined />} onClick={() => onUninstall(r)}>{t('workspace.uninstall')}</Button>
          {r.can_manage_groups && <Button type="link" size="small" onClick={() => openGroupManager(r)}>{t('workspace.group')}</Button>}
          {r.can_manage && (
            <Button type="link" size="small" icon={r.status === 'active' ? <StopOutlined /> : <CheckOutlined />} onClick={() => onToggle(r)}>
              {t(r.status === 'active' ? 'workspace.disable' : 'workspace.enable')}
            </Button>
          )}
        </Space>
      )
    },
  ]

  const managementColumns = [
    { title: t('workspace.name'), dataIndex: 'name', key: 'name', render: (name, r) => <Button type="link" style={{ padding: 0 }} onClick={() => nav(`/scripts/${r.id}`)}>{name}</Button> },
    { title: t('workspace.category'), dataIndex: 'category', key: 'category', width: 120 },
    { title: t('workspace.version'), key: 'ver', width: 85, render: (_, r) => formatScriptVersion(r.latest_semantic_version, r.latest_version) },
    { title: t('workspace.groups'), dataIndex: 'groups', key: 'groups', render: renderGroups },
    { title: t('workspace.status'), dataIndex: 'status', key: 'status', width: 70, render: s => <Tag color={s === 'active' ? 'green' : 'red'}>{t(s === 'active' ? 'workspace.enable' : 'workspace.disable')}</Tag> },
    { title: t('workspace.actions'), key: 'action', width: 190, render: (_, r) => <Space>
      <Button type="link" size="small" onClick={() => nav(`/scripts/${r.id}`)}>{t('workspace.details')}</Button>
      {r.can_manage_groups && <Button type="link" size="small" disabled={!groupsReady} onClick={() => openGroupManager(r)}>{t('workspace.group')}</Button>}
      {r.can_manage && <Button type="link" size="small" icon={r.status === 'active' ? <StopOutlined /> : <CheckOutlined />} onClick={() => onToggle(r)}>{t(r.status === 'active' ? 'workspace.disable' : 'workspace.enable')}</Button>}
    </Space> },
  ]

  const marketColumns = [
    { title: t('workspace.name'), dataIndex: 'name', key: 'name',
      render: (name, r) => <Button type="link" style={{ padding: 0 }} onClick={() => nav(`/scripts/${r.id}`)}>{name}</Button> },
    { title: t('workspace.description'), dataIndex: 'description', key: 'desc', ellipsis: true },
    { title: t('workspace.category'), dataIndex: 'category', key: 'category', width: 120 },
    { title: t('workspace.version'), key: 'ver', width: 85, render: (_, r) => formatScriptVersion(r.latest_semantic_version, r.latest_version) },
    { title: t('workspace.groups'), dataIndex: 'groups', key: 'groups', render: renderGroups },
    {
      title: t('workspace.actions'), key: 'action', width: 170,
      render: (_, r) => (
        <Space>
          {r.installed ? (
            <Button type="link" onClick={() => nav(`/scripts/${r.id}`)}>{t('workspace.view')}</Button>
          ) : (
            <Button type="primary" size="small" icon={<DownloadOutlined />} onClick={() => onInstall(r)}>{t('workspace.install')}</Button>
          )}
          {r.can_manage_groups && <Button type="link" size="small" disabled={!groupsReady} onClick={() => openGroupManager(r)}>{t('workspace.group')}</Button>}
        </Space>
      )
    },
  ]

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <h2 style={{ margin: 0 }}>{t('workspace.scripts.title')}</h2>
        {canUpload && (
          <Button type="primary" icon={<PlusOutlined />} disabled={!groupsReady} onClick={() => { form.setFieldsValue({ group_ids: defaultGroupIds(groups) }); setUploadOpen(true) }}>{t('workspace.scripts.upload')}</Button>
        )}
      </div>

      <Space style={{ marginBottom: 16 }}>
        <Input placeholder={t('workspace.scripts.search')} prefix={<SearchOutlined />}
          value={search} onChange={e => setSearch(e.target.value)} style={{ width: 240 }} allowClear />
        <Select placeholder={t('workspace.scripts.allCategories')} value={category} onChange={setCategory}
          options={categories} style={{ width: 160 }} allowClear />
      </Space>

      <Tabs items={[
        {
          key: 'mine',
          label: t('workspace.scripts.mine', { count: filterList(myScripts).length }),
          children: (
            <Table dataSource={filterList(myScripts)} columns={myColumns} rowKey="id"
              loading={myLoading} size="small" pagination={{ pageSize: 20 }} />
          )
        },
        ...(online ? [{
          key: 'market',
          label: t('workspace.scripts.market'),
          children: (
            <Table dataSource={filterList(marketScripts)} columns={marketColumns} rowKey="id"
              loading={marketLoading} size="small" pagination={{ pageSize: 20 }}
              />
          )
        }] : []),
        ...(canUpload ? [{
          key: 'manage',
          label: t('workspace.scripts.manage', { count: filterList(manageableScripts).length }),
          children: (
            <Table dataSource={filterList(manageableScripts)} columns={managementColumns} rowKey="id"
              loading={manageLoading} size="small" pagination={{ pageSize: 20 }} />
          )
        }] : []),
      ]} />

      <Modal title={t('workspace.scripts.upload')} open={uploadOpen} onCancel={() => setUploadOpen(false)}
        confirmLoading={uploading} onOk={() => form.submit()} okText={t('workspace.upload')}>
        <Form form={form} layout="vertical" onFinish={onUpload}>
          <Form.Item name="file" label={t('workspace.scriptFile')} rules={[{ required: true }]}
            valuePropName="fileList" getValueFromEvent={(e) => Array.isArray(e) ? e : e?.fileList}>
            <Upload beforeUpload={() => false} maxCount={1} accept=".py,.zip">
              <Button icon={<UploadOutlined />}>{t('workspace.chooseFile')}</Button>
            </Upload>
          </Form.Item>
          <Form.Item name="group_ids" label={t('workspace.groups')} tooltip={t('workspace.scripts.groupsTooltip')} rules={[{ required: true, type: 'array', min: 1, message: t('workspace.scripts.groupsRequired') }]}>
            <Select mode="multiple" allowClear placeholder={t('workspace.scripts.chooseVisibleGroups')} options={activeGroupOptions(groups)} />
          </Form.Item>
          <Form.Item name="changelog" label={t('workspace.changelog')}>
            <Input.TextArea rows={3} placeholder={t('workspace.scripts.changelogPlaceholder')} />
          </Form.Item>
        </Form>
      </Modal>

      <Modal title={t('workspace.scripts.adjustGroups', { name: managingScript?.name || '' })} open={Boolean(managingScript)} onCancel={() => setManagingScript(null)} onOk={() => groupsForm.submit()}>
        <Form form={groupsForm} layout="vertical" onFinish={updateScriptGroups}>
          <Form.Item name="group_ids" label={t('workspace.groups')} extra={t('workspace.scripts.groupsHelp')} rules={[{ required: true, type: 'array', min: 1, message: t('workspace.scripts.groupsRequired') }]}>
            <Select mode="multiple" allowClear options={activeGroupOptions(groups)} placeholder={t('workspace.scripts.chooseGroups')} />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
