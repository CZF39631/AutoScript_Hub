import { useEffect, useState } from 'react'
import { Alert, Card, Collapse, List, Space, Switch, Tag, Typography } from 'antd'
import { BellOutlined, NotificationOutlined } from '@ant-design/icons'
import { useConnection } from '../contexts/ConnectionContext'
import { currentRelease, releaseHistory } from '../data/releaseNotes'
import {
  importantUpdatesHidden,
  setImportantUpdatesHidden,
  UPDATE_NOTICE_CHANGED_EVENT,
} from '../utils/updateNotices'

const { Paragraph, Text, Title } = Typography
const bundledVersion = import.meta.env.VITE_AUTOSCRIPT_VERSION || ''

function ReleaseSections({ release }) {
  return release.sections?.map(section => (
    <div key={section.title} style={{ marginTop: 14 }}>
      <Text strong>{section.title}</Text>
      <List
        size="small"
        dataSource={section.items}
        renderItem={item => <List.Item style={{ paddingInline: 0 }}>• {item}</List.Item>}
      />
    </div>
  ))
}

export default function Updates() {
  const { agentOnline, localApi } = useConnection()
  const [installedVersion, setInstalledVersion] = useState('')
  const [hideImportant, setHideImportant] = useState(() => importantUpdatesHidden())

  useEffect(() => {
    if (!agentOnline) return
    localApi.get('/local/update')
      .then(({ data }) => setInstalledVersion(data?.current_version || ''))
      .catch(() => {})
  }, [agentOnline, localApi])

  useEffect(() => {
    const refreshPreference = () => setHideImportant(importantUpdatesHidden())
    window.addEventListener(UPDATE_NOTICE_CHANGED_EVENT, refreshPreference)
    return () => window.removeEventListener(UPDATE_NOTICE_CHANGED_EVENT, refreshPreference)
  }, [])

  const changePreference = checked => {
    setImportantUpdatesHidden(checked)
    setHideImportant(checked)
  }

  return (
    <div>
      <h2 style={{ marginBottom: 16 }}><NotificationOutlined /> 更新说明</h2>

      <Card style={{ maxWidth: 820, marginBottom: 16 }}>
        <Space direction="vertical" size={12} style={{ width: '100%' }}>
          <Space wrap>
            <Tag color="blue">最新更新</Tag>
            {currentRelease.important && <Tag color="red">重要更新</Tag>}
            {(bundledVersion || installedVersion) && <Tag>版本 v{bundledVersion || installedVersion}</Tag>}
            {installedVersion && bundledVersion && installedVersion !== bundledVersion && (
              <Tag color="orange">本地 Agent v{installedVersion}</Tag>
            )}
          </Space>
          <Title level={3} style={{ margin: 0 }}>{currentRelease.title}</Title>
          <Paragraph type="secondary" style={{ marginBottom: 0 }}>{currentRelease.summary}</Paragraph>
          <ReleaseSections release={currentRelease} />
        </Space>
      </Card>

      <Card title={<Space><BellOutlined />提醒设置</Space>} style={{ maxWidth: 820, marginBottom: 16 }}>
        <Space direction="vertical">
          <Space>
            <Switch checked={hideImportant} onChange={changePreference} />
            <Text>默认隐藏重要更新弹窗</Text>
          </Space>
          <Text type="secondary">
            关闭默认隐藏后，重要更新会在升级后的首次运行中弹出一次；普通更新不会打扰你。
          </Text>
        </Space>
      </Card>

      {!agentOnline && (
        <Alert
          style={{ maxWidth: 820, marginBottom: 16 }}
          type="info"
          showIcon
          message="当前未连接本地 Agent，无法读取已安装客户端版本"
        />
      )}

      <Card title="历史版本" style={{ maxWidth: 820 }}>
        <Collapse
          items={releaseHistory.map(release => ({
            key: release.id,
            label: <Space><Tag>v{release.version}</Tag><Text strong>{release.title}</Text></Space>,
            children: (
              <>
                <Paragraph type="secondary">{release.summary}</Paragraph>
                <ReleaseSections release={release} />
              </>
            ),
          }))}
        />
      </Card>
    </div>
  )
}
