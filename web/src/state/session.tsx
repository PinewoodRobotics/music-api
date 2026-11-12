import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { api, ApiError, banOf, clearToken, onBanned, onUnauthorized, type AppPlaylist, type BanInfo, type LibraryAlbum, type LibraryItem, type Me } from '../lib/api'

type SessionState = { status: 'loading' } | { status: 'signedOut' } | { status: 'error'; message: string } | { status: 'banned'; ban: BanInfo } | { status: 'ready'; me: Me }

type Session = {
  state: SessionState
  me: Me | null
  library: LibraryItem[] | null
  libraryAvailable: boolean
  playlists: AppPlaylist[] | null
  playlistsError: unknown
  retryPlaylists: () => void
  refreshPlaylists: () => Promise<void>
  upsertPlaylist: (p: AppPlaylist) => void
  dropPlaylist: (id: string) => void
  upsertAlbum: (a: LibraryAlbum) => void
  dropAlbum: (id: string) => void
  signOut: () => Promise<void>
  retry: () => void
}

const SessionContext = createContext<Session | null>(null)

const asPlaylistItem = (p: AppPlaylist): LibraryItem => ({ ...p, kind: 'playlist' })

function upsertItem(list: LibraryItem[] | null, item: LibraryItem) {
  const same = (x: LibraryItem) => x.kind === item.kind && x.id === item.id
  return list?.some(same) ? list.map((x) => (same(x) ? item : x)) : [item, ...(list ?? [])]
}

async function loadLibrary(): Promise<{ items: LibraryItem[]; available: boolean }> {
  try {
    const { items } = await api.library('all', 'recent')
    return { items, available: true }
  } catch (err) {
    if (!(err instanceof ApiError) || err.status !== 404) throw err
    return { items: (await api.playlists()).map(asPlaylistItem), available: false }
  }
}

export function SessionProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<SessionState>({ status: 'loading' })
  const [library, setLibrary] = useState<LibraryItem[] | null>(null)
  const [libraryAvailable, setLibraryAvailable] = useState(true)
  const [attempt, setAttempt] = useState(0)

  useEffect(() => onUnauthorized(() => setState({ status: 'signedOut' })), [])
  useEffect(() => onBanned((ban) => setState({ status: 'banned', ban })), [])

  useEffect(() => {
    let live = true
    api
      .me()
      .then((me) => live && setState({ status: 'ready', me }))
      .catch((err) => {
        if (!live) return
        const ban = banOf(err)
        if (ban) setState({ status: 'banned', ban })
        else if (err instanceof ApiError && err.status === 401) setState({ status: 'signedOut' })
        else setState({ status: 'error', message: err instanceof Error ? err.message : String(err) })
      })
    return () => {
      live = false
    }
  }, [attempt])

  const [playlistsError, setPlaylistsError] = useState<unknown>(null)
  const refreshPlaylists = useCallback(async () => {
    const result = await loadLibrary()
    setLibrary(result.items)
    setLibraryAvailable(result.available)
    setPlaylistsError(null)
  }, [])
  const retryPlaylists = useCallback(() => {
    setPlaylistsError(null)
    refreshPlaylists().catch(setPlaylistsError)
  }, [refreshPlaylists])

  const upsertPlaylist = useCallback((p: AppPlaylist) => setLibrary((list) => upsertItem(list, asPlaylistItem(p))), [])
  const dropPlaylist = useCallback(
    (id: string) => setLibrary((list) => (list ?? []).filter((x) => !(x.kind === 'playlist' && x.id === id))),
    [],
  )
  const upsertAlbum = useCallback((a: LibraryAlbum) => setLibrary((list) => upsertItem(list, { ...a, kind: 'album' })), [])
  const dropAlbum = useCallback(
    (id: string) => setLibrary((list) => (list ?? []).filter((x) => !(x.kind === 'album' && x.id === id))),
    [],
  )

  const ready = state.status === 'ready'
  useEffect(() => {
    if (!ready) return
    refreshPlaylists().catch(setPlaylistsError)
    const onFocus = () => void refreshPlaylists().catch(() => {})
    window.addEventListener('focus', onFocus)
    return () => window.removeEventListener('focus', onFocus)
  }, [ready, refreshPlaylists])

  const playlists = useMemo(
    () => (library ? library.filter((x): x is LibraryItem & { kind: 'playlist' } => x.kind === 'playlist') : null),
    [library],
  )

  const value = useMemo<Session>(
    () => ({
      state,
      me: state.status === 'ready' ? state.me : null,
      library,
      libraryAvailable,
      playlists,
      playlistsError,
      retryPlaylists,
      refreshPlaylists,
      upsertPlaylist,
      dropPlaylist,
      upsertAlbum,
      dropAlbum,
      signOut: async () => {
        await api.logout()
        clearToken()
        setLibrary(null)
        setState({ status: 'signedOut' })
      },
      retry: () => {
        setState({ status: 'loading' })
        setAttempt((n) => n + 1)
      },
    }),
    [state, library, libraryAvailable, playlists, playlistsError, retryPlaylists, refreshPlaylists, upsertPlaylist, dropPlaylist, upsertAlbum, dropAlbum],
  )

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>
}

export function useSession() {
  const ctx = useContext(SessionContext)
  if (!ctx) throw new Error('useSession outside SessionProvider')
  return ctx
}
