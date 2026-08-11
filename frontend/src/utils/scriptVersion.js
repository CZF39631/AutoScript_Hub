export function formatScriptVersion(semanticVersion, internalVersion) {
  const value = typeof semanticVersion === 'string' ? semanticVersion.trim() : ''
  if (value) return `V${value.replace(/^v/i, '')}`
  return internalVersion == null ? '-' : `v${internalVersion}`
}
