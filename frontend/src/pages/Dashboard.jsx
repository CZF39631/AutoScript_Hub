import React, { useEffect, useState } from 'react'
import { Card, Col, Row, Statistic, Table, Tag, Spin, Progress } from 'antd'
import {
  CheckCircleOutlined, CloseCircleOutlined, ThunderboltOutlined,
  CodeOutlined, TeamOutlined, HistoryOutlined
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

  return (
    <div>
      <h2>仪表盘</h2>

      <Row gutter={[16, 16]}>
        <Col span={6}>
          <Card>
            <Statistic title="今日执行" value={stats.today_runs}
              prefix={<ThunderboltOutlined style={{ color: '#1890ff' }} />}
              suffix={<span style={{ fontSize: 14, color: '#999' }}>/ {stats.week_runs} 本周</span>} />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic title="今日成功" value={stats.today_success} valueStyle={{ color: '#52c41a' }}
              prefix={<CheckCircleOutlined />}
              suffix={<span style={{ fontSize: 14 }}>{stats.today_success_rate}%</span>} />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic title="今日失败" value={stats.today_failed} valueStyle={{ color: '#ff4d4f' }}
              prefix={<CloseCircleOutlined />} />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic title="在线用户" value={stats.online_users}
              prefix={<TeamOutlined style={{ color: '#722ed1' }} />}
              suffix={<span style={{ fontSize: 14, color: '#999' }}>/ {stats.total_users} 总</span>} />
          </Card>
        </Col>
      </Row>

      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        <Col span={12}>
          <Card title="本周成功率" size="small">
            <Progress type="dashboard" percent={stats.week_success_rate}
              format={p => `${p}%`}
              strokeColor={{ '0%': '#108ee9', '100%': '#87d068' }} />
            <div style={{ textAlign: 'center', color: '#999', marginTop: 8 }}>
              {stats.week_success} / {stats.week_runs} 次成功
            </div>
          </Card>
        </Col>
        <Col span={12}>
          <Card size="small">
            <div style={{ display: 'flex', justifyContent: 'space-around', padding: '12px 0' }}>
              <Statistic title="脚本总数" value={stats.total_scripts} prefix={<CodeOutlined />} />
              <Statistic title="执行总数" value={stats.total_runs} prefix={<HistoryOutlined />} />
              <Statistic title="用户总数" value={stats.total_users} prefix={<TeamOutlined />} />
            </div>
          </Card>
        </Col>
      </Row>

      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        <Col span={12}>
          <Card title="本周脚本排行" size="small">
            <Table dataSource={stats.script_ranking} columns={rankColumns}
              rowKey="script_name" size="small" pagination={false} />
          </Card>
        </Col>
        <Col span={12}>
          <Card title="最近失败任务" size="small">
            <Table dataSource={stats.recent_failed} columns={failedColumns}
              rowKey="run_id" size="small" pagination={false} />
          </Card>
        </Col>
      </Row>
    </div>
  )
}
