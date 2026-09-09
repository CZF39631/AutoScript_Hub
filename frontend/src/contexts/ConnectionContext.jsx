import { createContext, useContext, useState, useEffect, useCallback } from 'react'
import axios from 'axios'
import { discoverAgent, localApi, startConnectionPolling } from './connectionRuntime'

/**
 * Connection state for offline-mode UI (design §5.x offline support).
 *
 * Two endpoints matter:
 *   - Backend (via proxy /api/*): authoritative when online
 *   - Local Agent (loopback fallback ports): used when backend unreachable
 *
 * Pages consult `useConnection()` to decide which source to call and whether to
 * show the offline banner.
 */
const ConnectionContext = createContext({
  online: true,
  agentOnline: false,
  agentId: null,
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
  const [agentId, setAgentId] = useState(null)
  const [pendingSync, setPendingSync] = useState(0)
  const [lastOnlineAt, setLastOnlineAt] = useState(null)

  const refresh = useCallback(async () => {
    // 1) Backend reachable? (goes through the local proxy → backend)
    try {
      await axios.get('/api/health', { timeout: 3000 })
      setOnline(true)
      setLastOnlineAt(Date.now())
    } catch {
      setOnline(false)
    }

    // 2) Discover the Local Agent across its loopback fallback ports.
    try {
      const r = await discoverAgent(localApi)
      setAgentOnline(true)
      setAgentId(r.data?.agent_id ?? null)
      setPendingSync(r.data?.pending_sync_count || 0)
    } catch {
      setAgentOnline(false)
      setAgentId(null)
    }
  }, [])

  useEffect(() => {
    return startConnectionPolling(refresh)
  }, [refresh])

  return (
    <ConnectionContext.Provider value={{ online, agentOnline, agentId, pendingSync, lastOnlineAt, refresh, localApi }}>
      {children}
    </ConnectionContext.Provider>
  )
}
