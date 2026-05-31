import React, { useEffect, useState } from 'react'
import { Descriptions, Collapse, Tag, Spin, Button, Upload, Modal, Input, Form, Select, message, Space } from 'antd'
import { UploadOutlined, PlusOutlined } from '@ant-design/icons'
import { useNavigate, useParams } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import api from '../api/client'
import ParamForm from '../components/ParamForm'

const PARAMS_STORAGE_KEY = 'autoscript_saved_params'

function loadSavedParams(scriptId) {
  try {
    const all = JSON.parse(localStorage.getItem(PARAMS_STORAGE_KEY) || '{}')
    return all[scriptId] || null
  } catch { return null }
}

function saveParams(scriptId, params) {
  try {
    const all = JSON.parse(localStorage.getItem(PARAMS_STORAGE_KEY) || '{}')
    all[scriptId] = params
    localStorage.setItem(PARAMS_STORAGE_KEY, JSON.stringify(all))
  } catch { /* ignore */ }
}

export default function ScriptDetail() {
  const { id } = useParams()
  const nav = useNavigate()
  const { user } = useAuth()
  const [script, setScript] = useState(null)
  const [versions, setVersions] = useState([])
  const [loading, setLoading] = useState(true)
  const [savedParams, setSavedParams] = useState(null)
  const [verModalOpen, setVerModalOpen] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [environments, setEnvironments] = useState([])
  const [selectedEnvId, setSelectedEnvId] = useState(null)
  const [verForm] = Form.useForm()

  const canUpload = user?.role === 'admin' || user?.role === 'developer'

  const loadScript = () => {
    setLoading(true)
    Promise.all([
      api.get(`/api/scripts/${id}`),
      api.get(`/api/scripts/${id}/versions`),
      api.get('/api/environments'),
    ]).then(([s, v, e]) => {
      setScript(s.data)
      setVersions(v.data)
      setEnvironments(e.data)
      const defEnv = e.data.find(e => e.is_default)
      if (defEnv) setSelectedEnvId(defEnv.id)
    }).catch(() => message.error('加载失败')).finally(() => setLoading(false))

    setSavedParams(loadSavedParams(id))
  }

  useEffect(loadScript, [id])

  const onExecute = async (params) => {
    try {
      await api.post('/api/runs/execute', {
        script_id: parseInt(id),
        params,
        environment_id: selectedEnvId || undefined,
      })
      message.success('已提交执行')
      nav('/runs')
    } catch (e) {
      message.error(e.response?.data?.detail || '执行失败')
    }
  }

  const onSaveParams = (params) => {
    saveParams(id, params)
    setSavedParams(params)
    message.success('参数已保存')
  }

  const onUploadVersion = async (values) => {
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
      await api.post(`/api/scripts/${id}/upload-version`, formData)
      message.success('新版本上传成功')
      setVerModalOpen(false)
      verForm.resetFields()
      loadScript()
    } catch (e) {
      message.error(e.response?.data?.detail || '上传失败')
    } finally {
      setUploading(false)
    }
  }

  if (loading) return <Spin />
  if (!script) return <div>脚本不存在</div>

  const config = script.config_json ? JSON.parse(script.config_json) : {}
  const paramDefs = config.params || []

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <h2 style={{ margin: 0 }}>{script.name}</h2>
        {canUpload && (
          <Button icon={<PlusOutlined />} onClick={() => setVerModalOpen(true)}>上传新版本</Button>
        )}
      </div>

      <Descriptions bordered size="small" column={1} style={{ marginBottom: 16 }}>
        <Descriptions.Item label="描述">{script.description}</Descriptions.Item>
        <Descriptions.Item label="分类">{script.category}</Descriptions.Item>
        <Descriptions.Item label="版本">{script.latest_version}</Descriptions.Item>
        <Descriptions.Item label="状态">
          <Tag color={script.status === 'active' ? 'green' : 'red'}>{script.status}</Tag>
        </Descriptions.Item>
      </Descriptions>

      {paramDefs.length > 0 && (
        <div style={{ marginBottom: 16 }}>
          {environments.length > 0 && (
            <div style={{ marginBottom: 12 }}>
              <span style={{ marginRight: 8 }}>执行环境：</span>
              <Select
                style={{ width: 300 }}
                placeholder="不使用环境（默认）"
                allowClear
                value={selectedEnvId}
                onChange={setSelectedEnvId}
                options={environments.map(e => ({
                  label: `${e.name}${e.is_default ? ' (默认)' : ''}`,
                  value: e.id,
                }))}
              />
            </div>
          )}
          <h3 style={{ marginBottom: 8 }}>参数配置</h3>
          <ParamForm
            params={paramDefs}
            initialValues={savedParams}
            onSubmit={onExecute}
            onSave={onSaveParams}
          />
        </div>
      )}

      <Collapse items={versions.map(v => ({
        key: v.version,
        label: `v${v.version} - ${(v.changelog || '').substring(0, 50)}`,
        children: <p>{v.changelog}</p>,
      }))} />

      <Modal title="上传新版本" open={verModalOpen} onCancel={() => setVerModalOpen(false)}
        confirmLoading={uploading} onOk={() => verForm.submit()} okText="上传">
        <Form form={verForm} layout="vertical" onFinish={onUploadVersion}>
          <Form.Item name="file" label="脚本文件 (.py 或 .zip)" rules={[{ required: true }]}
            valuePropName="fileList" getValueFromEvent={(e) => Array.isArray(e) ? e : e?.fileList}>
            <Upload beforeUpload={() => false} maxCount={1} accept=".py,.zip">
              <Button icon={<UploadOutlined />}>选择文件</Button>
            </Upload>
          </Form.Item>
          <Form.Item name="changelog" label="版本说明">
            <Input.TextArea rows={3} placeholder="本次更新内容" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
