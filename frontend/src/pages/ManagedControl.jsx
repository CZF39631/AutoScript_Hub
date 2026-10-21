import ManagedAgents from './ManagedAgents'

export default function ManagedControl() {
  return (
    <div className="managed-control-page">
      <div className="page-heading managed-control-heading">
        <div>
          <h2>设备托管</h2>
          <p>在同一页面查看设备状态，发布临时任务并维护固定间隔定时任务</p>
        </div>
      </div>

      <ManagedAgents embedded />
    </div>
  )
}
