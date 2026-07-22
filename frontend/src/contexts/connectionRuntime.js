import axios from 'axios'


export const AGENT_URL = 'http://127.0.0.1:18080'
export const localApi = axios.create({ baseURL: AGENT_URL, timeout: 10000 })


export function startConnectionPolling(
  refresh,
  { setIntervalFn = setInterval, clearIntervalFn = clearInterval } = {},
) {
  refresh()
  const interval = setIntervalFn(refresh, 30000)
  return () => clearIntervalFn(interval)
}
