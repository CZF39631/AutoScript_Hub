export async function loadUpdateStatus(localApi) {
  const response = await localApi.get('/local/update')
  return response.data
}


export async function checkUpdate(localApi) {
  const response = await localApi.post('/local/update/check')
  return response.data
}


export async function installUpdate(localApi) {
  const response = await localApi.post('/local/update/install')
  return response.data
}
