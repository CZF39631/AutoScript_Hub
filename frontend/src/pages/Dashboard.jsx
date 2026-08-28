import { useEffect, useState } from 'react'
import { Card, Col, Row, Statistic, Table, Spin, Progress } from 'antd'
import {
  CheckCircleOutlined, CloseCircleOutlined, ThunderboltOutlined,
  CodeOutlined, TeamOutlined, HistoryOutlined,
} from '@ant-design/icons'
import api from '../api/client'

export default function Dashboard() {
  const [stats, setStats] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.get('/api/dashboard/stats').then(r => setStats(r.data))
      .catch(() => {}).finally(() => setLoading(false))
  }, [])

  if (loading) return <Spin size="large" style={{ display: 'block', marginTop: 100 }} />
  if (!stats) return <div>加载失败</div>

  const failedColumns = [
    { title: '脚本', dataIndex: 'script_name', key: 'name', width: 140, ellipsis: true },
    { title: '用户', dataIndex: 'username', key: 'user', width: 90 },
    { title: '错误', dataIndex: 'error_msg', key: 'err', ellipsis: true },
    { title: '时间', dataIndex: 'created_at', key: 'time', width: 160,
      render: (t) => t ? new Date(t).toLocaleString() : '-' },
  ]
  const rankColumns = [
    { title: '脚本', dataIndex: 'script_name', key: 'name', ellipsis: true },
    { title: '执行次数', dataIndex: 'count', key: 'cnt', width: 100 },
  ]

  const metrics = [
    { key: 'runs', tone: 'blue', title: '今日执行', value: stats.today_runs,
      icon: <ThunderboltOutlined />, suffix: `/ ${stats.week_runs} 本周` },
    { key: 'success', tone: 'green', title: '今日成功', value: stats.today_success,
      icon: <CheckCircleOutlined />, suffix: `${stats.today_success_rate}%` },
    { key: 'failed', tone: 'red', title: '今日失败', value: stats.today_failed,
      icon: <CloseCircleOutlined /> },
    { key: 'online', tone: 'purple', title: '在线用户', value: stats.online_users,
      icon: <TeamOutlined />, suffix: `/ ${stats.total_users} 总` },
  ]

  return (
    <div className="dashboard-page">
      <div className="page-heading">
        <div>
          <h2>仪表盘</h2>
          <p>概览脚本运行状态与系统活动</p>
        </div>
      </div>

      <Row gutter={[18, 18]}>
        {metrics.map(item => (
          <Col xs={12} xl={6} key={item.key}>
            <Card className={`metric-card metric-card--${item.tone}`}>
              <Statistic title={item.title} value={item.value}
                prefix={<span className="metric-icon">{item.icon}</span>}
                suffix={item.suffix && <span className="metric-suffix">{item.suffix}</span>} />
            </Card>
          </Col>
        ))}
      </Row>

      <Row gutter={[18, 18]} className="dashboard-section">
        <Col xs={24} xl={12}>
          <Card className="dashboard-panel" title="本周成功率">
            <div className="success-overview">
              <Progress type="dashboard" width={132} percent={stats.week_success_rate}
                format={p => `${p}%`}
                strokeColor={{ '0%': '#007aff', '100%': '#34c759' }} />
              <div className="success-overview__text">
                <strong>{stats.week_success} 次成功</strong>
                <span>本周共执行 {stats.week_runs} 次</span>
              </div>
            </div>
          </Card>
        </Col>
        <Col xs={24} xl={12}>
          <Card className="dashboard-panel dashboard-totals">
            <div className="dashboard-totals__grid">
              <Statistic title="脚本总数" value={stats.total_scripts} prefix={<CodeOutlined />} />
              <Statistic title="执行总数" value={stats.total_runs} prefix={<HistoryOutlined />} />
              <Statistic title="用户总数" value={stats.total_users} prefix={<TeamOutlined />} />
            </div>
          </Card>
        </Col>
      </Row>

      <Row gutter={[18, 18]} className="dashboard-section">
        <Col xs={24} xl={12}>
          <Card className="dashboard-panel" title="本周脚本排行">
            <Table dataSource={stats.script_ranking} columns={rankColumns}
              rowKey="script_name" size="small" pagination={false} />
          </Card>
        </Col>
        <Col xs={24} xl={12}>
          <Card className="dashboard-panel" title="最近失败任务">
            <Table dataSource={stats.recent_failed} columns={failedColumns}
              rowKey="run_id" size="small" pagination={false} />
          </Card>
        </Col>
      </Row>
    </div>
  )
}
