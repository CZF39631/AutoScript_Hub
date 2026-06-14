import React from 'react'
import { Routes, Route, Navigate, useNavigate, useLocation } from 'react-router-dom'
import { Layout, Menu, Button } from 'antd'
import {
  DashboardOutlined, CodeOutlined, HistoryOutlined,
  UserOutlined, LogoutOutlined, AuditOutlined, BugOutlined, GlobalOutlined,
  SettingOutlined
} from '@ant-design/icons'
import { ConfigProvider } from 'antd'
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

const { Sider, Content } = Layout

function PrivateRoute({ children }) {
  const { token } = useAuth()
  return token ? children : <Navigate to="/login" />
}

function OfflineBanner() {
  const { online, agentOnline, pendingSync } = useConnection()
  if (online) return null
  const bg = agentOnline ? '#fffbe6' : '#fff1f0'
  const border = agentOnline ? '#ffe58f' : '#ffa39e'
  return (
    <div style={{
      background: bg, padding: '8px 24px', borderBottom: `1px solid ${border}`,
      fontSize: 13,
    }}>
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
  const nav = useNavigate()
  const loc = useLocation()

  const baseMenuItems = [
    { key: '/dashboard', icon: <DashboardOutlined />, label: '仪表盘' },
    { key: '/scripts', icon: <CodeOutlined />, label: '脚本管理' },
    { key: '/runs', icon: <HistoryOutlined />, label: '执行历史' },
    { key: '/issues', icon: <BugOutlined />, label: '问题工单' },
    { key: '/environments', icon: <GlobalOutlined />, label: '环境管理' },
    { key: '/settings', icon: <SettingOutlined />, label: '系统设置' },
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
    : loc.pathname.startsWith('/scripts') ? '/scripts'
    : '/dashboard'

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Sider width={200} theme="light">
        <div style={{ padding: '16px', fontSize: 16, fontWeight: 'bold', borderBottom: '1px solid #f0f0f0' }}>
          AutoScript Hub
        </div>
        <Menu mode="inline" selectedKeys={[selectedKey]} items={menuItems}
          onClick={({ key }) => nav(key)} style={{ borderRight: 0 }} />
        <div style={{ position: 'absolute', bottom: 0, width: '100%', padding: 16, borderTop: '1px solid #f0f0f0' }}>
          <div style={{ fontSize: 12, marginBottom: 8, color: '#999' }}>{user?.display_name} ({user?.role})</div>
          <Button icon={<LogoutOutlined />} block size="small" onClick={() => { logout(); nav('/login') }}>退出</Button>
        </div>
      </Sider>
      <Layout>
        <OfflineBanner />
        <Content style={{ padding: 24, background: '#f5f5f5', minHeight: 'auto' }}>
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
            <Route path="*" element={<Navigate to="/dashboard" />} />
          </Routes>
        </Content>
      </Layout>
    </Layout>
  )
}

export default function App() {
  return (
    <ConfigProvider locale={zhCN}>
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
