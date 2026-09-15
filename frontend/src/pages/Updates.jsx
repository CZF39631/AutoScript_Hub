import { useEffect, useState } from 'react'
import { Alert, Card, Collapse, List, Space, Switch, Tag, Typography } from 'antd'
import { BellOutlined, NotificationOutlined } from '@ant-design/icons'
import { useConnection } from '../contexts/ConnectionContext'
import { useI18n } from '../i18n/useI18n'
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
  const { t } = useI18n()
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
      <h2 style={{ marginBottom: 16 }}><NotificationOutlined /> {t('management.updates.title')}</h2>

      <Card style={{ maxWidth: 820, marginBottom: 16 }}>
        <Space direction="vertical" size={12} style={{ width: '100%' }}>
          <Space wrap>
            <Tag color="blue">{t('management.updates.latest')}</Tag>
            {currentRelease.important && <Tag color="red">{t('management.updates.important')}</Tag>}
            {(bundledVersion || installedVersion) && <Tag>{t('management.updates.version', { version: bundledVersion || installedVersion })}</Tag>}
            {installedVersion && bundledVersion && installedVersion !== bundledVersion && (
              <Tag color="orange">{t('management.updates.localVersion', { version: installedVersion })}</Tag>
            )}
          </Space>
          <Title level={3} style={{ margin: 0 }}>{currentRelease.title}</Title>
          <Paragraph type="secondary" style={{ marginBottom: 0 }}>{currentRelease.summary}</Paragraph>
          <ReleaseSections release={currentRelease} />
        </Space>
      </Card>

      <Card title={<Space><BellOutlined />{t('management.updates.preferences')}</Space>} style={{ maxWidth: 820, marginBottom: 16 }}>
        <Space direction="vertical">
          <Space>
            <Switch aria-label={t('management.updates.hide')} checked={hideImportant} onChange={changePreference} />
            <Text>{t('management.updates.hide')}</Text>
          </Space>
          <Text type="secondary">
            {t('management.updates.preferenceHint')}
          </Text>
        </Space>
      </Card>

      {!agentOnline && (
        <Alert
          style={{ maxWidth: 820, marginBottom: 16 }}
          type="info"
          showIcon
          message={t('management.updates.offline')}
        />
      )}

      <Card title={t('management.updates.history')} style={{ maxWidth: 820 }}>
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
