import { useEffect, useState } from 'react'
import { Card, Col, Row, Statistic, Table, Spin, Progress } from 'antd'
import {
  CheckCircleOutlined, CloseCircleOutlined, ThunderboltOutlined,
  CodeOutlined, TeamOutlined, HistoryOutlined,
} from '@ant-design/icons'
import api from '../api/client'
import { formatServerTime } from '../utils/dateTime'
import { useI18n } from '../i18n/useI18n'

export default function Dashboard() {
  const { t } = useI18n()
  const [stats, setStats] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.get('/api/dashboard/stats').then(r => setStats(r.data))
      .catch(() => {}).finally(() => setLoading(false))
  }, [])

  if (loading) return <Spin size="large" style={{ display: 'block', marginTop: 100 }} />
  if (!stats) return <div>{t('management.loadFailed')}</div>

  const failedColumns = [
    { title: t('management.script'), dataIndex: 'script_name', key: 'name', width: 140, ellipsis: true },
    { title: t('management.user'), dataIndex: 'username', key: 'user', width: 90 },
    { title: t('management.error'), dataIndex: 'error_msg', key: 'err', ellipsis: true },
    { title: t('management.time'), dataIndex: 'created_at', key: 'time', width: 160,
      render: formatServerTime },
  ]
  const rankColumns = [
    { title: t('management.script'), dataIndex: 'script_name', key: 'name', ellipsis: true },
    { title: t('management.runCount'), dataIndex: 'count', key: 'cnt', width: 100 },
  ]

  const metrics = [
    { key: 'runs', tone: 'blue', title: t('management.todayRuns'), value: stats.today_runs,
      icon: <ThunderboltOutlined />, suffix: t('management.weekSuffix', { count: stats.week_runs }) },
    { key: 'success', tone: 'green', title: t('management.todaySuccess'), value: stats.today_success,
      icon: <CheckCircleOutlined />, suffix: `${stats.today_success_rate}%` },
    { key: 'failed', tone: 'red', title: t('management.todayFailed'), value: stats.today_failed,
      icon: <CloseCircleOutlined /> },
    { key: 'online', tone: 'purple', title: t('management.onlineUsers'), value: stats.online_users,
      icon: <TeamOutlined />, suffix: t('management.totalSuffix', { count: stats.total_users }) },
  ]

  return (
    <div className="dashboard-page">
      <div className="page-heading">
        <div>
          <h2>{t('management.dashboard')}</h2>
          <p>{t('management.dashboardSummary')}</p>
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
          <Card className="dashboard-panel" title={t('management.weekSuccessRate')}>
            <div className="success-overview">
              <Progress type="dashboard" width={132} percent={stats.week_success_rate}
                format={p => `${p}%`}
                strokeColor={{ '0%': '#007aff', '100%': '#34c759' }} />
              <div className="success-overview__text">
                <strong>{t('management.weekSuccess', { count: stats.week_success })}</strong>
                <span>{t('management.weekRuns', { count: stats.week_runs })}</span>
              </div>
            </div>
          </Card>
        </Col>
        <Col xs={24} xl={12}>
          <Card className="dashboard-panel dashboard-totals">
            <div className="dashboard-totals__grid">
              <Statistic title={t('management.totalScripts')} value={stats.total_scripts} prefix={<CodeOutlined />} />
              <Statistic title={t('management.totalRuns')} value={stats.total_runs} prefix={<HistoryOutlined />} />
              <Statistic title={t('management.totalUsers')} value={stats.total_users} prefix={<TeamOutlined />} />
            </div>
          </Card>
        </Col>
      </Row>

      <Row gutter={[18, 18]} className="dashboard-section">
        <Col xs={24} xl={12}>
          <Card className="dashboard-panel" title={t('management.weekRanking')}>
            <Table locale={{ emptyText: t('management.empty') }} dataSource={stats.script_ranking} columns={rankColumns}
              rowKey="script_name" size="small" pagination={false} />
          </Card>
        </Col>
        <Col xs={24} xl={12}>
          <Card className="dashboard-panel" title={t('management.recentFailures')}>
            <Table locale={{ emptyText: t('management.empty') }} dataSource={stats.recent_failed} columns={failedColumns}
              rowKey="run_id" size="small" pagination={false} />
          </Card>
        </Col>
      </Row>
    </div>
  )
}
