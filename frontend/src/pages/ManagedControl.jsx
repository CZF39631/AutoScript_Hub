import { Tabs } from 'antd'
import { CalendarOutlined, DesktopOutlined } from '@ant-design/icons'
import { useSearchParams } from 'react-router-dom'
import ManagedAgents from './ManagedAgents'
import ManagedSchedules from './ManagedSchedules'

const VALID_TABS = new Set(['devices', 'schedules'])

export default function ManagedControl() {
  const [searchParams, setSearchParams] = useSearchParams()
  const requestedTab = searchParams.get('tab')
  const activeTab = VALID_TABS.has(requestedTab) ? requestedTab : 'devices'

  const changeTab = tab => {
    setSearchParams(tab === 'devices' ? {} : { tab }, { replace: true })
  }

  return (
    <div className="managed-control-page">
      <div className="page-heading managed-control-heading">
        <div>
          <h2>设备托管</h2>
          <p>集中管理被控设备、临时任务和固定间隔定时任务</p>
        </div>
      </div>

      <Tabs
        className="managed-control-tabs"
        activeKey={activeTab}
        onChange={changeTab}
        items={[
          {
            key: 'devices',
            label: <span><DesktopOutlined />设备与临时任务</span>,
            children: activeTab === 'devices' ? <ManagedAgents embedded /> : null,
          },
          {
            key: 'schedules',
            label: <span><CalendarOutlined />定时任务</span>,
            children: activeTab === 'schedules' ? <ManagedSchedules embedded /> : null,
          },
        ]}
      />
    </div>
  )
}
