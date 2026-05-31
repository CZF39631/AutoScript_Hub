import React, { useEffect, useState } from 'react'
import { Card, Form, Input, InputNumber, Button, message, Spin, Popconfirm } from 'antd'
import { SaveOutlined, UndoOutlined, SettingOutlined } from '@ant-design/icons'
import api from '../api/client'

export default function Settings() {
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [form] = Form.useForm()

  useEffect(() => {
    setLoading(true)
    api.get('/api/settings')
      .then(r => form.setFieldsValue(r.data))
      .catch(() => message.error('加载设置失败'))
      .finally(() => setLoading(false))
  }, [])

  const onSave = async (values) => {
    setSaving(true)
    try {
      await api.put('/api/settings', values)
      message.success('设置已保存')
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
    } catch (e) {
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
    </div>
  )
}
