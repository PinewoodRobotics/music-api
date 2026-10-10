import { useSyncExternalStore } from 'react'

const listeners = new Set<() => void>()
const notify = () => listeners.forEach((l) => l())

window.addEventListener('popstate', notify)

function subscribe(listener: () => void) {
  listeners.add(listener)
  return () => void listeners.delete(listener)
}

const snapshot = () => location.pathname + location.search

export function navigate(to: string, { replace = false } = {}) {
  if (to === snapshot()) return
  if (replace) history.replaceState(null, '', to)
  else history.pushState(null, '', to)
  if (!replace) window.scrollTo(0, 0)
  notify()
}

export function useLocation() {
  const href = useSyncExternalStore(subscribe, snapshot)
  const url = new URL(href, location.origin)
  return { path: url.pathname, query: url.searchParams }
}

export type Route =
  | { name: 'library' }
  | { name: 'search' }
  | { name: 'open'; url: string }
  | { name: 'playlist'; id: string }
  | { name: 'album'; id: string }
  | { name: 'artist'; id: string }
  | { name: 'notFound' }

export function matchRoute(path: string, query: URLSearchParams): Route {
  const parts = path.split('/').filter(Boolean)
  if (parts.length === 0 || (parts.length === 1 && parts[0] === 'library')) return { name: 'library' }
  if (parts.length === 1 && parts[0] === 'search') return { name: 'search' }
  if (parts.length === 1 && parts[0] === 'open') return { name: 'open', url: query.get('url') ?? '' }
  if (parts.length === 2 && (parts[0] === 'playlist' || parts[0] === 'album' || parts[0] === 'artist'))
    return { name: parts[0], id: parts[1] }
  return { name: 'notFound' }
}
