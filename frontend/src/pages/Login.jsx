import { useState } from 'react'
import { Alert, Form, Input, Button, Card, message } from 'antd'
import { UserOutlined, LockOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'

export default function Login() {
  const { login } = useAuth()
  const nav = useNavigate()
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  const onFinish = async (values) => {
    setError('')
    setSubmitting(true)
    try {
      await login(values.username, values.password)
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
    <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', minHeight: '100vh', background: '#f0f2f5' }}>
      <Card title="AutoScript Hub" style={{ width: 360 }}>
        <Form onFinish={onFinish} onValuesChange={() => setError('')}>
          {error && (
            <Alert
              type="error"
              showIcon
              message={error}
              style={{ marginBottom: 16 }}
              role="alert"
            />
          )}
          <Form.Item name="username" rules={[{ required: true, message: '请输入用户名' }]}>
            <Input prefix={<UserOutlined />} placeholder="用户名" />
          </Form.Item>
          <Form.Item name="password" rules={[{ required: true, message: '请输入密码' }]}>
            <Input.Password prefix={<LockOutlined />} placeholder="密码" />
          </Form.Item>
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
