import { useEffect, useState } from 'react'
import { Checkbox, List, Modal, Space, Tag, Typography } from 'antd'
import { RocketOutlined } from '@ant-design/icons'
import { useConnection } from '../contexts/ConnectionContext'
import { currentRelease } from '../data/releaseNotes'
import {
  dismissUpdateNotice,
  setImportantUpdatesHidden,
  shouldShowUpdateNotice,
} from '../utils/updateNotices'

const { Paragraph, Text, Title } = Typography
const bundledVersion = import.meta.env.VITE_AUTOSCRIPT_VERSION || ''

export default function ImportantUpdateNotice() {
  const { agentOnline, localApi } = useConnection()
  const [open, setOpen] = useState(false)
  const [version, setVersion] = useState('')
  const [hideFuture, setHideFuture] = useState(false)

  useEffect(() => {
    if (!agentOnline) return undefined
    let active = true
    localApi.get('/local/update')
      .then(({ data }) => {
        const installedVersion = data?.current_version || ''
        const matchesBundledRelease = !bundledVersion || bundledVersion === installedVersion
        if (active && matchesBundledRelease && shouldShowUpdateNotice({ release: currentRelease, version: installedVersion })) {
          setVersion(installedVersion)
          setOpen(true)
        }
      })
      .catch(() => {})
    return () => { active = false }
  }, [agentOnline, localApi])

  const close = () => {
    dismissUpdateNotice(currentRelease.id, version)
    if (hideFuture) setImportantUpdatesHidden(true)
    setOpen(false)
  }

  return (
    <Modal
      open={open}
      title={<Space><RocketOutlined />重要更新</Space>}
      okText="我知道了"
      cancelButtonProps={{ style: { display: 'none' } }}
      onOk={close}
      onCancel={close}
      destroyOnClose
    >
      <Space direction="vertical" size={12} style={{ width: '100%' }}>
        <div>
          <Tag color="blue">v{version}</Tag>
          <Title level={4} style={{ display: 'inline', margin: 0 }}>{currentRelease.title}</Title>
        </div>
        <Paragraph type="secondary" style={{ marginBottom: 0 }}>{currentRelease.summary}</Paragraph>
        {currentRelease.sections.map(section => (
          <div key={section.title}>
            <Text strong>{section.title}</Text>
            <List
              size="small"
              dataSource={section.items}
              renderItem={item => <List.Item style={{ paddingInline: 0 }}>• {item}</List.Item>}
            />
          </div>
        ))}
        <Checkbox checked={hideFuture} onChange={event => setHideFuture(event.target.checked)}>
          以后默认隐藏重要更新弹窗（仍可在“更新说明”中查看）
        </Checkbox>
      </Space>
    </Modal>
  )
}
