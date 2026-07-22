import { useEffect, useRef, useState } from 'react'
import { Spin } from 'antd'
import api from '../api/client'
import { loadRunLog } from '../api/offlineData'

export default function LogViewer({ runId, status, onComplete, localOnly = false, localApi = null }) {
  const [log, setLog] = useState('')
  const [loading, setLoading] = useState(true)
  const [streaming, setStreaming] = useState(false)
  const preRef = useRef(null)

  const isAlive = status === 'pending' || status === 'running'

  useEffect(() => {
    if (localOnly) {
      let active = true
      const refreshLocal = () => loadRunLog({ id: runId, localOnly: true, api, localApi })
        .then(data => { if (active) setLog(data.log || '') })
        .finally(() => { if (active) setLoading(false) })
      refreshLocal()
      const interval = isAlive ? setInterval(refreshLocal, 1000) : null
      return () => {
        active = false
        if (interval) clearInterval(interval)
      }
    }
    if (isAlive) {
      // SSE for live runs — connect directly to backend (bypass local proxy)
      setStreaming(true)
      setLoading(false)
      const token = localStorage.getItem('token')
      const backendUrl = window._BACKEND_URL || 'http://127.0.0.1:8000'
      const url = `${backendUrl}/api/runs/${runId}/log/stream?token=${token}`
      const es = new EventSource(url)

      const finish = () => {
        // Final full fetch to ensure completeness, then notify parent so it can refresh status.
        api.get(`/api/runs/${runId}/log`).then(r => {
          setLog(r.data.log || '')
        }).finally(() => {
          if (onComplete) onComplete()
        })
      }

      es.onmessage = (e) => {
        try {
          const data = JSON.parse(e.data)
          if (data.done) {
            es.close()
            setStreaming(false)
            finish()
            return
          }
          if (data.log) {
            setLog(prev => prev + data.log)
            setLoading(false)
          }
        } catch { /* ignore parse errors */ }
      }

      es.onerror = () => {
        es.close()
        setStreaming(false)
        finish()
      }

      return () => es.close()
    } else {
      // Static fetch for finished runs
      api.get(`/api/runs/${runId}/log`).then(r => {
        setLog(r.data.log || '')
      }).catch(() => {}).finally(() => setLoading(false))
    }
  }, [runId, isAlive, onComplete, localOnly, localApi])

  useEffect(() => {
    if (preRef.current) {
      preRef.current.scrollTop = preRef.current.scrollHeight
    }
  }, [log])

  if (loading) return <Spin />

  return (
    <div>
      <h3>执行日志{streaming ? ' (实时推送中...)' : ''}</h3>
      <pre ref={preRef} style={{
        background: '#1e1e1e', color: '#d4d4d4', padding: 16,
        borderRadius: 4, maxHeight: 400, overflow: 'auto',
        fontSize: 13, lineHeight: 1.5, whiteSpace: 'pre-wrap',
      }}>
        {log || '(暂无日志)'}
      </pre>
    </div>
  )
}
