import { useEffect, useState } from 'react'

function pageIsFocused() {
  if (typeof document === 'undefined') return true
  const visible = document.visibilityState !== 'hidden'
  const focused = typeof document.hasFocus !== 'function' || document.hasFocus()
  return visible && focused
}

export default function usePageFocused() {
  const [focused, setFocused] = useState(pageIsFocused)

  useEffect(() => {
    const update = () => setFocused(pageIsFocused())
    document.addEventListener('visibilitychange', update)
    window.addEventListener('focus', update)
    window.addEventListener('blur', update)
    return () => {
      document.removeEventListener('visibilitychange', update)
      window.removeEventListener('focus', update)
      window.removeEventListener('blur', update)
    }
  }, [])

  return focused
}
