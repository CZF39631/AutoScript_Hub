// Compatibility adapter for known legacy authentication errors only.
// Never translate arbitrary user content or render structured server details.
const knownErrors = new Map([
  ['用户名或密码错误', 'shell.invalidCredentials'],
  ['账号已被禁用', 'shell.accountDisabled'],
  ['账号未获授权', 'shell.accountNotAuthorized'],
  ['外部认证响应格式错误', 'shell.invalidAuthResponse'],
  ['外部认证服务暂时不可用', 'shell.authUnavailable'],
  ['登录尝试过多，请稍后再试', 'shell.tooManyAttempts'],
])

export function describeLoginError(error) {
  const detail = error?.response?.data?.detail
  if (typeof detail === 'string' && detail) {
    const key = knownErrors.get(detail)
    return key ? { key } : { detail }
  }
  return error?.response
    ? { key: 'shell.loginFailed', values: { status: error.response.status } }
    : { key: 'shell.serverUnreachable' }
}

export function renderLoginError(error, t) {
  return error?.key ? t(error.key, error.values) : error?.detail || ''
}
