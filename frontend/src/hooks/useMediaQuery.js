import { useEffect, useState } from 'react'

export default function useMediaQuery(query) {
  const getMatches = () => typeof window !== 'undefined' && window.matchMedia(query).matches
  const [matches, setMatches] = useState(getMatches)

  useEffect(() => {
    const media = window.matchMedia(query)
    const update = () => setMatches(media.matches)
    update()
    media.addEventListener('change', update)
    return () => media.removeEventListener('change', update)
  }, [query])

  return matches
}
