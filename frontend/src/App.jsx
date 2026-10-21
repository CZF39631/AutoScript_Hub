import { useEffect, useRef, useState } from 'react'
import { Routes, Route, Navigate, useNavigate, useLocation } from 'react-router-dom'
import { App as AntdApp, Layout, Menu, Button, Drawer } from 'antd'
import {
  DashboardOutlined, CodeOutlined, HistoryOutlined,
  UserOutlined, LogoutOutlined, AuditOutlined, BugOutlined, GlobalOutlined,
  SettingOutlined, NotificationOutlined, DesktopOutlined, WarningOutlined,
  MenuFoldOutlined, MenuOutlined, MenuUnfoldOutlined,
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
import ManagedControl from './pages/ManagedControl'
import ManagedClientPanel from './pages/ManagedClientPanel'
import ImportantUpdateNotice from './components/ImportantUpdateNotice'
import useMediaQuery from './hooks/useMediaQuery'
import { isManagedClientMode } from './utils/managed'

const { Sider, Content } = Layout

function PrivateRoute({ children }) {
  const { token } = useAuth()
  return token ? children : <Navigate to="/login" />
}

function AdminRoute({ children }) {
  const { user } = useAuth()
  return user?.role === 'admin' ? children : <Navigate to="/dashboard" />
}

function OfflineBanner() {
  const { online, agentOnline, pendingSync } = useConnection()
  if (online) return null
  return (
    <div className={`offline-banner ${agentOnline ? 'offline-banner--agent' : 'offline-banner--error'}`}>
      {agentOnline ? (
        <>
          <WarningOutlined /> 与服务器断开,已切换到 <strong>离线模式</strong>。可执行已下载的脚本,结果会在恢复连接后自动同步
          {pendingSync > 0 && <>(待同步 {pendingSync} 条)</>}
        </>
      ) : (
        <><WarningOutlined /> 与服务器断开,且本地 Agent 不可用。请检查 Agent 进程是否运行</>
      )}
    </div>
  )
}

function AppLayout() {
  const { user, logout } = useAuth()
  const { agentOnline } = useConnection()
  const nav = useNavigate()
  const loc = useLocation()
  const isCompact = useMediaQuery('(max-width: 900px)')
  const isMobile = useMediaQuery('(max-width: 640px)')
  const [sidebarCollapsed, setSidebarCollapsed] = useState(isCompact)
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false)
  const mobileMenuButton = useRef(null)

  useEffect(() => {
    setSidebarCollapsed(isCompact)
  }, [isCompact])

  useEffect(() => {
    if (!isMobile) setMobileMenuOpen(false)
  }, [isMobile])

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
    { key: '/managed-agents', icon: <DesktopOutlined />, label: '设备托管' },
    { key: '/users', icon: <UserOutlined />, label: '用户管理' },
    { key: '/audit', icon: <AuditOutlined />, label: '操作审计' },
  ]

  const menuItems = user?.role === 'admin'
    ? [...baseMenuItems, ...adminItems]
    : baseMenuItems

  const selectedKey = loc.pathname === '/dashboard' ? '/dashboard'
    : loc.pathname.startsWith('/runs') ? '/runs'
    : loc.pathname.startsWith('/managed-agents') ? '/managed-agents'
    : loc.pathname.startsWith('/managed-schedules') ? '/managed-agents'
    : loc.pathname.startsWith('/users') ? '/users'
    : loc.pathname.startsWith('/audit') ? '/audit'
    : loc.pathname.startsWith('/issues') ? '/issues'
    : loc.pathname.startsWith('/environments') ? '/environments'
    : loc.pathname.startsWith('/settings') ? '/settings'
    : loc.pathname.startsWith('/updates') ? '/updates'
    : loc.pathname.startsWith('/scripts') ? '/scripts'
    : '/dashboard'

  const goTo = key => {
    nav(key)
    if (isMobile) {
      setMobileMenuOpen(false)
      requestAnimationFrame(() => mobileMenuButton.current?.focus())
    }
  }

  const closeMobileNavigation = () => {
    setMobileMenuOpen(false)
    requestAnimationFrame(() => mobileMenuButton.current?.focus())
  }

  const navigationContents = ({ collapsed = false } = {}) => (
    <>
      <div className="app-brand">
        <img className="app-brand__mark" src="/app-icon.png" alt="" />
        {!collapsed && (
          <span>
            <strong>AutoScript</strong>
            <small>Hub</small>
          </span>
        )}
      </div>
      <Menu className="app-menu" mode="inline" inlineCollapsed={collapsed} selectedKeys={[selectedKey]} items={menuItems}
        onClick={({ key }) => goTo(key)} />
      <div className={`agent-status ${agentOnline ? 'agent-status--online' : 'agent-status--offline'}`}
        title={agentOnline ? '本地 Agent 连接正常' : '本地 Agent 未启动或连接失败'}>
        <span className="agent-status__light" aria-hidden="true" />
        {!collapsed && (
          <span>
            <strong>Agent</strong>
            <small>{agentOnline ? '连接正常' : '未启动或连接失败'}</small>
          </span>
        )}
        {collapsed && <span className="visually-hidden">Agent {agentOnline ? '连接正常' : '未启动或连接失败'}</span>}
      </div>
      <div className="app-account">
        <div className="app-account__avatar" aria-label={`当前用户：${user?.display_name || user?.username || '用户'}`}>
          {(user?.display_name || user?.username || 'U').slice(0, 1).toUpperCase()}
        </div>
        {!collapsed && (
          <div className="app-account__meta">
            <strong>{user?.display_name}</strong>
            <span>{user?.role}</span>
          </div>
        )}
        <Button className="app-account__logout" type="text" icon={<LogoutOutlined aria-hidden="true" />} aria-label="退出登录"
          onClick={() => { logout(); nav('/login') }} />
      </div>
    </>
  )

  return (
    <Layout className={`app-shell${isMobile ? ' app-shell--mobile' : ''}`}>
      {!isMobile && (
        <Sider
          width={224}
          collapsedWidth={76}
          collapsed={sidebarCollapsed}
          theme="light"
          className="app-sidebar"
        >
          {navigationContents({ collapsed: sidebarCollapsed })}
          {isCompact && (
            <Button
              className="app-sidebar-toggle"
              type="text"
              icon={sidebarCollapsed ? <MenuUnfoldOutlined aria-hidden="true" /> : <MenuFoldOutlined aria-hidden="true" />}
              aria-label={sidebarCollapsed ? '展开侧边导航' : '收起侧边导航'}
              aria-expanded={!sidebarCollapsed}
              onClick={() => setSidebarCollapsed(value => !value)}
            />
          )}
        </Sider>
      )}
      <Layout className="app-workspace">
        {isMobile && (
          <header className="app-mobile-header">
            <Button
              ref={mobileMenuButton}
              className="app-mobile-menu-button"
              type="text"
              icon={<MenuOutlined aria-hidden="true" />}
              aria-label={mobileMenuOpen ? '关闭主导航菜单' : '打开主导航菜单'}
              aria-expanded={mobileMenuOpen}
              aria-controls="app-mobile-navigation"
              onClick={() => setMobileMenuOpen(value => !value)}
            />
            <div className="app-mobile-brand">
              <img src="/app-icon.png" alt="" />
              <strong>AutoScript Hub</strong>
            </div>
          </header>
        )}
        {isMobile && mobileMenuOpen && (
          <Drawer
            id="app-mobile-navigation"
            rootClassName="app-mobile-navigation"
            title="主导航"
            placement="left"
            size="min(86vw, 320px)"
            open
            onClose={closeMobileNavigation}
            destroyOnHidden
          >
            <nav aria-label="主导航">{navigationContents()}</nav>
          </Drawer>
        )}
        <OfflineBanner />
        <Content className="app-content">
          <ImportantUpdateNotice />
          <Routes>
            <Route path="/dashboard" element={<Dashboard />} />
            <Route path="/scripts" element={<Scripts />} />
            <Route path="/scripts/:id" element={<ScriptDetail />} />
            <Route path="/runs" element={<Runs />} />
            <Route path="/runs/:id" element={<RunDetail />} />
            <Route path="/managed-agents" element={<AdminRoute><ManagedControl /></AdminRoute>} />
            <Route path="/managed-schedules" element={<Navigate to="/managed-agents" replace />} />
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
  const managedMode = isManagedClientMode()
  return (
    <ConfigProvider locale={zhCN} theme={appleTheme}>
      <AntdApp>
        <ConnectionProvider>
          {managedMode ? (
            <Routes>
              <Route path="/managed" element={<ManagedClientPanel />} />
              <Route path="*" element={<Navigate to="/managed" replace />} />
            </Routes>
          ) : (
            <AuthProvider>
              <Routes>
                <Route path="/login" element={<Login />} />
                <Route path="/*" element={<PrivateRoute><AppLayout /></PrivateRoute>} />
              </Routes>
            </AuthProvider>
          )}
        </ConnectionProvider>
      </AntdApp>
    </ConfigProvider>
  )
}
