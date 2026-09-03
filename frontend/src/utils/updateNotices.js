export const HIDE_IMPORTANT_UPDATES_KEY = 'autoscript-hub:updates:hide-important'
export const UPDATE_NOTICE_CHANGED_EVENT = 'autoscript-hub:update-notice-changed'

const dismissedKey = (releaseId, version) => (
  `autoscript-hub:updates:dismissed:${releaseId}:${version}`
)

export function importantUpdatesHidden(storage = globalThis.localStorage) {
  try {
    return storage?.getItem(HIDE_IMPORTANT_UPDATES_KEY) === 'true'
  } catch {
    return false
  }
}

export function setImportantUpdatesHidden(hidden, storage = globalThis.localStorage) {
  try {
    storage?.setItem(HIDE_IMPORTANT_UPDATES_KEY, hidden ? 'true' : 'false')
    globalThis.window?.dispatchEvent(new Event(UPDATE_NOTICE_CHANGED_EVENT))
    return true
  } catch {
    return false
  }
}

export function dismissUpdateNotice(releaseId, version, storage = globalThis.localStorage) {
  if (!releaseId || !version) return false
  try {
    storage?.setItem(dismissedKey(releaseId, version), 'true')
    return true
  } catch {
    return false
  }
}

export function shouldShowUpdateNotice({ release, version, storage = globalThis.localStorage }) {
  if (!release?.important || !release.id || !version || importantUpdatesHidden(storage)) return false
  try {
    return storage?.getItem(dismissedKey(release.id, version)) !== 'true'
  } catch {
    return true
  }
}
