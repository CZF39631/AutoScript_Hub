// Detection reports installed paths only, not launchability or script compatibility.
const pending = new WeakMap()

export function normalizeBrowsers(data) {
  if (!Array.isArray(data)) throw new Error('浏览器检测返回格式不正确')
  const seen = new Set()
  return data.filter(browser => {
    if (!browser || typeof browser.name !== 'string' || !browser.name.trim()
      || typeof browser.path !== 'string' || !browser.path.trim()) return false
    // Keep the exact path for saving; deduplicate Windows paths case-insensitively.
    const key = browser.path.replaceAll('/', '\\').toLowerCase()
    if (seen.has(key)) return false
    seen.add(key)
    return true
  }).map(({ name, path }) => ({ name, path }))
}

export function loadLocalBrowsers(localApi) {
  if (pending.has(localApi)) return pending.get(localApi)
  const request = Promise.resolve()
    .then(() => localApi.get('/detect-browsers'))
    .then(response => normalizeBrowsers(response.data))
    .finally(() => pending.delete(localApi))
  pending.set(localApi, request)
  return request
}

export function browserOptions(browsers, value) {
  const options = browsers.map(({ name, path }) => ({ value: path, label: name, path }))
  if (value && !options.some(option => option.value === value)) {
    options.unshift({ value, label: '当前路径（未在检测列表中）', path: value })
  }
  return options
}
