import { useEffect, useState } from 'react'
import { Alert, Form, Input, Button, Card, Checkbox, message } from 'antd'
import { UserOutlined, LockOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'

export default function Login() {
  const { login } = useAuth()
  const nav = useNavigate()
  const [form] = Form.useForm()
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [desktopCredentials, setDesktopCredentials] = useState(false)

  useEffect(() => {
    let disposed = false
    const loadSavedCredentials = async () => {
      const api = window.pywebview?.api
      if (!api?.getSavedCredentials) return
      try {
        const saved = await api.getSavedCredentials()
        if (disposed) return
        setDesktopCredentials(true)
        form.setFieldsValue({
          username: saved?.username || '',
          password: saved?.remember ? (saved?.password || '') : '',
          remember: Boolean(saved?.remember),
        })
      } catch {
        // Browser login and unavailable desktop credential stores remain usable.
      }
    }
    loadSavedCredentials()
    window.addEventListener('pywebviewready', loadSavedCredentials)
    return () => {
      disposed = true
      window.removeEventListener('pywebviewready', loadSavedCredentials)
    }
  }, [form])

  const onFinish = async (values) => {
    setError('')
    setSubmitting(true)
    try {
      await login(values.username, values.password)
      const api = window.pywebview?.api
      if (api?.saveCredentials && typeof values.remember === 'boolean') {
        try {
          await api.saveCredentials(values.username, values.password, values.remember)
        } catch {
          message.warning('登录成功，但未能保存账号密码')
        }
      }
      message.success('登录成功')
      nav('/scripts')
    } catch (e) {
      const detail = e.response?.data?.detail
      const text = typeof detail === 'string'
        ? detail
        : e.response
          ? `登录失败（HTTP ${e.response.status}）`
          : '无法连接服务端，请检查服务是否已经启动'
      setError(text)
      message.error(text)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="login-page">
      <Card className="login-card" bordered={false}>
        <div className="login-brand">
          <div className="login-brand__icon">A</div>
          <h1>AutoScript Hub</h1>
          <p>安全、清晰地管理自动化脚本</p>
        </div>
        <Form form={form} layout="vertical" onFinish={onFinish} onValuesChange={() => setError('')}>
          {error && (
            <Alert
              type="error"
              showIcon
              message={error}
              style={{ marginBottom: 16 }}
              role="alert"
            />
          )}
          <Form.Item name="username" label="账号" rules={[{ required: true, message: '请输入用户名' }]}>
            <Input prefix={<UserOutlined />} placeholder="用户名" autoComplete="username" />
          </Form.Item>
          <Form.Item name="password" label="密码" rules={[{ required: true, message: '请输入密码' }]}>
            <Input.Password prefix={<LockOutlined />} placeholder="密码" autoComplete="current-password" />
          </Form.Item>
          {desktopCredentials && (
            <Form.Item name="remember" valuePropName="checked" initialValue={false}>
              <Checkbox>记住账号密码</Checkbox>
            </Form.Item>
          )}
          <Form.Item>
            <Button type="primary" htmlType="submit" loading={submitting} block>
              {submitting ? '正在登录…' : '登录'}
            </Button>
          </Form.Item>
        </Form>
      </Card>
    </div>
  )
}
