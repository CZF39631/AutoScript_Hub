import axios from 'axios'


export function agentUrls(flavor = 'stable') {
  if (!['stable', 'preview'].includes(flavor)) throw new Error('无效的客户端安装身份')
  const base = flavor === 'preview' ? 18180 : 18080
  return [
    `http://127.0.0.1:${base}`,
    ...Array.from({ length: 9 }, (_, index) => `http://127.0.0.1:${base + 11 + index}`),
  ]
}
export const AGENT_URLS = agentUrls(
  typeof window !== 'undefined' ? window._INSTALL_FLAVOR || 'stable' : 'stable',
)
const agentToken = typeof window !== 'undefined' ? window._AGENT_API_TOKEN : ''
export const localApi = axios.create({
  baseURL: AGENT_URLS[0],
  timeout: 10000,
  headers: agentToken ? { Authorization: `Bearer ${agentToken}` } : {},
})

export async function discoverAgent(api = localApi) {
  let lastError
  for (const baseURL of AGENT_URLS) {
    try {
      const response = await api.get(`${baseURL}/local/connection`, { timeout: 1000 })
      api.defaults.baseURL = baseURL
      return response
    } catch (error) {
      lastError = error
    }
  }
  throw lastError || new Error('本地 Agent 不可用')
}


export function startConnectionPolling(
  refresh,
  { setIntervalFn = setInterval, clearIntervalFn = clearInterval } = {},
) {
  refresh()
  const interval = setIntervalFn(refresh, 5000)
  return () => clearIntervalFn(interval)
}
