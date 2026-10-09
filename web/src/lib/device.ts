import { useSyncExternalStore } from 'react'

export const isTouch = () => window.matchMedia('(hover: none) and (pointer: coarse)').matches

export function useMediaQuery(query: string) {
  return useSyncExternalStore(
    (notify) => {
      const list = window.matchMedia(query)
      list.addEventListener('change', notify)
      return () => list.removeEventListener('change', notify)
    },
    () => window.matchMedia(query).matches,
  )
}
