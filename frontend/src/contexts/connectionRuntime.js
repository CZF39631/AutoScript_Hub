import axios from 'axios'


export const AGENT_URL = 'http://127.0.0.1:18080'
const agentToken = typeof window !== 'undefined' ? window._AGENT_API_TOKEN : ''
export const localApi = axios.create({
  baseURL: AGENT_URL,
  timeout: 10000,
  headers: agentToken ? { Authorization: `Bearer ${agentToken}` } : {},
})


export function startConnectionPolling(
  refresh,
  { setIntervalFn = setInterval, clearIntervalFn = clearInterval } = {},
) {
  refresh()
  const interval = setIntervalFn(refresh, 5000)
  return () => clearIntervalFn(interval)
}
