export async function loadUpdateStatus(localApi) {
  const response = await localApi.get('/local/update')
  return response.data
}


// 更新检查需要依次尝试 Gitee、GitHub 等外部源，不能沿用本地 API 的 10 秒超时。
// 安装还包含安装包下载，交由 Agent 侧的网络超时和状态机负责终止。
export async function checkUpdate(localApi) {
  const response = await localApi.post('/local/update/check', undefined, { timeout: 180000 })
  return response.data
}


export async function downloadAndInstallUpdate(localApi) {
  const response = await localApi.post('/local/update/install', undefined, { timeout: 0 })
  return response.data
}
