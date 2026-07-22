import { useEffect, useState } from 'react'
import { Alert, Card, Form, Input, InputNumber, Button, message, Spin, Popconfirm, Select, Space, Tag } from 'antd'
import { DownloadOutlined, ReloadOutlined, SaveOutlined, UndoOutlined, SettingOutlined } from '@ant-design/icons'
import api from '../api/client'
import { checkUpdate, installUpdate, loadUpdateStatus } from '../api/localUpdate'
import { useConnection } from '../contexts/ConnectionContext'

export default function Settings() {
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [updateBusy, setUpdateBusy] = useState(false)
  const [updateState, setUpdateState] = useState({ state: 'idle' })
  const [form] = Form.useForm()
  const { agentOnline, localApi } = useConnection()

  useEffect(() => {
    setLoading(true)
    api.get('/api/settings')
      .then(r => form.setFieldsValue({
        ...r.data,
        update_manifest_urls: (r.data.update_manifest_urls || []).join('\n'),
      }))
      .catch(() => message.error('加载设置失败'))
      .finally(() => setLoading(false))
  }, [form])

  useEffect(() => {
    if (!agentOnline) return
    loadUpdateStatus(localApi).then(setUpdateState).catch(() => {})
  }, [agentOnline, localApi])

  const runUpdateAction = async (action) => {
    setUpdateBusy(true)
    try {
      const result = action === 'install'
        ? await installUpdate(localApi)
        : await checkUpdate(localApi)
      setUpdateState(result)
      if (result.state === 'installing') message.success('更新安装已启动，客户端将自动重启')
      else if (result.state === 'verified') message.success('更新已下载并验证，可选择安装')
      else message.info('当前没有可用更新')
    } catch (error) {
      const detail = error.response?.data?.error || error.message
      message.error(`更新操作失败：${detail}`)
    } finally {
      setUpdateBusy(false)
    }
  }

  const onSave = async (values) => {
    setSaving(true)
    try {
      const payload = {
        ...values,
        update_manifest_urls: (values.update_manifest_urls || '')
          .split(/\r?\n/)
          .map(value => value.trim())
          .filter(Boolean),
      }
      await api.put('/api/settings', payload)
      message.success('设置已保存，客户端将在一分钟内同步；路径或服务器地址变更需重启客户端')
    } catch (e) {
      message.error(e.response?.data?.detail || '保存失败')
    } finally {
      setSaving(false)
    }
  }

  const onReset = async () => {
    try {
      await api.delete('/api/settings')
      form.resetFields()
      message.success('设置已重置，请重启应用以重新运行设置向导')
    } catch {
      message.error('重置失败')
    }
  }

  if (loading) return <Spin size="large" style={{ display: 'block', marginTop: 100 }} />

  return (
    <div>
      <h2 style={{ marginBottom: 16 }}><SettingOutlined /> 系统设置</h2>

      <Card style={{ maxWidth: 600 }}>
        <Form form={form} layout="vertical" onFinish={onSave}>
          <Form.Item name="server_url" label="服务器地址">
            <Input placeholder="如：http://192.168.1.100:8000" />
          </Form.Item>
          <Form.Item name="script_download_dir" label="脚本下载目录">
            <Input placeholder="如：D:\scripts" />
          </Form.Item>
          <Form.Item name="output_dir" label="输出目录">
            <Input placeholder="如：D:\output" />
          </Form.Item>
          <Form.Item name="default_browser_path" label="默认浏览器路径">
            <Input placeholder="如：C:\Program Files\Google\Chrome\Application\chrome.exe" />
          </Form.Item>
          <Form.Item name="browser_debug_port" label="浏览器调试端口">
            <InputNumber min={0} max={65535} style={{ width: '100%' }} placeholder="9222" />
          </Form.Item>
          <Form.Item name="proxy" label="代理地址">
            <Input placeholder="如：http://127.0.0.1:7890" />
          </Form.Item>
          <Form.Item name="pip_index_url" label="Python 依赖镜像（可选）">
            <Input placeholder="如：https://pypi.tuna.tsinghua.edu.cn/simple" />
          </Form.Item>
          <Form.Item name="github_update_repository" label="GitHub 更新仓库">
            <Input placeholder="CZF39631/AutoScript_Hub" />
          </Form.Item>
          <Form.Item name="update_channel" label="更新通道">
            <Select options={[{ value: 'beta', label: 'Beta 0.9' }, { value: 'stable', label: 'Stable 1.x' }]} />
          </Form.Item>
          <Form.Item
            name="update_manifest_urls"
            label="Gitee / Git Raw / 局域网更新清单"
            extra="每行一个 autoscript-hub-update.json 地址；按顺序尝试，签名文件使用同地址加 .sig。"
          >
            <Input.TextArea rows={4} placeholder={'http://192.168.1.106/releases/autoscript-hub-update.json\nhttps://gitee.com/.../autoscript-hub-update.json'} />
          </Form.Item>

          <div style={{ display: 'flex', gap: 8 }}>
            <Button type="primary" htmlType="submit" icon={<SaveOutlined />} loading={saving}>
              保存设置
            </Button>
            <Popconfirm
              title="确定重置所有设置？重置后需要重新运行设置向导。"
              onConfirm={onReset}
              okText="确定重置"
              cancelText="取消"
            >
              <Button icon={<UndoOutlined />}>重置设置</Button>
            </Popconfirm>
          </div>
        </Form>
      </Card>

      <Card title="客户端更新" style={{ maxWidth: 600, marginTop: 16 }}>
        {!agentOnline && <Alert type="info" showIcon message="此功能仅在 Windows 客户端中可用" />}
        {agentOnline && (
          <Space direction="vertical" style={{ width: '100%' }}>
            <div>
              状态：<Tag>{updateState.state || 'idle'}</Tag>
              {updateState.version && <span>版本：{updateState.version}</span>}
            </div>
            {updateState.error && <Alert type="warning" showIcon message={updateState.error} />}
            <Space>
              <Button icon={<ReloadOutlined />} loading={updateBusy} onClick={() => runUpdateAction('check')}>
                检查并验证更新
              </Button>
              <Button
                type="primary"
                icon={<DownloadOutlined />}
                loading={updateBusy}
                disabled={!['verified', 'waiting-for-idle'].includes(updateState.state)}
                onClick={() => runUpdateAction('install')}
              >
                安装已验证更新
              </Button>
            </Space>
            <div style={{ color: '#888' }}>更新只在用户确认后安装；脚本运行期间会等待至空闲。</div>
          </Space>
        )}
      </Card>
    </div>
  )
}
