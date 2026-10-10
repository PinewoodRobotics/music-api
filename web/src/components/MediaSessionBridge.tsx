import { useEffect, useReducer, useRef } from 'react'
import { withClientOrigin, type Track } from '../lib/api'
import { byline } from '../lib/format'
import { mediaSessionSupported, nowPlayingSync, useSyncState } from '../lib/nowPlayingSync'
import { usePlayer } from '../state/player'

const SEEK_STEP_S = 10
const ECHO_WINDOW_MS = 1000
const RATE_LIMIT_MS = { skip: 1500, seek: 1000 }
const SPOTIFY_SIZES: [string, string][] = [
  ['ab67616d00004851', '64x64'],
  ['ab67616d00001e02', '300x300'],
  ['ab67616d0000b273', '640x640'],
]
const ACTIONS: MediaSessionAction[] = ['play', 'pause', 'stop', 'previoustrack', 'nexttrack', 'seekto', 'seekbackward', 'seekforward']

function setHandler(action: MediaSessionAction, handler: MediaSessionActionHandler | null) {
  try {
    navigator.mediaSession.setActionHandler(action, handler)
  } catch {
    return
  }
}

function artworkFor(url: string | null): MediaImage[] {
  if (!url) return []
  const absolute = new URL(url, location.href).href
  const variant = SPOTIFY_SIZES.find(([hash]) => absolute.includes(hash))
  if (!variant) return [{ src: absolute, sizes: '640x640', type: 'image/jpeg' }]
  return SPOTIFY_SIZES.map(([hash, sizes]) => ({ src: absolute.replace(variant[0], hash), sizes, type: 'image/jpeg' }))
}

function metadataFor(track: Track) {
  return new MediaMetadata({
    title: track.name,
    artist: byline(track),
    album: track.album?.name ?? '',
    artwork: artworkFor(track.artwork),
  })
}

export function MediaSessionBridge() {
  const { state: sync } = useSyncState()
  const player = usePlayer()
  const latest = useRef(player)
  latest.current = player
  const [wakeups, resync] = useReducer((n: number) => n + 1, 0)
  const enabled = mediaSessionSupported && sync !== 'off'
  const { status, isPlaying, positionAt } = player
  const track = status?.track ?? null

  useEffect(() => {
    if (!enabled) return
    const p = () => latest.current
    const lastSent = { skip: 0, seek: 0 }
    const guarded =
      (action: MediaSessionAction, kind: keyof typeof lastSent | null, run: (d: MediaSessionActionDetails) => void): MediaSessionActionHandler =>
      (details) => {
        const now = performance.now()
        if (nowPlayingSync.ownOperationWithin(ECHO_WINDOW_MS)) return
        if (kind && now - lastSent[kind] < RATE_LIMIT_MS[kind]) return
        if (kind) lastSent[kind] = now
        withClientOrigin(`media-session:${action}`, () => run(details))
      }
    const seekTo = (ms: number) => {
      if (Math.abs(p().positionAt(performance.now()) - ms) >= 1000) p().seek(ms)
    }
    const handlers: Record<string, MediaSessionActionHandler> = {
      play: guarded('play', null, () => !p().isPlaying && p().togglePlay()),
      pause: guarded('pause', null, () => p().isPlaying && p().togglePlay()),
      stop: guarded('stop', null, () => p().isPlaying && p().togglePlay()),
      nexttrack: guarded('nexttrack', 'skip', () => p().next()),
      previoustrack: guarded('previoustrack', 'skip', () => p().previous()),
      seekto: guarded('seekto', 'seek', (d) => d.seekTime != null && seekTo(d.seekTime * 1000)),
      seekforward: guarded('seekforward', 'seek', (d) => p().seekBy((d.seekOffset ?? SEEK_STEP_S) * 1000)),
      seekbackward: guarded('seekbackward', 'seek', (d) => p().seekBy(-(d.seekOffset ?? SEEK_STEP_S) * 1000)),
    }
    const register = () => {
      const current = p().status?.track
      if (current) navigator.mediaSession.metadata = metadataFor(current)
      ACTIONS.forEach((action) => setHandler(action, handlers[action]))
      navigator.mediaSession.playbackState = current ? (p().isPlaying ? 'playing' : 'paused') : 'none'
    }
    register()
    const stopListening = nowPlayingSync.onPlaying(register)
    const onVisible = () => document.visibilityState === 'visible' && resync()
    document.addEventListener('visibilitychange', onVisible)
    return () => {
      stopListening()
      document.removeEventListener('visibilitychange', onVisible)
      ACTIONS.forEach((action) => setHandler(action, null))
      navigator.mediaSession.metadata = null
      navigator.mediaSession.playbackState = 'none'
    }
  }, [enabled])

  const trackKey = track?.uri
  useEffect(() => {
    if (!enabled) return
    const current = latest.current.status?.track
    navigator.mediaSession.metadata = current ? metadataFor(current) : null
  }, [enabled, trackKey])

  useEffect(() => {
    if (!enabled) return
    navigator.mediaSession.playbackState = track ? (isPlaying ? 'playing' : 'paused') : 'none'
  }, [enabled, isPlaying, track, sync, wakeups])

  useEffect(() => {
    if (!track) return nowPlayingSync.sync(null)
    const durationMs = status?.duration_ms ?? track.duration_ms
    const positionMs = Math.min(Math.max(0, positionAt(performance.now())), durationMs)
    nowPlayingSync.sync({ key: track.uri, durationMs, positionMs, playing: isPlaying })
    if (!enabled || !navigator.mediaSession.setPositionState || !(durationMs > 0)) return
    try {
      navigator.mediaSession.setPositionState({ duration: durationMs / 1000, position: positionMs / 1000, playbackRate: 1 })
    } catch {
      return
    }
  }, [enabled, sync, track, status?.duration_ms, positionAt, isPlaying, wakeups])

  return null
}
