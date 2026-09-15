export const LANGUAGE_STORAGE_KEY = 'autoscript.ui.language'
export const DEFAULT_LANGUAGE = 'zh-CN'
export const SUPPORTED_LANGUAGES = ['zh-CN', 'en-US']

export function normalizeLanguage(value) {
  if (typeof value !== 'string') return DEFAULT_LANGUAGE
  const language = value.toLowerCase()
  return language === 'en' || language.startsWith('en-') ? 'en-US' : DEFAULT_LANGUAGE
}

function browserStorage() {
  try {
    return typeof window === 'undefined' ? undefined : window.localStorage
  } catch {
    return undefined
  }
}

export function readLanguage(storage = browserStorage()) {
  try {
    return normalizeLanguage(storage?.getItem(LANGUAGE_STORAGE_KEY))
  } catch {
    return DEFAULT_LANGUAGE
  }
}

export function saveLanguage(language, storage = browserStorage()) {
  const normalized = normalizeLanguage(language)
  try {
    storage?.setItem(LANGUAGE_STORAGE_KEY, normalized)
  } catch {
    // A blocked/full storage must not prevent switching the current interface.
  }
  return normalized
}
