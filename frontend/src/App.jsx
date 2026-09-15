import { useEffect } from 'react'
import { Routes, Route, Navigate, useNavigate, useLocation } from 'react-router-dom'
import { Layout, Menu, Button } from 'antd'
import {
  DashboardOutlined, CodeOutlined, HistoryOutlined,
  UserOutlined, LogoutOutlined, AuditOutlined, BugOutlined, GlobalOutlined,
  SettingOutlined, NotificationOutlined, ScheduleOutlined
} from '@ant-design/icons'
import { ConfigProvider, theme } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import enUS from 'antd/locale/en_US'
import dayjs from 'dayjs'
import 'dayjs/locale/zh-cn'
import { useI18n } from './i18n/useI18n'
import LanguageSelect from './components/LanguageSelect'
import { AuthProvider, useAuth } from './contexts/AuthContext'
import { ConnectionProvider, useConnection } from './contexts/ConnectionContext'
import Login from './pages/Login'
import Dashboard from './pages/Dashboard'
import Scripts from './pages/Scripts'
import ScriptDetail from './pages/ScriptDetail'
import Runs from './pages/Runs'
import Tasks from './pages/Tasks'
import RunDetail from './pages/RunDetail'
import Users from './pages/Users'
import AuditLog from './pages/AuditLog'
import Issues from './pages/Issues'
import Environments from './pages/Environments'
import Settings from './pages/Settings'
import Updates from './pages/Updates'
import ImportantUpdateNotice from './components/ImportantUpdateNotice'

const { Sider, Content } = Layout

function PrivateRoute({ children }) {
  const { token } = useAuth()
  return token ? children : <Navigate to="/login" />
}

function OfflineBanner() {
  const { t } = useI18n()
  const { online, agentOnline, pendingSync } = useConnection()
  if (online) return null
  return (
    <div className={`offline-banner ${agentOnline ? 'offline-banner--agent' : 'offline-banner--error'}`}>
      {agentOnline ? (
        <>
          {t('shell.offline')}
          {pendingSync > 0 && t('shell.pendingSync', { count: pendingSync })}
        </>
      ) : (
        <>{t('shell.noAgent')}</>
      )}
    </div>
  )
}

function AppLayout() {
  const { t } = useI18n()
  const { user, logout } = useAuth()
  const { agentOnline } = useConnection()
  const nav = useNavigate()
  const loc = useLocation()

  const baseMenuItems = [
    { key: '/dashboard', icon: <DashboardOutlined />, label: t('shell.dashboard') },
    { key: '/scripts', icon: <CodeOutlined />, label: t('shell.scripts') },
    { key: '/runs', icon: <HistoryOutlined />, label: t('shell.runs') },
    { key: '/tasks', icon: <ScheduleOutlined />, label: t('shell.tasks') },
    { key: '/issues', icon: <BugOutlined />, label: t('shell.issues') },
    { key: '/environments', icon: <GlobalOutlined />, label: t('shell.environments') },
    { key: '/settings', icon: <SettingOutlined />, label: t('shell.settings') },
    { key: '/updates', icon: <NotificationOutlined />, label: t('shell.updates') },
  ]

  const adminItems = [
    { key: '/users', icon: <UserOutlined />, label: t('shell.users') },
    { key: '/audit', icon: <AuditOutlined />, label: t('shell.audit') },
  ]

  const menuItems = user?.role === 'admin'
    ? [...baseMenuItems, ...adminItems]
    : baseMenuItems

  const selectedKey = loc.pathname === '/dashboard' ? '/dashboard'
    : loc.pathname.startsWith('/runs') ? '/runs'
    : loc.pathname.startsWith('/tasks') ? '/tasks'
    : loc.pathname.startsWith('/users') ? '/users'
    : loc.pathname.startsWith('/audit') ? '/audit'
    : loc.pathname.startsWith('/issues') ? '/issues'
    : loc.pathname.startsWith('/environments') ? '/environments'
    : loc.pathname.startsWith('/settings') ? '/settings'
    : loc.pathname.startsWith('/updates') ? '/updates'
    : loc.pathname.startsWith('/scripts') ? '/scripts'
    : '/dashboard'

  return (
    <Layout className="app-shell">
      <Sider width={224} theme="light" className="app-sidebar">
        <div className="app-brand">
          <img className="app-brand__mark" src="/app-icon.png" alt="" />
          <span>
            <strong>AutoScript</strong>
            <small>Hub</small>
          </span>
        </div>
        <Menu className="app-menu" mode="inline" selectedKeys={[selectedKey]} items={menuItems}
          onClick={({ key }) => nav(key)} />
        <div className="app-language"><LanguageSelect /></div>
        <div className={`agent-status ${agentOnline ? 'agent-status--online' : 'agent-status--offline'}`}
          title={t(agentOnline ? 'shell.agentConnected' : 'shell.agentDisconnected')}>
          <span className="agent-status__light" aria-hidden="true" />
          <span>
            <strong>Agent</strong>
            <small>{t(agentOnline ? 'shell.connected' : 'shell.disconnected')}</small>
          </span>
        </div>
        <div className="app-account">
          <div className="app-account__avatar">{(user?.display_name || user?.username || 'U').slice(0, 1).toUpperCase()}</div>
          <div className="app-account__meta">
            <strong>{user?.display_name}</strong>
            <span>{({ admin: t('shell.roleAdmin'), developer: t('shell.roleDeveloper'), operator: t('shell.roleOperator') })[user?.role] || user?.role}</span>
          </div>
          <Button className="app-account__logout" type="text" icon={<LogoutOutlined />} title={t('shell.logout')} aria-label={t('shell.logout')}
            onClick={() => { logout(); nav('/login') }} />
        </div>
      </Sider>
      <Layout className="app-workspace">
        <OfflineBanner />
        <Content className="app-content">
          <ImportantUpdateNotice />
          <Routes>
            <Route path="/dashboard" element={<Dashboard />} />
            <Route path="/scripts" element={<Scripts />} />
            <Route path="/scripts/:id" element={<ScriptDetail />} />
            <Route path="/runs" element={<Runs />} />
            <Route path="/tasks" element={<Tasks />} />
            <Route path="/runs/:id" element={<RunDetail />} />
            <Route path="/users" element={<Users />} />
            <Route path="/audit" element={<AuditLog />} />
            <Route path="/issues" element={<Issues />} />
            <Route path="/environments" element={<Environments />} />
            <Route path="/settings" element={<Settings />} />
            <Route path="/updates" element={<Updates />} />
            <Route path="*" element={<Navigate to="/dashboard" />} />
          </Routes>
        </Content>
      </Layout>
    </Layout>
  )
}

const appleTheme = {
  algorithm: theme.defaultAlgorithm,
  token: {
    colorPrimary: '#007aff',
    colorInfo: '#007aff',
    colorSuccess: '#34c759',
    colorWarning: '#ff9f0a',
    colorError: '#ff3b30',
    colorText: '#1d1d1f',
    colorTextSecondary: '#6e6e73',
    colorBgLayout: '#f5f5f7',
    colorBgContainer: 'rgba(255, 255, 255, 0.86)',
    borderRadius: 10,
    borderRadiusLG: 16,
    controlHeight: 38,
    fontFamily: "-apple-system, BlinkMacSystemFont, 'SF Pro Text', 'PingFang SC', 'Segoe UI', sans-serif",
    boxShadowSecondary: '0 12px 40px rgba(0, 0, 0, 0.08)',
  },
  components: {
    Button: { borderRadius: 10, primaryShadow: '0 4px 14px rgba(0, 122, 255, 0.24)' },
    Card: { borderRadiusLG: 18, boxShadowTertiary: '0 8px 30px rgba(0, 0, 0, 0.055)' },
    Menu: { itemBorderRadius: 10, itemMarginInline: 10, itemHeight: 42 },
    Table: { headerBg: 'rgba(245, 245, 247, 0.78)', headerColor: '#6e6e73' },
    Modal: { borderRadiusLG: 18 },
  },
}

export default function App() {
  const { language } = useI18n()
  useEffect(() => {
    document.documentElement.lang = language
    dayjs.locale(language === 'en-US' ? 'en' : 'zh-cn')
  }, [language])

  return (
    <ConfigProvider locale={language === 'en-US' ? enUS : zhCN} theme={appleTheme}>
      <ConnectionProvider>
        <AuthProvider>
          <Routes>
            <Route path="/login" element={<Login />} />
            <Route path="/*" element={<PrivateRoute><AppLayout /></PrivateRoute>} />
          </Routes>
        </AuthProvider>
      </ConnectionProvider>
    </ConfigProvider>
  )
}
