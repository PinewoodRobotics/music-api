import { storage } from './storage'

export type ArtistRef = { uri: string; name: string }

export type Track = {
  uri: string
  id: string
  type: 'track' | 'episode'
  name: string
  artists?: ArtistRef[]
  show?: { uri: string; name: string }
  album?: { uri: string; name: string } | null
  duration_ms: number
  explicit?: boolean
  artwork: string | null
  added_at?: string
}

export type Album = {
  uri: string
  id: string
  type: 'album'
  name: string
  artists: ArtistRef[]
  album_type: string
  release_date: string
  total_tracks: number
  artwork: string | null
  label?: string
  tracks?: Page<Track>
}

export type Artist = {
  uri: string
  id: string
  type: 'artist'
  name: string
  genres: string[] | null
  artwork: string | null
}

export type SpotifyPlaylist = {
  uri: string
  id: string
  type: 'playlist'
  name: string
  owner: string
  description: string
  total: number
  artwork: string | null
}

export type Page<T> = { items: T[]; total: number; offset: number; limit: number; next: boolean }

export type PlaybackState = 'playing' | 'paused' | 'idle' | 'buffering' | (string & {})
export type RepeatMode = 'off' | 'context' | 'track'

export type Status = {
  backend: string
  state: PlaybackState
  active: boolean
  device: { name: string; type: string; active: boolean } | null
  position_ms: number
  duration_ms: number | null
  volume: number | null
  shuffle: boolean | null
  repeat: RepeatMode | null
  track: Track | null
  context: { uri: string; type: string; name?: string; artwork?: string | null } | null
  actions: string[]
  credit?: Credit | null
}

export type Person = { id?: string; name: string; avatar: string | null }

export type Credit = { by: Person; how: 'queued' | 'started' }

export type QueueEntry = {
  uid: string | null
  source: 'context' | 'queue' | 'autoplay' | null
  item: Track | null
  added_by?: Person | null
}

export type Queue = { upcoming: QueueEntry[]; previous?: QueueEntry[] }

export type Lyrics = {
  instrumental: boolean
  synced: { time_ms: number; text: string }[]
  plain: string | null
  track: { uri: string; name: string }
  position_ms?: number
  line?: number
}

export type SearchResults = {
  tracks?: Page<Track>
  albums?: Page<Album>
  artists?: Page<Artist>
  playlists?: Page<SpotifyPlaylist>
}

export type Me = {
  id: string
  name: string
  avatar: string | null
  admin: boolean
  kind: 'slack' | 'token'
}

export type AppPlaylist = {
  id: string
  uri: string
  name: string
  description: string
  artwork: string | null
  total: number
  created_by: Person | null
  source_url: string | null
  created: string | null
  can_edit: boolean
}

export type ImportResult = {
  playlist: AppPlaylist
  imported: number
  total: number | null
  truncated: boolean
  unmatched?: { name: string; artists: string[] }[]
}

export type PersonalToken = { token: string; created: number; docs: string }

export type ResolvedTrack = {
  name: string
  artists: string[]
  album: string | null
  duration_ms: number
  artwork: string | null
  uri: string | null
}

export type Resolved = {
  source: 'spotify' | 'apple'
  kind: 'track' | 'album' | 'playlist'
  name: string
  subtitle: string | null
  artwork: string | null
  url: string
  spotify_uri: string | null
  tracks: ResolvedTrack[]
  total: number
  matched: number
  truncated: boolean
}

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

const TOKEN_KEY = 'token'

function readToken(): string | null {
  const url = new URL(location.href)
  const fromUrl = url.searchParams.get('token')
  if (!fromUrl) return storage.get(TOKEN_KEY)
  storage.set(TOKEN_KEY, fromUrl)
  url.searchParams.delete('token')
  history.replaceState(history.state, '', url.pathname + url.search + url.hash)
  return fromUrl
}

let token = readToken()

export function clearToken() {
  token = null
  storage.set(TOKEN_KEY, null)
}

const unauthorizedListeners = new Set<() => void>()

export function onUnauthorized(listener: () => void) {
  unauthorizedListeners.add(listener)
  return () => void unauthorizedListeners.delete(listener)
}

const RETRYABLE = new Set([502, 503, 504])
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))

async function request<T>(method: string, path: string, body?: unknown, retried = false): Promise<T> {
  const headers: Record<string, string> = {}
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  if (token) headers.Authorization = `Bearer ${token}`
  const retry = method === 'GET' && !retried
  let res: Response
  try {
    res = await fetch(path, {
      method,
      headers,
      credentials: 'same-origin',
      body: body === undefined ? undefined : JSON.stringify(body),
    })
  } catch {
    if (retry) return sleep(1000).then(() => request<T>(method, path, body, true))
    throw new ApiError(0, "Can't reach the music server. Check your connection.")
  }
  if (retry && RETRYABLE.has(res.status)) return sleep(1000).then(() => request<T>(method, path, body, true))
  const data = await res.json().catch(() => null)
  if (res.status === 401) unauthorizedListeners.forEach((l) => l())
  if (!res.ok) throw new ApiError(res.status, data?.error ?? friendlyStatus(res.status))
  return data?.result as T
}

function friendlyStatus(status: number) {
  return RETRYABLE.has(status) ? 'The music server is restarting. Try again in a moment.' : `Request failed (${status})`
}

const get = <T>(path: string) => request<T>('GET', path)
const post = <T>(path: string, body: unknown = {}) => request<T>('POST', path, body)
const qs = (params: Record<string, string | number>) => new URLSearchParams(Object.entries(params).map(([k, v]) => [k, String(v)])).toString()

export function eventsUrl() {
  return token ? `/api/events?${qs({ token })}` : '/api/events'
}

export const api = {
  me: () => get<Me>('/api/app/me'),
  personalToken: () => get<PersonalToken>('/api/app/token'),
  regenerateToken: () => post<PersonalToken>('/api/app/token/regenerate'),
  logout: () => post<unknown>('/auth/slack/logout').catch(() => undefined),

  status: () => get<Status>('/api/status'),
  queue: (limit = 50) => get<Queue>(`/api/queue?${qs({ limit })}`),
  lyrics: () => get<Lyrics>('/api/lyrics'),

  play: (body: { uri?: string; uris?: string[]; context?: string; offset?: number | string } = {}) => post<Status>('/api/play', body),
  pause: () => post<Status>('/api/pause'),
  next: () => post<Status>('/api/next'),
  previous: () => post<Status>('/api/previous'),
  seek: (position_ms: number) => post<Status>('/api/seek', { position_ms: Math.max(0, Math.round(position_ms)) }),
  volume: (volume: number) => post<Status>('/api/volume', { volume: Math.round(volume) }),
  shuffle: (enabled: boolean) => post<Status>('/api/shuffle', { enabled }),
  repeat: (mode: RepeatMode) => post<Status>('/api/repeat', { mode }),
  addToQueue: (uris: string[]) => post<{ added: string[] }>('/api/queue', { uris }),

  resolve: (url: string) => post<Resolved>('/api/resolve', { url }),
  search: (q: string) => get<SearchResults>(`/api/search?${qs({ q, type: 'track,album,artist,playlist', limit: 10 })}`),
  album: (id: string) => get<Album>(`/api/albums/${id}`),
  albumTracks: (id: string, offset: number) => get<Page<Track>>(`/api/albums/${id}/tracks?${qs({ limit: 50, offset })}`),
  artist: (id: string) => get<Artist>(`/api/artists/${id}`),
  artistAlbums: (id: string, offset = 0) =>
    get<Page<Album>>(`/api/artists/${id}/albums?${qs({ include_groups: 'album,single', limit: 10, offset })}`),

  playlists: () => get<AppPlaylist[]>('/api/app/playlists'),
  playlist: (id: string) => get<AppPlaylist>(`/api/app/playlists/${id}`),
  createPlaylist: (body: { name: string; description?: string }) => post<AppPlaylist>('/api/app/playlists', body),
  importPlaylist: (url: string) => post<ImportResult>('/api/app/playlists/import', { url }),
  updatePlaylist: (id: string, body: { name?: string; description?: string }) =>
    request<AppPlaylist>('PATCH', `/api/app/playlists/${id}`, body),
  deletePlaylist: (id: string) => request<unknown>('DELETE', `/api/app/playlists/${id}`),
  playlistItems: (id: string, offset: number) => get<Page<Track>>(`/api/playlists/${id}/items?${qs({ limit: 50, offset })}`),
  addToPlaylist: (id: string, uris: string[]) => post<unknown>(`/api/playlists/${id}/items`, { uris }),
  removeFromPlaylist: (id: string, uris: string[]) => request<unknown>('DELETE', `/api/playlists/${id}/items`, { uris }),
  playPlaylist: (id: string, body: { offset?: number | string; shuffle?: boolean } = {}) =>
    post<Status>(`/api/playlists/${id}/play`, body),
}

export function errorMessage(err: unknown) {
  return err instanceof Error ? err.message : 'Something went wrong.'
}
