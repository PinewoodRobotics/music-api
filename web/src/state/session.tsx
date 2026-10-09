import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { api, ApiError, clearToken, onUnauthorized, type AppPlaylist, type Me } from '../lib/api'

type SessionState = { status: 'loading' } | { status: 'signedOut' } | { status: 'error'; message: string } | { status: 'ready'; me: Me }

type Session = {
  state: SessionState
  me: Me | null
  playlists: AppPlaylist[] | null
  playlistsError: unknown
  retryPlaylists: () => void
  refreshPlaylists: () => Promise<void>
  upsertPlaylist: (p: AppPlaylist) => void
  dropPlaylist: (id: string) => void
  signOut: () => Promise<void>
  retry: () => void
}

const SessionContext = createContext<Session | null>(null)

export function SessionProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<SessionState>({ status: 'loading' })
  const [playlists, setPlaylists] = useState<AppPlaylist[] | null>(null)
  const [attempt, setAttempt] = useState(0)

  useEffect(() => onUnauthorized(() => setState({ status: 'signedOut' })), [])

  useEffect(() => {
    let live = true
    api
      .me()
      .then((me) => live && setState({ status: 'ready', me }))
      .catch((err) => {
        if (!live) return
        if (err instanceof ApiError && err.status === 401) setState({ status: 'signedOut' })
        else setState({ status: 'error', message: err instanceof Error ? err.message : String(err) })
      })
    return () => {
      live = false
    }
  }, [attempt])

  const [playlistsError, setPlaylistsError] = useState<unknown>(null)
  const refreshPlaylists = useCallback(async () => {
    const list = await api.playlists()
    setPlaylists(list)
    setPlaylistsError(null)
  }, [])
  const retryPlaylists = useCallback(() => {
    setPlaylistsError(null)
    refreshPlaylists().catch(setPlaylistsError)
  }, [refreshPlaylists])

  const upsertPlaylist = useCallback(
    (p: AppPlaylist) =>
      setPlaylists((list) =>
        list?.some((x) => x.id === p.id) ? list.map((x) => (x.id === p.id ? p : x)) : [p, ...(list ?? [])],
      ),
    [],
  )
  const dropPlaylist = useCallback((id: string) => setPlaylists((list) => (list ?? []).filter((x) => x.id !== id)), [])

  const ready = state.status === 'ready'
  useEffect(() => {
    if (!ready) return
    refreshPlaylists().catch(setPlaylistsError)
    const onFocus = () => void refreshPlaylists().catch(() => {})
    window.addEventListener('focus', onFocus)
    return () => window.removeEventListener('focus', onFocus)
  }, [ready, refreshPlaylists])

  const value = useMemo<Session>(
    () => ({
      state,
      me: state.status === 'ready' ? state.me : null,
      playlists,
      playlistsError,
      retryPlaylists,
      refreshPlaylists,
      upsertPlaylist,
      dropPlaylist,
      signOut: async () => {
        await api.logout()
        clearToken()
        setPlaylists(null)
        setState({ status: 'signedOut' })
      },
      retry: () => {
        setState({ status: 'loading' })
        setAttempt((n) => n + 1)
      },
    }),
    [state, playlists, playlistsError, retryPlaylists, refreshPlaylists, upsertPlaylist, dropPlaylist],
  )

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>
}

export function useSession() {
  const ctx = useContext(SessionContext)
  if (!ctx) throw new Error('useSession outside SessionProvider')
  return ctx
}
