import { useEffect, useState } from 'react'
import { Alert, Form, Input, Button, Card, Checkbox, message } from 'antd'
import { UserOutlined, LockOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import { useI18n } from '../i18n/useI18n'
import { describeLoginError, renderLoginError } from '../i18n/loginError'
import LanguageSelect from '../components/LanguageSelect'

export default function Login() {
  const { t } = useI18n()
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
          message.warning(t('shell.credentialsNotSaved'))
        }
      }
      message.success(t('shell.loggedIn'))
      nav('/scripts')
    } catch (e) {
      const described = describeLoginError(e)
      setError(described)
      message.error(renderLoginError(described, t))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="login-page">
      <Card className="login-card" bordered={false}>
        <div className="login-language"><LanguageSelect /></div>
        <div className="login-brand">
          <img className="login-brand__icon" src="/app-icon.png" alt="AutoScript Hub" />
          <h1>AutoScript Hub</h1>
          <p>{t('shell.tagline')}</p>
        </div>
        <Form form={form} layout="vertical" onFinish={onFinish} onValuesChange={() => setError('')}>
          {error && (
            <Alert
              type="error"
              showIcon
              message={renderLoginError(error, t)}
              style={{ marginBottom: 16 }}
              role="alert"
            />
          )}
          <Form.Item name="username" label={t('shell.account')} rules={[{ required: true, message: t('shell.enterUsername') }]}>
            <Input prefix={<UserOutlined />} placeholder={t('shell.username')} autoComplete="username" />
          </Form.Item>
          <Form.Item name="password" label={t('shell.password')} rules={[{ required: true, message: t('shell.enterPassword') }]}>
            <Input.Password prefix={<LockOutlined />} placeholder={t('shell.password')} autoComplete="current-password" />
          </Form.Item>
          {desktopCredentials && (
            <Form.Item name="remember" valuePropName="checked" initialValue={false}>
              <Checkbox>{t('shell.rememberCredentials')}</Checkbox>
            </Form.Item>
          )}
          <Form.Item>
            <Button type="primary" htmlType="submit" loading={submitting} block>
              {t(submitting ? 'shell.loggingIn' : 'shell.login')}
            </Button>
          </Form.Item>
        </Form>
      </Card>
    </div>
  )
}
