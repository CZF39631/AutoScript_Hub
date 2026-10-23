export async function loadManagedThumbnail(http, agentId, { signal, urlApi = URL } = {}) {
  const response = await http.get(`/api/admin/managed-agents/${agentId}/thumbnail`, {
    responseType: 'blob',
    signal,
  })
  const url = urlApi.createObjectURL(response.data)
  let released = false
  return {
    url,
    release() {
      if (released) return
      released = true
      urlApi.revokeObjectURL(url)
    },
  }
}
