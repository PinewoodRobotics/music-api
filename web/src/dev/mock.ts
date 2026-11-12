import type { ActivityEntry, AdminEntry, AdminList, BanEntry, AppPlaylist, EffectsVolume, KnownUser, LibraryAlbum, Lyrics, QuietAdmin, QuietHours, QuietSettings, Queue, ServiceInfo, Status, SystemInfo, Track, UpdateAuto, UpdateHistoryEntry, UpdateInfo, UpdateRun } from '../lib/api'
import fixtures from './fixtures.json'

type Mode = 'full' | 'signedout' | 'signedout-slack' | 'signedout-google' | 'writes' | 'down' | 'banned'
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
      airplay: (on: boolean, resume?: boolean, playing?: boolean) => void
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
    device: { name: 'PEARL Speakers', type: 'Soloist', active: true },
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
type AirPlaySession = { at: number; pos: number; playing: boolean; resume: boolean }
let airplay: AirPlaySession | null = null
let quiet: QuietHours = { enabled: true, window: '21:00-08:00', phase: 'open', locked: false, grace_s: 300, until: '08:00' }
let quietIdleAt: number | null = null

const airplayPos = (a: AirPlaySession) => Math.min(a.pos + (a.playing ? Date.now() - a.at : 0), airplayTrack.duration_ms ?? Infinity)

function airplaySet(patch: Partial<AirPlaySession>) {
  if (airplay) airplay = { ...airplay, pos: airplayPos(airplay), at: Date.now(), ...patch }
}

function quietSnapshot(playing: boolean): QuietHours {
  if (quiet.phase !== 'grace') return { ...quiet, idle_since: null, locks_at: null }
  const idleAt = playing ? null : (quietIdleAt ??= Date.now() / 1000 - 60)
  if (playing) quietIdleAt = null
  return { ...quiet, idle_since: idleAt, locks_at: idleAt ? Math.round(idleAt + (quiet.grace_s ?? 300)) : null }
}

function spotifySnapshot(): Status {
  const s = state.status
  const elapsed = s.state === 'playing' ? Date.now() - state.at : 0
  return { ...s, position_ms: Math.min(s.position_ms + elapsed, s.duration_ms ?? Infinity) }
}

function snapshot(): Status {
  const spotify = spotifySnapshot()
  const base = { ...spotify, quiet_hours: quietSnapshot(!airplay && spotify.state === 'playing'), airplay: null }
  if (!airplay) return base
  const state = airplay.playing ? 'playing' : 'paused'
  return {
    ...base,
    quiet_hours: quietSnapshot(airplay.playing),
    source: 'airplay',
    state,
    track: airplayTrack,
    position_ms: airplayPos(airplay),
    duration_ms: airplayTrack.duration_ms,
    context: null,
    credit: null,
    skip: null,
    actions: [],
    airplay: { sender: "Adam's iPhone", state, started_at: airplay.at / 1000, resume_spotify: airplay.resume },
  }
}

function airplayControl(route: string, body: Record<string, unknown>): readonly [number, unknown] | null {
  if (!airplay) return null
  if (route === 'POST /api/play' && Object.keys(body).length) return refusal()
  if (route === 'POST /api/play') airplaySet({ playing: true })
  else if (route === 'POST /api/pause') airplaySet({ playing: false })
  else if (route === 'POST /api/playpause') airplaySet({ playing: !airplay.playing })
  else if (route === 'POST /api/next' || route === 'POST /api/previous') airplaySet({ pos: 0, playing: true })
  else return null
  return ok(snapshot())
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

const sec = () => Date.now() / 1000
const wave = (t: number, period: number, phase = 0) => Math.sin((t / period) * Math.PI * 2 + phase)
const bootAt = sec() - 3 * 86400 - 5 * 3600

function cpuAt(t: number) {
  return Math.round((40 + 14 * wave(t, 90) + 7 * wave(t, 23, 1) + 4 * wave(t, 7, 2)) * 10) / 10
}
const tempAt = (t: number) => Math.round((58.5 + 2.6 * wave(t, 140) + 0.8 * wave(t, 11)) * 10) / 10

const mockServices: ServiceInfo[] = [
  { name: 'soloist', unit: 'soloist.service', scope: 'user', state: 'active', sub: 'running', since: bootAt + 60, enabled: 'enabled', restartable: true },
  { name: 'music-api', unit: 'music-api.service', scope: 'user', state: 'active', sub: 'running', since: sec() - 5 * 3600, enabled: 'enabled', restartable: true },
  { name: 'airplay', unit: 'shairport-sync.service', scope: 'user', state: 'active', sub: 'running', since: bootAt + 62, enabled: 'enabled', restartable: true },
  { name: 'music-display', unit: 'music-display.service', scope: 'user', state: 'active', sub: 'running', since: sec() - 5 * 3600, enabled: 'enabled', restartable: true },
  { name: 'quiet-hours.timer', unit: 'quiet-hours.timer', scope: 'user', state: 'active', sub: 'waiting', since: bootAt + 70, enabled: 'enabled', restartable: false },
  { name: 'cloudflared', unit: 'cloudflared.service', scope: 'system', state: 'active', sub: 'running', since: bootAt + 30, enabled: 'enabled', restartable: false },
]

function systemInfo(): SystemInfo {
  const t = sec()
  const history = Array.from({ length: 120 }, (_, i) => {
    const at = t - (119 - i) * 5
    return { t: Math.round(at), cpu: cpuAt(at), temp: tempAt(at) }
  })
  const gib = 1024 ** 3
  return {
    sampled_at: t,
    hostname: 'robotics-pi',
    model: 'Raspberry Pi 3 Model B Plus Rev 1.3',
    uptime_s: t - bootAt,
    cpu: {
      percent: cpuAt(t),
      cores: [0, 1, 2, 3].map((c) => Math.max(2, Math.min(98, Math.round(cpuAt(t) + 16 * wave(t, 13 + c * 5, c) + c * 2)))),
      count: 4,
      freq_mhz: 1400,
      max_mhz: 1400,
    },
    load: [1.12 + 0.3 * wave(t, 60), 0.94, 0.71],
    temp_c: tempAt(t),
    power: {
      source: 'vcgencmd',
      raw: 'throttled=0x50000',
      now: { under_voltage: false, freq_capped: false, throttled: false, soft_temp_limit: false },
      since_boot: { under_voltage: true, freq_capped: false, throttled: true, soft_temp_limit: false },
      events: 3,
      last_event_at: t - 2 * 3600,
    },
    memory: { total: 0.9 * gib, available: 0.38 * gib, used: 0.52 * gib, percent: 57.8, swap_total: 0.1 * gib, swap_used: 0.02 * gib },
    disk: { path: '/', total: 29.1 * gib, used: 7.4 * gib, free: 20.8 * gib, percent: 25.4 },
    network: { interface: 'wlan0', ip: '192.168.4.27', ssid: 'Pinewood-IoT', bssid: 'a4:2b:b0:5c:19:e2', signal_dbm: -61 - Math.round(2 * wave(t, 30)), quality: 62, bitrate_mbps: 65, freq_mhz: 2437 },
    services: mockServices,
    versions: {
      commit: 'e801f38c0f6f2d6a1a3b0b1c4d5e6f708192a3b4',
      commit_short: 'e801f38',
      subject: 'Docs: sound effects in README',
      built_at: sec() - 5 * 3600,
      python: '3.11.2',
      soloist: '0.14.2',
      shairport_sync: '4.3.2',
      kernel: '6.6.51+rpt-rpi-v8',
      os: 'Debian GNU/Linux 12 (bookworm)',
    },
    history,
  }
}

const quietSettings: QuietSettings = { enabled: true, start: '21:00', end: '08:00', grace_min: 5, source: 'env', env_window: '21:00-08:00', updated_by: null, updated_at: null }
let quietOverride: NonNullable<QuietAdmin['status']['override']> | null = null
let effectsVolume: Omit<EffectsVolume, 'media_volume'> = { mode: 'follow', level: 62, play_during_quiet_hours: true, updated_by: null, updated_at: null }

function quietAdmin(): QuietAdmin {
  const tomorrow = new Date()
  tomorrow.setHours(Number(quietSettings.start.slice(0, 2)), Number(quietSettings.start.slice(3)), 0, 0)
  const status = {
    ...quiet,
    enabled: quietSettings.enabled,
    window: quietSettings.enabled ? `${quietSettings.start}-${quietSettings.end}` : null,
    until: quietSettings.end,
    grace_s: quietSettings.grace_min * 60,
    starts_at: tomorrow.getTime() / 1000,
    override: quietOverride,
  }
  return { settings: { ...quietSettings }, status }
}

function applyQuietSettings() {
  quiet = { ...quiet, enabled: quietSettings.enabled, window: quietSettings.enabled ? `${quietSettings.start}-${quietSettings.end}` : null, until: quietSettings.end, grace_s: quietSettings.grace_min * 60 }
}

const bannedUsers: BanEntry[] = [
  { key: 'u05', id: 'U05', email: null, name: 'Jonas Weber', reason: "Kept skipping everyone's songs during the **Friday build session**.\n\n- Skipped 40 tracks in an hour\n- Ignored two warnings in `#lab-music`\n\n> Take a break and come back next week.", until: sec() + 4 * 86400, banned_by: { id: 'U03', name: 'Howard Kent' }, banned: sec() - 2 * 86400 },
  { key: 'spam@example.com', id: null, email: 'spam@example.com', name: null, reason: 'Used a leaked API token to queue ads.', until: null, banned_by: { id: 'U01', name: 'Adam Xu' }, banned: sec() - 9 * 86400 },
]
const adminUsers: AdminEntry[] = [
  { key: 'email:howard@robotics.example', id: null, email: 'howard@robotics.example', name: 'Howard Kent', avatar: null, source: 'config', added_by: null, added: null, you: false },
  { key: 'U01', id: 'U01', email: 'adam@robotics.example', name: 'Adam Xu', avatar: null, source: 'admin', added_by: { id: 'U03', name: 'Howard Kent' }, added: sec() - 6 * 86400, you: true },
]
const knownUsers: KnownUser[] = [
  { id: 'U01', name: 'Adam Xu', avatar: null, email: 'adam@robotics.example', admin: true, last_seen: sec() - 30 },
  { id: 'U02', name: 'Maya Lindqvist', avatar: null, email: 'maya@robotics.example', admin: false, last_seen: sec() - 3600 },
  { id: 'U03', name: 'Howard Kent', avatar: null, email: 'howard@robotics.example', admin: true, last_seen: sec() - 86400 },
  { id: 'U04', name: 'Priya Natarajan', avatar: null, email: 'priya@robotics.example', admin: false, last_seen: sec() - 2 * 86400 },
  { id: 'U05', name: 'Jonas Weber', avatar: null, email: null, admin: false, last_seen: sec() - 9 * 86400 },
]

function adminList(): AdminList {
  const ids = new Set(adminUsers.map((a) => a.id))
  const emails = new Set(adminUsers.map((a) => a.email))
  return { admins: adminUsers, known: knownUsers.map((u) => ({ ...u, admin: ids.has(u.id) || emails.has(u.email) })) }
}

const updateCommits = [
  { commit: 'd41c0b7a', short: 'd41c0b7', subject: 'Admin: system health, quiet hours, admins, updates and services', author: 'Adam Xu', date: sec() - 2 * 3600 },
  { commit: 'b93e2f10', short: 'b93e2f1', subject: 'Display: smoother progress strip on slow SD cards', author: 'Adam Xu', date: sec() - 20 * 3600 },
  { commit: '7a5d8c33', short: '7a5d8c3', subject: 'Queue: keep the autoplay credit when skipping', author: 'Maya Lindqvist', date: sec() - 2 * 86400 },
]
let updateRunStart: number | null = null
let updateAction: 'update' | 'revert' = 'update'
let reverted = false
const autoUpdate: UpdateAuto = { enabled: true, time: '03:00', updated_by: null, updated_at: null }
const night = (n: number, h = 3, m = 0) => {
  const d = new Date()
  d.setDate(d.getDate() - n)
  d.setHours(h, m, 0, 0)
  return Math.floor(d.getTime() / 1000)
}
const updateHistory: UpdateHistoryEntry[] = [
  { id: 'auto-1', action: 'update', auto: true, outcome: 'skipped', result: 'Not safe to restart: music is playing', from: 'e801f38c', to: 'd41c0b7a', started_at: night(0, 3, 1), at: night(0, 3, 1), by: null, notes: [] },
  { id: 'auto-2', action: 'update', auto: true, outcome: 'updated', result: 'Updated to e801f38: Docs: sound effects in README', from: '5c2a9e14', to: 'e801f38c', started_at: night(1), at: night(1) + 40, by: null, notes: [] },
  { id: 'auto-3', action: 'update', auto: true, outcome: 'skipped', result: 'Already up to date', from: '5c2a9e14', to: '5c2a9e14', started_at: night(2), at: night(2), by: null, notes: [], count: 3 },
  { id: 'run-4', action: 'update', auto: false, outcome: 'updated', result: 'Updated to 5c2a9e1: Effects: duck the music under sound effects', from: '0b77d2f9', to: '5c2a9e14', started_at: night(5, 14, 12), at: night(5, 14, 13), by: { id: adam.id, name: adam.name }, notes: ['deploy/install-linux.sh changed: check it for new packages or setup steps and run them on the Pi by hand (they need sudo)'] },
  { id: 'auto-5', action: 'update', auto: true, outcome: 'rolled_back', result: 'Rolled back to 0b77d2f; the failed build is kept in music-api-v2.failed', from: '0b77d2f9', to: '9f13ab02', started_at: night(6), at: night(6) + 75, by: null, notes: [] },
  { id: 'run-6', action: 'revert', auto: false, outcome: 'reverted', result: 'Rolled back to 0b77d2f; 3e9c5d1 is kept as the previous version', from: '3e9c5d10', to: '0b77d2f9', started_at: night(8, 18, 40), at: night(8, 18, 41), by: { id: adam.id, name: adam.name }, notes: [] },
]
const UPDATE_STEPS: [number, string, 'info' | 'warn' | 'error'][] = [
  [0.2, 'Downloading build d41c0b7 from GitHub', 'info'],
  [1.2, 'Verifying checksum', 'info'],
  [2.2, 'Unpacking into releases/d41c0b7', 'info'],
  [3.2, 'Switching the current release', 'info'],
  [3.8, 'Restarting music-api', 'info'],
  [6.0, 'music-api is healthy again', 'info'],
]
const UPDATE_DONE = 6.5

function updateInfo(): UpdateInfo {
  const done = updateRunStart !== null && sec() - updateRunStart >= UPDATE_DONE
  const behind = done ? 0 : updateCommits.length
  const deployedCommit = done ? updateCommits[0] : { commit: 'e801f38c', short: 'e801f38', subject: 'Docs: sound effects in README', date: sec() - 5 * 3600 }
  let run: UpdateRun | null = null
  if (updateRunStart !== null) {
    const elapsed = sec() - updateRunStart
    run = {
      id: 'run-1',
      action: updateAction,
      auto: false,
      by: { id: adam.id, name: adam.name },
      state: done ? 'succeeded' : 'running',
      started_at: updateRunStart,
      finished_at: done ? updateRunStart + UPDATE_DONE : null,
      from: 'e801f38',
      to: 'd41c0b7',
      result: done ? 'Now running d41c0b7.' : null,
      log: UPDATE_STEPS.filter(([at]) => elapsed >= at).map(([at, msg, level]) => ({ t: updateRunStart! + at, msg, level })),
    }
  }
  return {
    configured: true,
    setup_hint: null,
    deployed: { ...deployedCommit, built_at: deployedCommit.date },
    latest: { commit: updateCommits[0].commit, short: updateCommits[0].short, subject: updateCommits[0].subject, date: updateCommits[0].date },
    build: { commit: updateCommits[0].commit, short: updateCommits[0].short, built_at: updateCommits[0].date + 600, ready: true },
    behind,
    commits: behind ? updateCommits : [],
    changes: { files: ['server.py', 'web/src'], restarts: behind ? ['music-api'] : [], units: [], enable: [], notes: behind ? ['Run sh deploy/install-airplay.sh on the Pi to pick up the new AirPlay hooks.'] : [] },
    fetched_at: sec() - 90,
    fetch_error: null,
    run,
    auto: autoUpdate,
    history: updateHistory,
    previous: reverted ? null : { commit: '5c2a9e14', short: '5c2a9e1', subject: 'Effects: duck the music under sound effects', built_at: night(5, 14, 0) },
  }
}

function finishMockRun() {
  if (updateRunStart === null || sec() - updateRunStart < UPDATE_DONE || updateHistory[0]?.id === `run-${updateRunStart}`) return
  const revert = updateAction === 'revert'
  updateHistory.unshift({
    id: `run-${updateRunStart}`,
    action: updateAction,
    auto: false,
    outcome: revert ? 'reverted' : 'updated',
    result: revert ? 'Rolled back to 5c2a9e1; e801f38 is kept as the previous version' : 'Now running d41c0b7.',
    from: 'e801f38c',
    to: revert ? '5c2a9e14' : 'd41c0b7a',
    started_at: updateRunStart,
    at: updateRunStart + UPDATE_DONE,
    by: { id: adam.id, name: adam.name },
    notes: [],
  })
  updateHistory.splice(10)
  if (revert) reverted = true
}

function serviceLog(name: string) {
  const t = sec()
  const stamp = (ago: number) => new Date((t - ago) * 1000).toLocaleString('en-US', { month: 'short', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false })
  const lines = ['started', 'GET /api/status 200 4ms', 'GET /api/queue 200 11ms', 'event: track changed', 'GET /api/status 200 3ms', 'POST /api/volume 200 9ms', 'spotify: token refreshed']
  return Array.from({ length: 80 }, (_, i) => `${stamp((80 - i) * 37)} robotics-pi ${name}[812]: ${lines[(i * 5) % lines.length]}`)
}

function handleAdmin(method: string, p: string, body: Record<string, unknown>): readonly [number, unknown] | null {
  const route = `${method} ${p}`
  if (route === 'GET /api/admin/system') return ok(systemInfo())
  if (route === 'GET /api/admin/quiet-hours') return ok(quietAdmin())
  if (route === 'PUT /api/admin/quiet-hours') {
    if (body.reset) Object.assign(quietSettings, { enabled: true, start: '21:00', end: '08:00', grace_min: 5, source: 'env', updated_by: null, updated_at: null })
    else {
      const { enabled, start, end, grace_min } = body as Partial<QuietSettings>
      Object.assign(quietSettings, { ...(enabled !== undefined && { enabled }), ...(start && { start }), ...(end && { end }), ...(grace_min !== undefined && { grace_min }) })
      Object.assign(quietSettings, { source: 'admin', updated_by: { id: adam.id, name: adam.name }, updated_at: sec() })
    }
    applyQuietSettings()
    return ok(quietAdmin())
  }
  if (route === 'GET /api/admin/effects-volume') return ok({ ...effectsVolume, media_volume: state.status.volume ?? 50 })
  if (route === 'PUT /api/admin/effects-volume') {
    const { mode, level, play_during_quiet_hours } = body as Partial<EffectsVolume>
    effectsVolume = { ...effectsVolume, ...(mode && { mode }), ...(level !== undefined && { level }), ...(play_during_quiet_hours !== undefined && { play_during_quiet_hours }), updated_by: { id: adam.id, name: adam.name }, updated_at: sec() }
    return ok({ ...effectsVolume, media_volume: state.status.volume ?? 50 })
  }
  if (route === 'POST /api/admin/quiet-hours/override') {
    const until_ts = sec() + 8 * 3600
    const by = { id: adam.id, name: adam.name }
    if (body.action === 'unlock') {
      quietOverride = { kind: 'unlocked', until_ts, by }
      quiet = { ...quiet, phase: 'open', locked: false }
    } else if (body.action === 'lock') {
      if (quiet.phase === 'open' && !quietOverride) return fail(409, 'Quiet hours are not active right now')
      quietOverride = { kind: 'locked', until_ts, by }
      quiet = { ...quiet, phase: 'locked', locked: true }
      setStatus({ state: 'paused' })
    } else quietOverride = null
    return ok(quietAdmin())
  }
  if (route === 'GET /api/admin/bans') return ok({ bans: bannedUsers.filter((b) => b.until == null || b.until > sec()) })
  if (route === 'POST /api/admin/bans') {
    const known = knownUsers.find((u) => u.id === body.id || (body.email && u.email === body.email))
    const email = typeof body.email === 'string' ? body.email.toLowerCase() : null
    const id = typeof body.id === 'string' ? body.id : null
    const key = (id ?? email ?? '').toLowerCase()
    if (bannedUsers.some((b) => b.key === key)) return fail(409, 'already banned')
    const reason = typeof body.reason === 'string' ? body.reason.trim() : ''
    if (!reason) return fail(400, 'reason is required')
    if (reason.length > 2000) return fail(400, 'reason is too long')
    const until = typeof body.until === 'number' ? body.until : null
    if (until != null && until <= sec()) return fail(400, 'until must be in the future')
    bannedUsers.unshift({ key, id, email, name: known?.name ?? null, reason, until, banned_by: { id: adam.id, name: adam.name }, banned: sec() })
    return ok({ bans: bannedUsers })
  }
  const unbanning = p.match(/^\/api\/admin\/bans\/(.+)$/)
  if (method === 'DELETE' && unbanning) {
    const i = bannedUsers.findIndex((b) => b.key === decodeURIComponent(unbanning[1]))
    if (i < 0) return fail(404, 'not banned')
    bannedUsers.splice(i, 1)
    return ok({ bans: bannedUsers })
  }
  if (route === 'GET /api/admin/admins') return ok(adminList())
  if (route === 'POST /api/admin/admins') {
    const known = knownUsers.find((u) => u.id === body.id || (body.email && u.email === body.email))
    const email = typeof body.email === 'string' ? body.email : (known?.email ?? null)
    const id = typeof body.id === 'string' ? body.id : (known?.id ?? null)
    if (adminUsers.some((a) => (id && a.id === id) || (email && a.email === email))) return fail(409, 'Already an admin')
    adminUsers.push({ key: id ?? `email:${email}`, id, email, name: known?.name ?? null, avatar: null, source: 'admin', added_by: { id: adam.id, name: adam.name }, added: sec(), you: false })
    return ok(adminList())
  }
  const removing = p.match(/^\/api\/admin\/admins\/(.+)$/)
  if (method === 'DELETE' && removing) {
    const key = decodeURIComponent(removing[1])
    const target = adminUsers.find((a) => a.key === key)
    if (!target) return fail(404, 'Not an admin')
    if (target.source === 'config') return fail(409, 'Server config admins cannot be removed here')
    if (adminUsers.length === 1) return fail(409, 'You are the last admin')
    adminUsers.splice(adminUsers.indexOf(target), 1)
    return ok(adminList())
  }
  if (route === 'GET /api/admin/update') {
    finishMockRun()
    const info = updateInfo()
    if (info.run?.state === 'running' && sec() - updateRunStart! > 3.6 && sec() - updateRunStart! < 5.2) return fail(502, 'Bad gateway')
    return ok(info)
  }
  if (route === 'POST /api/admin/update/check') return ok(updateInfo())
  if (route === 'POST /api/admin/update') {
    updateAction = 'update'
    updateRunStart = sec()
    return ok(updateInfo())
  }
  if (route === 'POST /api/admin/update/revert') {
    if (reverted) return fail(409, "there's no previous version to roll back to")
    updateAction = 'revert'
    updateRunStart = sec()
    return ok(updateInfo())
  }
  if (route === 'PUT /api/admin/update/settings') {
    const { auto, time } = body as { auto?: boolean; time?: string }
    if (time !== undefined && !/^\d{1,2}:\d{2}$/.test(time)) return fail(400, 'time must look like 03:00')
    Object.assign(autoUpdate, { ...(auto !== undefined && { enabled: auto }), ...(time !== undefined && { time }), updated_by: { id: adam.id, name: adam.name }, updated_at: sec() })
    return ok(updateInfo())
  }
  const restart = p.match(/^\/api\/admin\/services\/([^/]+)\/restart$/)
  if (method === 'POST' && restart) {
    const svc = mockServices.find((s) => s.name === decodeURIComponent(restart[1]))
    if (!svc?.restartable) return fail(404, 'Unknown service')
    svc.since = sec()
    return ok({ name: svc.name, state: 'active' })
  }
  const logs = p.match(/^\/api\/admin\/logs\/([^/]+)$/)
  if (method === 'GET' && logs) {
    const svc = mockServices.find((s) => s.name === decodeURIComponent(logs[1]))
    if (!svc) return fail(404, 'Unknown service')
    return ok({ name: svc.name, unit: svc.unit, lines: serviceLog(svc.name), error: null })
  }
  return null
}

function handle(method: string, url: URL, body: Record<string, unknown>): readonly [number, unknown] {
  const p = url.pathname.replace(/\/$/, '')
  const route = `${method} ${p}`
  if (route === 'GET /api/app/me') return ok({ ...adam, admin: true, kind: 'slack' })
  if (p.startsWith('/api/admin/')) return handleAdmin(method, p, body) ?? fail(404, 'not found')
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
  const controlled = airplayControl(route, body)
  if (controlled) return controlled
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
  const mode: Mode = param && ['signedout', 'signedout-slack', 'signedout-google', 'writes', 'down', 'banned'].includes(param) ? (param as Mode) : param !== null ? 'full' : ((stored as Mode) ?? 'full')
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
    airplay: (on, resume = true, playing = true) => {
      airplay = on ? { at: Date.now(), pos: 74000, playing, resume } : null
      if (on) setStatus({ state: 'paused' })
    },
    quiet: (phase, idle = false) => {
      quiet = { ...quiet, phase, locked: phase === 'locked' }
      quietIdleAt = null
      if (phase === 'locked' || (phase === 'grace' && idle)) setStatus({ state: 'paused' })
      else if (phase === 'grace') setStatus({ state: 'playing' })
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
      : mode === 'banned' && url.pathname.startsWith('/api/')
        ? [403, { error: "you're banned from the music API", ban: { reason: "Queued **Never Gonna Give You Up** eleven times in a row during build season.\n\n- Skipped everyone else's songs\n- Turned the volume to max at 7am\n\nTake a few days off. See the [lab rules](https://example.com/rules) before you're back.", until: Math.floor(sec()) + 3 * 86400 + 5 * 3600, banned: Math.floor(sec()) - 3600 } }] as const
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
