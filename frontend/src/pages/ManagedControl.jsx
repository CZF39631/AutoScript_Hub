import { useEffect } from 'react'
import { useLocation } from 'react-router-dom'
import ManagedAgents from './ManagedAgents'
import ManagedSchedules from './ManagedSchedules'

export default function ManagedControl() {
  const location = useLocation()

  useEffect(() => {
    if (location.hash === '#schedules') {
      requestAnimationFrame(() => document.getElementById('managed-schedules')?.scrollIntoView({ behavior: 'smooth' }))
    }
  }, [location.hash])

  return (
    <div className="managed-control-page">
      <div className="page-heading managed-control-heading">
        <div>
          <h2>设备托管</h2>
          <p>在同一页面查看设备状态，发布临时任务并维护固定间隔定时任务</p>
        </div>
      </div>

      <ManagedAgents embedded />

      <section id="managed-schedules" className="managed-control-schedules" aria-label="定时任务">
        <ManagedSchedules embedded />
      </section>
    </div>
  )
}
