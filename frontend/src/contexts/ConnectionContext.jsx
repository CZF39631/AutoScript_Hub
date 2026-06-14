import React, { createContext, useContext, useState, useEffect, useCallback } from 'react'
import axios from 'axios'

/**
 * Connection state for offline-mode UI (design §5.x offline support).
 *
 * Two endpoints matter:
 *   - Backend (via proxy /api/*): authoritative when online
 *   - Local Agent (http://127.0.0.1:18080/local/*): used when backend unreachable
 *
 * Pages consult `useConnection()` to decide which source to call and whether to
 * show the offline banner.
 */
const AGENT_URL = 'http://127.0.0.1:18080'

const ConnectionContext = createContext({
  online: true,
  agentOnline: false,
  pendingSync: 0,
  lastOnlineAt: null,
  refresh: () => {},
  localApi: null,
})

export function useConnection() {
  return useContext(ConnectionContext)
}

export function ConnectionProvider({ children }) {
  const [online, setOnline] = useState(true)
  const [agentOnline, setAgentOnline] = useState(false)
  const [pendingSync, setPendingSync] = useState(0)
  const [lastOnlineAt, setLastOnlineAt] = useState(null)

  // Dedicated axios instance for the local Agent — bypasses the proxy entirely.
  const localApi = axios.create({ baseURL: AGENT_URL, timeout: 10000 })

  const refresh = useCallback(async () => {
    // 1) Backend reachable? (goes through the local proxy → backend)
    let backendOk = false
    try {
      await axios.get('/api/health', { timeout: 3000 })
      backendOk = true
    } catch {
      backendOk = false
    }
    setOnline(backendOk)
    if (backendOk) setLastOnlineAt(Date.now())

    // 2) Local Agent reachable? (direct hit on 127.0.0.1:18080)
    let agentOk = false
    try {
      const r = await localApi.get('/local/connection')
      agentOk = true
      setPendingSync(r.data?.pending_sync_count || 0)
    } catch {
      agentOk = false
    }
    setAgentOnline(agentOk)
  }, [localApi])

  useEffect(() => {
    refresh()
    // Poll every 30s so the banner updates on its own.
    const interval = setInterval(refresh, 30000)
    return () => clearInterval(interval)
  }, [refresh])

  return (
    <ConnectionContext.Provider value={{ online, agentOnline, pendingSync, lastOnlineAt, refresh, localApi }}>
      {children}
    </ConnectionContext.Provider>
  )
}
