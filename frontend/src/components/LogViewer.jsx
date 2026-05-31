import React, { useEffect, useRef, useState } from 'react'
import { Spin } from 'antd'
import api from '../api/client'

export default function LogViewer({ runId, status }) {
  const [log, setLog] = useState('')
  const [loading, setLoading] = useState(true)
  const [streaming, setStreaming] = useState(false)
  const preRef = useRef(null)

  const isAlive = status === 'pending' || status === 'running'

  useEffect(() => {
    if (isAlive) {
      // SSE for live runs
      setStreaming(true)
      setLoading(false)  // Show empty state immediately for SSE
      const token = localStorage.getItem('token')
      const url = `/api/runs/${runId}/log/stream?token=${token}`
      const es = new EventSource(url)

      es.onmessage = (e) => {
        try {
          const data = JSON.parse(e.data)
          if (data.done) {
            es.close()
            setStreaming(false)
            // Final full fetch to ensure completeness
            api.get(`/api/runs/${runId}/log`).then(r => {
              setLog(r.data.log || '')
            })
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
        // Fallback: fetch full log once
        api.get(`/api/runs/${runId}/log`).then(r => {
          setLog(r.data.log || '')
          setLoading(false)
        })
      }

      return () => es.close()
    } else {
      // Static fetch for finished runs
      api.get(`/api/runs/${runId}/log`).then(r => {
        setLog(r.data.log || '')
      }).catch(() => {}).finally(() => setLoading(false))
    }
  }, [runId, isAlive])

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
