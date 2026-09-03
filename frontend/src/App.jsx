import { Routes, Route, Navigate, useNavigate, useLocation } from 'react-router-dom'
import { Layout, Menu, Button } from 'antd'
import {
  DashboardOutlined, CodeOutlined, HistoryOutlined,
  UserOutlined, LogoutOutlined, AuditOutlined, BugOutlined, GlobalOutlined,
  SettingOutlined, NotificationOutlined
} from '@ant-design/icons'
import { ConfigProvider, theme } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import { AuthProvider, useAuth } from './contexts/AuthContext'
import { ConnectionProvider, useConnection } from './contexts/ConnectionContext'
import Login from './pages/Login'
import Dashboard from './pages/Dashboard'
import Scripts from './pages/Scripts'
import ScriptDetail from './pages/ScriptDetail'
import Runs from './pages/Runs'
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
  const { online, agentOnline, pendingSync } = useConnection()
  if (online) return null
  return (
    <div className={`offline-banner ${agentOnline ? 'offline-banner--agent' : 'offline-banner--error'}`}>
      {agentOnline ? (
        <>
          ⚠️ 与服务器断开,已切换到 <strong>离线模式</strong>。可执行已下载的脚本,结果会在恢复连接后自动同步
          {pendingSync > 0 && <>(待同步 {pendingSync} 条)</>}
        </>
      ) : (
        <>⚠️ 与服务器断开,且本地 Agent 不可用。请检查 Agent 进程是否运行</>
      )}
    </div>
  )
}

function AppLayout() {
  const { user, logout } = useAuth()
  const { agentOnline } = useConnection()
  const nav = useNavigate()
  const loc = useLocation()

  const baseMenuItems = [
    { key: '/dashboard', icon: <DashboardOutlined />, label: '仪表盘' },
    { key: '/scripts', icon: <CodeOutlined />, label: '脚本管理' },
    { key: '/runs', icon: <HistoryOutlined />, label: '执行历史' },
    { key: '/issues', icon: <BugOutlined />, label: '问题工单' },
    { key: '/environments', icon: <GlobalOutlined />, label: '环境管理' },
    { key: '/settings', icon: <SettingOutlined />, label: '系统设置' },
    { key: '/updates', icon: <NotificationOutlined />, label: '更新说明' },
  ]

  const adminItems = [
    { key: '/users', icon: <UserOutlined />, label: '用户管理' },
    { key: '/audit', icon: <AuditOutlined />, label: '操作审计' },
  ]

  const menuItems = user?.role === 'admin'
    ? [...baseMenuItems, ...adminItems]
    : baseMenuItems

  const selectedKey = loc.pathname === '/dashboard' ? '/dashboard'
    : loc.pathname.startsWith('/runs') ? '/runs'
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
          <span className="app-brand__mark">A</span>
          <span>
            <strong>AutoScript</strong>
            <small>Hub</small>
          </span>
        </div>
        <Menu className="app-menu" mode="inline" selectedKeys={[selectedKey]} items={menuItems}
          onClick={({ key }) => nav(key)} />
        <div className={`agent-status ${agentOnline ? 'agent-status--online' : 'agent-status--offline'}`}
          title={agentOnline ? '本地 Agent 连接正常' : '本地 Agent 未启动或连接失败'}>
          <span className="agent-status__light" aria-hidden="true" />
          <span>
            <strong>Agent</strong>
            <small>{agentOnline ? '连接正常' : '未启动或连接失败'}</small>
          </span>
        </div>
        <div className="app-account">
          <div className="app-account__avatar">{(user?.display_name || user?.username || 'U').slice(0, 1).toUpperCase()}</div>
          <div className="app-account__meta">
            <strong>{user?.display_name}</strong>
            <span>{user?.role}</span>
          </div>
          <Button className="app-account__logout" type="text" icon={<LogoutOutlined />} title="退出登录"
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
  return (
    <ConfigProvider locale={zhCN} theme={appleTheme}>
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
