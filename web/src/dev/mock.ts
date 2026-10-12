import type { ActivityEntry, AppPlaylist, LibraryAlbum, Lyrics, QuietHours, Queue, Status, Track } from '../lib/api'
import fixtures from './fixtures.json'

type Mode = 'full' | 'signedout' | 'signedout-slack' | 'signedout-google' | 'writes' | 'down'
type Call = { method: string; path: string; body: unknown; origin: string | null }

declare global {
  interface Window {
    __mockCalls: Call[]
    __mockActivity: (action: string, detail?: Record<string, unknown>, who?: string, origin?: string) => number
    __mockActivityUpdate: (id: number, patch: Record<string, unknown>) => void
    __mockActivitySilent: (action: string, detail?: Record<string, unknown>, who?: string, agoMs?: number) => number
    __mockReconnect: () => void
    __mockLab: {
      next: () => void
      pause: () => void
      resume: () => void
      seek: (ms: number) => void
      airplay: (on: boolean, resume?: boolean) => void
      quiet: (phase: QuietHours['phase'], idle?: boolean) => void
    }
  }
}

const tracks = fixtures.tracks as Track[]
const lyrics = fixtures.lyrics as unknown as Lyrics
const adam = { id: 'U01', name: 'Adam Xu', avatar: null }
const maya = { id: 'U02', name: 'Maya', avatar: null }
const howard = { id: 'U03', name: 'Howard Kent', avatar: null }
const people: Record<string, { id: string; name: string; avatar: null }> = { maya, howard, me: { id: 'U01', name: 'Adam Xu', avatar: null } }

const activityBus = new EventTarget()
const openSources = new Set<EventTarget>()
let activityId = 0
const activityLog: ActivityEntry[] = []

function logActivity(by: ActivityEntry['by'], action: string, detail: Record<string, unknown>, origin = 'web', at = Date.now()) {
  const entry: ActivityEntry = { id: ++activityId, at, by, action, detail, origin }
  activityLog.push(entry)
  return entry
}

function seedActivity() {
  const ago = (min: number) => Date.now() - min * 60_000
  const seed: [ActivityEntry['by'], string, Record<string, unknown>, string, number][] = [
    [maya, 'playlist_import', { id: 'p2', name: 'Competition Hype', imported: 88, source: 'spotify' }, 'web', ago(22 * 60)],
    [{ id: 'U01', name: 'Adam Xu', avatar: null }, 'playlist_create', { id: 'p1', name: 'Build Night' }, 'web', ago(20 * 60)],
    [howard, 'queue_add', { uris: ['x'], count: 3 }, 'slack', ago(5 * 60)],
    [maya, 'shuffle', { enabled: true }, 'web', ago(3 * 60 + 10)],
    [howard, 'volume', { volume: 45 }, 'media-session', ago(95)],
    [{ id: 'U01', name: 'Adam Xu', avatar: null }, 'playlist_play', { id: 'p1', name: 'Build Night' }, 'web', ago(40)],
    [maya, 'next', { from: 'Dreams' }, 'web', ago(6)],
    [howard, 'queue_add', { uris: ['y'], count: 1, names: ['Kiss from a Rose'] }, 'slack', ago(2)],
  ]
  for (const [by, action, detail, origin, at] of seed) logActivity(by, action, detail, origin, at)
}
seedActivity()

const playlists: AppPlaylist[] = [
  {
    id: 'p1',
    uri: 'spotify:playlist:p1',
    name: 'Build Night',
    description: 'Loud enough to hear over the drill press.',
    artwork: tracks[2].artwork,
    total: 8,
    created_by: adam,
    source_url: null,
    created: '2026-10-08T19:00:00Z',
    can_edit: true,
  },
  {
    id: 'p2',
    uri: 'spotify:playlist:p2',
    name: 'Competition Hype',
    description: '',
    artwork: tracks[7].artwork,
    total: 6,
    created_by: maya,
    source_url: 'https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M',
    created: '2026-10-07T19:00:00Z',
    can_edit: false,
  },
  {
    id: 'p3',
    uri: 'spotify:playlist:p3',
    name: 'Quiet CAD Hours',
    description: 'Focus music for drawing parts.',
    artwork: tracks[1].artwork,
    total: 4,
    created_by: adam,
    source_url: 'https://music.apple.com/us/playlist/quiet-cad-hours/pl.u-abc',
    created: '2026-10-01T19:00:00Z',
    can_edit: true,
  },
]

const items: Record<string, Track[]> = {
  p1: tracks.slice(0, 8),
  p2: tracks.slice(6, 12),
  p3: tracks.slice(1, 5),
}

const state: { status: Status; at: number } = {
  at: Date.now(),
  status: {
    backend: 'soloist',
    state: 'playing',
    active: true,
    device: { name: 'Lab Speakers', type: 'Soloist', active: true },
    position_ms: 58000,
    duration_ms: tracks[0].duration_ms,
    volume: 62,
    shuffle: false,
    repeat: 'off',
    track: tracks[0],
    context: { uri: 'spotify:playlist:p1', type: 'playlist', name: 'Build Night' },
    actions: ['pause', 'seek', 'skip_next', 'skip_prev', 'shuffle', 'set_repeat', 'add_to_queue'],
    credit: { by: maya, how: 'started' },
  },
}

let queued: Track[] = [tracks[9]]

const airplayTrack = {
  uri: null,
  id: null,
  type: 'airplay',
  name: 'Clair de Lune',
  artists: [{ uri: null, name: 'Claude Debussy' }],
  album: { uri: null, name: 'Suite bergamasque' },
  duration_ms: 300000,
  explicit: false,
  artwork: tracks[4].artwork,
} as unknown as Track
let airplay: { since: number; resume: boolean } | null = null
let quiet: QuietHours = { enabled: true, window: '21:00-08:00', phase: 'open', locked: false, grace_s: 300, until: '08:00' }

function spotifySnapshot(): Status {
  const s = state.status
  const elapsed = s.state === 'playing' ? Date.now() - state.at : 0
  return { ...s, position_ms: Math.min(s.position_ms + elapsed, s.duration_ms ?? Infinity) }
}

function snapshot(): Status {
  const base = { ...spotifySnapshot(), quiet_hours: quiet, airplay: null }
  if (!airplay) return base
  const pos = Math.min(Date.now() - airplay.since + 74000, airplayTrack.duration_ms)
  return {
    ...base,
    source: 'airplay',
    state: 'playing',
    track: airplayTrack,
    position_ms: pos,
    duration_ms: airplayTrack.duration_ms,
    context: null,
    credit: null,
    skip: null,
    actions: [],
    airplay: { sender: "Adam's iPhone", state: 'playing', started_at: airplay.since / 1000, resume_spotify: airplay.resume },
  }
}

function refusal(): readonly [number, unknown] | null {
  if (airplay)
    return [409, { error: 'airplay_active', message: "AirPlay from Adam's iPhone is playing, so Spotify is paused until it ends", sender: "Adam's iPhone" }]
  if (quiet.phase === 'locked') return [423, { error: 'quiet_hours', message: 'Quiet hours: the speakers are locked until 8:00 AM', until: '08:00' }]
  return null
}

function setStatus(patch: Partial<Status>) {
  state.status = { ...spotifySnapshot(), ...patch }
  state.at = Date.now()
}

function playTrack(track: Track, context: Status['context'] = state.status.context) {
  setStatus({ track, duration_ms: track.duration_ms, position_ms: 0, state: 'playing', context, credit: { by: adam, how: 'started' } })
}

const removedUids = new Set<string>()

function queue(): Queue {
  const ctx = items.p1
  const i = ctx.findIndex((t) => t.uri === state.status.track?.uri)
  return {
    upcoming: [
      ...queued.map((item, n) => ({ uid: `q${n}`, source: 'queue' as const, item, added_by: n === 0 ? maya : adam })),
      ...[...ctx.slice(i + 1), ...tracks, ...tracks].map((item, n) => ({ uid: `c${n}`, source: 'context' as const, item, added_by: null })),
    ].filter((e) => !removedUids.has(e.uid)),
    previous: [],
  }
}

let personal = { token: 'mapu_Xk29fQ7LmPz4Rt8WvB1nC6dY', created: 1760040000, docs: 'https://music.pinewoodrobotics.org/llms.txt' }

const unmatchedSongs = [
  { name: 'Lofi Lab Session (Live)', artists: ['The 5190s'] },
  { name: 'Drive Team Anthem', artists: ['Pit Crew'] },
  { name: 'Untitled Voice Memo', artists: [] },
]

function resolve(link: string): readonly [number, unknown] {
  const base = { url: link, truncated: false }
  const asResolved = (t: Track) => ({
    name: t.name,
    artists: t.artists?.map((a) => a.name) ?? [],
    album: t.album?.name ?? null,
    duration_ms: t.duration_ms,
    artwork: t.artwork,
    uri: t.uri,
  })
  if (/open\.spotify\.com\/track|spotify:track/.test(link)) {
    const t = tracks[2]
    return ok({ ...base, source: 'spotify', kind: 'track', name: t.name, subtitle: byArtists(t), artwork: t.artwork, spotify_uri: t.uri, tracks: [asResolved(t)], total: 1, matched: 1 })
  }
  if (/open\.spotify\.com\/playlist/.test(link))
    return ok({ ...base, source: 'spotify', kind: 'playlist', name: 'Robot-Themed Songs', subtitle: 'Daniel Costa Ramos', artwork: tracks[5].artwork, spotify_uri: 'spotify:playlist:5SLCReZBKclNPPJ0n1bBkp', tracks: tracks.map(asResolved), total: 12, matched: 12, truncated: false })
  if (/music\.apple\.com\/.*playlist|youtube\.com\/playlist\?list=PL/.test(link)) {
    const list = [
      ...tracks.slice(0, 4).map(asResolved),
      { ...unmatchedSongs[0], album: null, duration_ms: 241000, artwork: null, uri: null },
      ...tracks.slice(4, 9).map(asResolved),
      { ...unmatchedSongs[1], album: 'Pit Stop', duration_ms: 182000, artwork: null, uri: null },
      { ...unmatchedSongs[2], album: null, duration_ms: 64000, artwork: null, uri: null },
    ]
    return ok({ ...base, source: link.includes('youtube') ? 'youtube' : 'apple', kind: 'playlist', name: 'Shop Floor Favorites', subtitle: 'Maya', artwork: tracks[3].artwork, spotify_uri: null, tracks: list, total: list.length, matched: 9 })
  }
  return fail(400, "That link isn't a song, album or playlist we can open.")
}

const byArtists = (t: Track) => t.artists?.map((a) => a.name).join(', ') ?? ''

const synthetic: Track[] = Array.from({ length: 600 }, (_, n) => {
  const base = tracks[n % tracks.length]
  return { ...base, uri: `spotify:track:gen${n}`, id: `gen${n}`, name: `${base.name} (Take ${Math.floor(n / tracks.length) + 1})` }
})
items.big = synthetic
playlists.push({
  id: 'big',
  uri: 'spotify:playlist:big',
  name: 'Everything Mix',
  description: 'A very long playlist for testing.',
  artwork: tracks[10].artwork,
  total: synthetic.length,
  created_by: maya,
  source_url: null,
  created: '2026-09-20T19:00:00Z',
  can_edit: false,
})

const albumOf = (t: Track, by: LibraryAlbum['added_by'], added: string, canEdit: boolean): LibraryAlbum => ({
  kind: 'album',
  id: (t.album?.uri ?? '').split(':').pop() ?? '',
  uri: t.album?.uri ?? '',
  name: t.album?.name ?? '',
  artists: t.artists ?? [],
  artwork: t.artwork,
  total: tracks.filter((x) => x.album?.uri === t.album?.uri).length,
  year: '1977',
  duration_ms: null as unknown as number,
  added_by: by,
  added,
  source_url: `https://open.spotify.com/album/${(t.album?.uri ?? '').split(':').pop()}`,
  can_edit: canEdit,
})

const libraryAlbums: LibraryAlbum[] = [
  { ...albumOf(tracks[0], maya, '2026-10-08T21:00:00Z', false), year: '2001' },
  albumOf(tracks[2], { id: 'U01', name: 'Adam Xu', avatar: null }, '2026-10-09T18:00:00Z', true),
]

function trackByUri(uri: string) {
  return tracks.find((t) => t.uri === uri) ?? synthetic.find((t) => t.uri === uri)
}

function addAlbum(link: string, viaImport = false): readonly [number, unknown] {
  if (/music\.apple\.com|youtube\.com/.test(link) && /nomatch/.test(link)) return fail(422, "that album isn't on Spotify as a whole album; use Import as playlist to copy its songs")
  const id = link.match(/album[:/]([A-Za-z0-9]+)/)?.[1]
  if (!id) return fail(400, 'paste a Spotify, Apple Music or YouTube Music album link (use Import as playlist for playlists and songs)')
  const existing = libraryAlbums.find((a) => a.id === id)
  const source = tracks.find((t) => t.album?.uri.endsWith(id)) ?? tracks[5]
  const album = existing ? { ...existing, already: true } : albumOf(source, { id: 'U01', name: 'Adam Xu', avatar: null }, new Date().toISOString(), true)
  if (!existing) libraryAlbums.unshift({ ...album, id, uri: `spotify:album:${id}` })
  const out = existing ? album : libraryAlbums[0]
  return ok(viaImport ? { kind: 'album', album: out } : out)
}

function librarySongs() {
  const byUri = new Map<string, { track: Track; sources: { kind: string; id: string; name: string }[]; added: string }>()
  const add = (t: Track, kind: string, id: string, name: string, added: string) => {
    const row = byUri.get(t.uri) ?? { track: t, sources: [], added }
    row.sources.push({ kind, id, name })
    if (added < row.added) row.added = added
    byUri.set(t.uri, row)
  }
  for (const pl of playlists) for (const t of items[pl.id] ?? []) add(t, 'playlist', pl.id, pl.name, pl.created ?? '2026-01-01')
  for (const a of libraryAlbums) for (const t of tracks.filter((x) => x.album?.uri === a.uri)) add(t, 'album', a.id, a.name, a.added ?? '')
  return [...byUri.values()].map((r) => ({ ...r.track, sources: r.sources, added: r.added }))
}

function libraryRoute(method: string, p: string, url: URL, body: Record<string, unknown>): readonly [number, unknown] | null {
  const catalog = p.match(/^\/api\/albums\/([^/]+)$/)
  if (method === 'GET' && catalog && catalog[1] !== fixtures.album.id) {
    const t = tracks.find((x) => x.album?.uri.endsWith(catalog[1]))
    if (!t?.album) return fail(404, 'not found')
    const albumTracks = tracks.filter((x) => x.album?.uri === t.album?.uri)
    return ok({
      uri: t.album.uri, id: catalog[1], type: 'album', name: t.album.name, artists: t.artists, album_type: 'album', release_date: '1977-10-03',
      total_tracks: albumTracks.length, artwork: t.artwork, tracks: { items: albumTracks, total: albumTracks.length, offset: 0, limit: 50, next: false },
    })
  }
  if (method === 'GET' && p === '/api/app/library') {
    const kind = url.searchParams.get('kind') ?? 'all'
    const list = [
      ...(kind !== 'albums' ? playlists.map((x) => ({ ...x, kind: 'playlist' })) : []),
      ...(kind !== 'playlists' ? libraryAlbums : []),
    ]
    return ok({ items: list })
  }
  if (method === 'POST' && p === '/api/app/library/albums') return addAlbum(String(body.url ?? body.uri ?? ''))
  const album = p.match(/^\/api\/app\/library\/albums\/([^/]+)$/)
  if (album) {
    const found = libraryAlbums.find((a) => a.id === album[1])
    if (!found) return fail(404, 'not in the Library')
    if (method === 'DELETE') {
      if (!found.can_edit) return fail(403, 'only the person who added it can remove it')
      libraryAlbums.splice(libraryAlbums.indexOf(found), 1)
      return ok({ removed: found.uri })
    }
    return ok({ ...found, tracks: tracks.filter((t) => t.album?.uri === found.uri) })
  }
  if (method === 'GET' && p === '/api/app/library/songs') {
    const q = (url.searchParams.get('q') ?? '').toLowerCase()
    const sort = url.searchParams.get('sort') ?? 'recent'
    const offset = Number(url.searchParams.get('offset') ?? 0)
    const limit = Number(url.searchParams.get('limit') ?? 100)
    let list = librarySongs().filter((t) => !q || `${t.name} ${t.artists?.map((a) => a.name).join(' ')} ${t.album?.name}`.toLowerCase().includes(q))
    const key = { title: (t: Track) => t.name, artist: (t: Track) => t.artists?.[0]?.name ?? '', album: (t: Track) => t.album?.name ?? '' }[sort]
    list = key ? list.sort((a, b) => key(a).localeCompare(key(b))) : list.sort((a, b) => b.added.localeCompare(a.added))
    return ok({ items: list.slice(offset, offset + limit), total: list.length })
  }
  if (method === 'POST' && p === '/api/app/library/songs/play') {
    const t = trackByUri(String(body.uri))
    if (!t) return fail(404, 'not in the list')
    playTrack(t, null)
    return ok(snapshot())
  }
  const dup = p.match(/^\/api\/app\/playlists\/([^/]+)\/duplicate$/)
  if (method === 'POST' && dup) {
    const src = playlists.find((x) => x.id === dup[1])
    if (!src) return fail(404, 'playlist not found')
    const copy: AppPlaylist = {
      ...src,
      id: `dup${Date.now()}`,
      uri: `spotify:playlist:dup${Date.now()}`,
      name: String(body.name ?? `${src.name} (copy)`),
      created_by: { id: 'U01', name: 'Adam Xu', avatar: null },
      source_url: null,
      created: new Date().toISOString(),
      can_edit: true,
    }
    playlists.unshift(copy)
    items[copy.id] = [...(items[src.id] ?? [])]
    copy.total = items[copy.id].length
    return ok(copy)
  }
  return null
}

function mutate(patch: Partial<Status>) {
  setStatus(patch)
  return ok(snapshot())
}

const ok = (result: unknown) => [200, { result }] as const
const fail = (status: number, error: string) => [status, { error }] as const

function handle(method: string, url: URL, body: Record<string, unknown>): readonly [number, unknown] {
  const p = url.pathname.replace(/\/$/, '')
  const route = `${method} ${p}`
  if (route === 'GET /api/app/me') return ok({ ...adam, admin: false, kind: 'slack' })
  if (route === 'POST /auth/slack/logout') return ok(null)
  if (route === 'GET /api/app/token') return ok(personal)
  if (route === 'POST /api/app/token/regenerate') {
    personal = { ...personal, token: `mapu_${Math.random().toString(36).slice(2, 14)}${Math.random().toString(36).slice(2, 14)}`, created: Date.now() / 1000 }
    return ok(personal)
  }
  if (route === 'GET /api/activity') {
    const since = Number(url.searchParams.get('since') ?? 0)
    const limit = Number(url.searchParams.get('limit') ?? 500)
    const list = since ? activityLog.filter((e) => e.id > since) : activityLog.slice(-limit)
    return ok({ entries: list, latest: activityId })
  }
  if (route === 'GET /api/status') return ok(snapshot())
  if (route === 'GET /api/queue') return ok(queue())
  if (route === 'GET /api/lyrics') {
    if (state.status.track?.uri !== tracks[0].uri) return fail(404, 'no lyrics found')
    return ok({ ...lyrics, position_ms: snapshot().position_ms, line: 0 })
  }
  if (route === 'POST /api/airplay/stop') {
    if (!airplay) return [409, { error: 'airplay_inactive', message: 'no AirPlay session' }] as const
    if (airplay.resume) setStatus({ state: 'playing' })
    airplay = null
    return ok(snapshot())
  }
  const blocked = /^POST \/api\/(play|playpause|next|previous|back|queue\/jump|playlists\/[^/]+\/play)$/.test(route) ? refusal() : null
  if (blocked && !(airplay === null && route === 'POST /api/playpause' && state.status.state === 'playing')) return blocked
  if (route === 'POST /api/play') {
    const target = tracks.find((t) => t.uri === body.uri) ?? tracks[Number(body.offset) || 0]
    playTrack(target)
    return ok(snapshot())
  }
  if (route === 'POST /api/pause') return mutate({ state: 'paused' })
  if (route === 'POST /api/playpause') return mutate({ state: state.status.state === 'playing' ? 'paused' : 'playing' })
  if (route === 'POST /api/next' || route === 'POST /api/previous') {
    const i = tracks.findIndex((t) => t.uri === state.status.track?.uri)
    const next = route.endsWith('next') ? (queued.shift() ?? tracks[(i + 1) % tracks.length]) : tracks[Math.max(0, i - 1)]
    const from = state.status.track?.uri ?? ''
    playTrack(next)
    state.status = { ...state.status, skip: { by: maya, from, at: Date.now() } }
    return ok(snapshot())
  }
  if (route === 'POST /api/seek') return mutate({ position_ms: Number(body.position_ms) })
  if (route === 'POST /api/volume') return mutate({ volume: Number(body.volume) })
  if (route === 'POST /api/shuffle') return mutate({ shuffle: !!body.enabled })
  if (route === 'POST /api/repeat') return mutate({ repeat: body.mode as Status['repeat'] })
  if (route === 'POST /api/queue/remove') {
    const visible = queue().upcoming
    const uids = (body.uids as string[] | undefined) ?? (body.uid ? [String(body.uid)] : [visible[Number(body.index)]?.uid].filter((u): u is string => !!u))
    if (uids.some((u) => !visible.some((e) => e.uid === u))) return fail(404, 'not in Up Next')
    uids.forEach((u) => removedUids.add(u))
    return ok(queue())
  }
  if (route === 'POST /api/queue') {
    const uris = (body.uris as string[]) ?? [body.uri]
    queued.push(...tracks.filter((t) => uris.includes(t.uri)))
    return ok({ added: uris })
  }
  if (route === 'GET /api/search') {
    const q = (url.searchParams.get('q') ?? '').toLowerCase()
    const hits = tracks.filter((t) => `${t.name} ${t.artists?.map((a) => a.name).join(' ')}`.toLowerCase().includes(q))
    const page = <T,>(list: T[]) => ({ items: list, total: list.length, offset: 0, limit: 10, next: false })
    return ok({
      tracks: page(hits),
      albums: page(q.includes('daft') ? [fixtures.album] : []),
      artists: page(hits.slice(0, 1).map((t) => ({ ...t.artists![0], id: 'a1', type: 'artist', genres: null, artwork: t.artwork }))),
      playlists: page([]),
    })
  }
  if (route === 'POST /api/resolve') return resolve(String(body.url))
  const artistAlbums = p.match(/^\/api\/artists\/([^/]+)\/albums$/)
  if (method === 'GET' && artistAlbums) {
    const limit = Number(url.searchParams.get('limit') ?? 20)
    if (limit > 10) return fail(400, 'Spotify 400: Invalid limit')
    const offset = Number(url.searchParams.get('offset') ?? 0)
    const all = tracks.concat(tracks.slice(0, 2)).map((t, i) => ({
      ...fixtures.album,
      id: `al${i}`,
      uri: `spotify:album:al${i}`,
      name: t.album?.name ?? `Album ${i}`,
      artwork: t.artwork,
      album_type: i % 3 === 2 ? 'single' : 'album',
    }))
    return ok({ items: all.slice(offset, offset + limit), total: all.length, offset, limit, next: offset + limit < all.length })
  }
  const artist = p.match(/^\/api\/artists\/([^/]+)$/)
  if (method === 'GET' && artist) return ok({ uri: 'spotify:artist:a1', id: 'a1', type: 'artist', name: 'Daft Punk', genres: ['french house'], artwork: tracks[0].artwork })
  if (route === 'GET /api/app/playlists') return ok(playlists)
  if (route === 'POST /api/app/playlists') {
    const created: AppPlaylist = {
      id: `p${Date.now()}`,
      uri: `spotify:playlist:new${Date.now()}`,
      name: String(body.name),
      description: String(body.description ?? ''),
      artwork: null,
      total: 0,
      created_by: adam,
      source_url: null,
      created: new Date().toISOString(),
      can_edit: true,
    }
    playlists.unshift(created)
    items[created.id] = []
    return ok(created)
  }
  if (route === 'POST /api/app/playlists/import' && body.as !== 'playlist' && /album\//.test(String(body.url))) return addAlbum(String(body.url), true)
  if (route === 'POST /api/app/playlists/import') {
    if (String(body.url).includes('private')) return fail(403, 'That playlist is private. Make it public on Spotify and try again.')
    const created: AppPlaylist = {
      id: `imp${Date.now()}`,
      uri: `spotify:playlist:imp${Date.now()}`,
      name: 'Imported Mix',
      description: '',
      artwork: tracks[4].artwork,
      total: 12,
      created_by: adam,
      source_url: String(body.url),
      created: new Date().toISOString(),
      can_edit: true,
    }
    playlists.unshift(created)
    items[created.id] = tracks
    const apple = /music\.apple\.com|youtube\.com|youtu\.be/.test(String(body.url))
    return ok({
      playlist: created,
      imported: apple ? 9 : 100,
      total: apple ? 12 : null,
      truncated: !apple,
      unmatched: apple ? unmatchedSongs : [],
    })
  }
  const one = p.match(/^\/api\/app\/playlists\/([^/]+)$/)
  if (one) {
    const pl = playlists.find((x) => x.id === one[1])
    if (!pl) return fail(404, 'playlist not found')
    if (method === 'GET') return ok(pl)
    if (method === 'PATCH') return ok(Object.assign(pl, body))
    if (method === 'DELETE') {
      playlists.splice(playlists.indexOf(pl), 1)
      return ok({ removed: pl.uri })
    }
  }
  const library = libraryRoute(method, p, url, body)
  if (library) return library
  const its = p.match(/^\/api\/playlists\/([^/]+)\/items$/)
  if (its) {
    const list = items[its[1]] ?? []
    if (method === 'GET') {
      const offset = Number(url.searchParams.get('offset') ?? 0)
      return ok({ items: list.slice(offset, offset + 50), total: list.length, offset, limit: 50, next: offset + 50 < list.length })
    }
    if (method === 'PUT') {
      const from = Number(body.range_start)
      const before = Number(body.insert_before)
      const next = [...list]
      const [moved] = next.splice(from, 1)
      next.splice(before > from ? before - 1 : before, 0, moved)
      items[its[1]] = next
      return ok({ snapshot_id: 'x' })
    }
    const uris = body.uris as string[]
    if (method === 'POST') {
      const added = uris.map((u) => trackByUri(u)).filter((t): t is Track => !!t)
      const next = [...list]
      next.splice(typeof body.position === 'number' ? body.position : next.length, 0, ...added)
      items[its[1]] = next
    }
    if (method === 'DELETE') items[its[1]] = list.filter((t) => !uris.includes(t.uri))
    const pl = playlists.find((x) => x.id === its[1])
    if (pl) pl.total = items[its[1]].length
    return ok({ snapshot_id: 'x' })
  }
  const play = p.match(/^\/api\/playlists\/([^/]+)\/play$/)
  if (play) {
    const list = items[play[1]] ?? tracks
    const offset = body.offset
    const target = typeof offset === 'string' ? list.find((t) => t.uri === offset) : list[Number(offset) || 0]
    if (body.shuffle !== undefined) setStatus({ shuffle: !!body.shuffle })
    const pl = playlists.find((x) => x.id === play[1])
    playTrack(target ?? list[0], { uri: pl?.uri ?? '', type: 'playlist', name: pl?.name })
    return ok(snapshot())
  }
  if (route === 'GET /api/albums/' + fixtures.album.id) return ok({ ...fixtures.album, tracks: { items: tracks.filter((t) => t.album?.uri === fixtures.album.uri), total: 3, offset: 0, limit: 50, next: false } })
  return fail(404, 'not found')
}

class MockEventSource extends EventTarget {
  static readonly CONNECTING = 0
  static readonly OPEN = 1
  static readonly CLOSED = 2
  readyState = 0
  private timer: ReturnType<typeof setInterval>
  constructor() {
    super()
    setTimeout(() => {
      this.readyState = 1
      this.dispatchEvent(new Event('open'))
      this.emit()
    }, 50)
    this.timer = setInterval(() => this.emit(), 1000)
    activityBus.addEventListener('activity', this.forward)
    openSources.add(this)
  }
  private forward = (e: Event) => {
    this.dispatchEvent(new MessageEvent('activity', { data: JSON.stringify((e as CustomEvent).detail) }))
  }
  private emit() {
    this.dispatchEvent(new MessageEvent('status', { data: JSON.stringify(snapshot()) }))
  }
  close() {
    this.readyState = 2
    clearInterval(this.timer)
    activityBus.removeEventListener('activity', this.forward)
    openSources.delete(this)
  }
}

export function installMock(param: string | null) {
  const stored = sessionStorage.getItem('mock')
  const mode: Mode = param && ['signedout', 'signedout-slack', 'signedout-google', 'writes', 'down'].includes(param) ? (param as Mode) : param !== null ? 'full' : ((stored as Mode) ?? 'full')
  sessionStorage.setItem('mock', mode)
  window.__mockCalls = []
  window.__mockActivity = (action, detail = {}, who = 'howard', origin = 'web') => {
    const entry = logActivity(people[who] ?? howard, action, detail, origin)
    activityBus.dispatchEvent(new CustomEvent('activity', { detail: entry }))
    return entry.id
  }
  window.__mockActivitySilent = (action, detail = {}, who = 'howard', agoMs = 0) =>
    logActivity(people[who] ?? howard, action, detail, 'web', Date.now() - agoMs).id
  window.__mockReconnect = () => openSources.forEach((source) => source.dispatchEvent(new Event('open')))
  window.__mockActivityUpdate = (id, patch) => {
    const entry = activityLog.find((e) => e.id === id)
    if (!entry) return
    Object.assign(entry.detail, patch)
    activityBus.dispatchEvent(new CustomEvent('activity', { detail: { ...entry } }))
  }
  window.__mockLab = {
    next: () => {
      const i = tracks.findIndex((t) => t.uri === state.status.track?.uri)
      playTrack(tracks[(i + 1) % tracks.length])
    },
    pause: () => setStatus({ state: 'paused' }),
    resume: () => setStatus({ state: 'playing' }),
    seek: (ms) => setStatus({ position_ms: ms }),
    airplay: (on, resume = true) => {
      airplay = on ? { since: Date.now(), resume } : null
      if (on) setStatus({ state: 'paused' })
    },
    quiet: (phase, idle = false) => {
      const now = Date.now() / 1000
      quiet = { ...quiet, phase, locked: phase === 'locked', idle_since: idle ? now - 60 : null, locks_at: idle ? now + 240 : null }
      if (phase === 'locked') setStatus({ state: 'paused' })
    },
  }
  const realFetch = window.fetch.bind(window)

  window.fetch = async (input, init) => {
    const url = new URL(typeof input === 'string' ? input : input instanceof URL ? input.href : input.url, location.origin)
    const method = (init?.method ?? 'GET').toUpperCase()
    if (!/^\/(api|auth)(\/|$)/.test(url.pathname)) return realFetch(input, init)
    const body = init?.body ? JSON.parse(String(init.body)) : {}
    const origin = new Headers(init?.headers).get('X-Client-Origin')
    if (method !== 'GET') window.__mockCalls.push({ method, path: url.pathname + url.search, body, origin })
    if (mode === 'writes' && (method === 'GET' || url.pathname === '/api/resolve')) return realFetch(input, init)
    const slow = url.pathname.endsWith('/import') || url.pathname === '/api/resolve'
    await new Promise((r) => setTimeout(r, slow ? (/apple|youtu/.test(String(body.url ?? '')) ? 3500 : 1500) : 120))
    const down = mode === 'down' && method === 'GET' && /^\/api\/(search|app\/playlists|albums|artists|playlists)/.test(url.pathname)
    if (url.pathname === '/auth/methods')
      return new Response(JSON.stringify({ slack: mode !== 'signedout-google', google: mode !== 'signedout-slack' }), { status: 200, headers: { 'Content-Type': 'application/json' } })
    const [status, json] = down
      ? fail(502, 'Bad gateway')
      : mode.startsWith('signedout')
        ? fail(401, 'unauthorized')
        : mode === 'writes' && !url.pathname.startsWith('/api/app/')
          ? ok({ mocked: true })
          : handle(method, url, body)
    return new Response(JSON.stringify(json), { status, headers: { 'Content-Type': 'application/json' } })
  }

  if (mode === 'full') window.EventSource = MockEventSource as unknown as typeof EventSource
  console.info(`[mock] mode=${mode}`)
}
