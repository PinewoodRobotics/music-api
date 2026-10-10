import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { api, eventsUrl, type Queue, type RepeatMode, type Status, type Track } from '../lib/api'
import { activity } from '../lib/activity'
import { storage } from '../lib/storage'
import { useToast } from './toast'

type Clock = { status: Status | null; at: number }
type OverrideKey = 'state' | 'volume' | 'shuffle' | 'repeat'
type Override = { value: Status[OverrideKey]; until: number }

type Player = {
  status: Status | null
  at: number
  queue: Queue | null
  connected: boolean
  isPlaying: boolean
  positionAt: (now: number) => number
  togglePlay: () => void
  next: () => void
  previous: () => void
  seek: (ms: number) => void
  seekBy: (deltaMs: number) => void
  setVolume: (volume: number, final?: boolean) => void
  toggleMute: () => void
  toggleShuffle: () => void
  cycleRepeat: () => void
  start: (key: string, call: () => Promise<Status>, shuffle?: boolean) => Promise<void>
  pending: string | null
  addToQueue: (uris: string[]) => Promise<void>
  refreshQueue: () => void
  replaceQueue: (queue: Queue) => void
}

const PlayerContext = createContext<Player | null>(null)
const REPEAT_ORDER: RepeatMode[] = ['off', 'context', 'track']
const LAST_VOLUME_KEY = 'lastVolume'
const VOLUME_INTERVAL_MS = 150

const isStatus = (v: unknown): v is Status => !!v && typeof v === 'object' && 'state' in v && 'backend' in v

function positionOf(clock: Clock, now: number) {
  const s = clock.status
  if (!s) return 0
  const elapsed = s.state === 'playing' ? now - clock.at : 0
  const pos = s.position_ms + elapsed
  return s.duration_ms ? Math.min(pos, s.duration_ms) : pos
}

export function PlayerProvider({ children }: { children: ReactNode }) {
  const toast = useToast()
  const [clock, setClock] = useState<Clock>({ status: null, at: 0 })
  const [queue, setQueue] = useState<Queue | null>(null)
  const [connected, setConnected] = useState(false)
  const clockRef = useRef(clock)
  const overrides = useRef<Partial<Record<OverrideKey, Override>>>({})
  const pendingSeek = useRef<{ ms: number; at: number; until: number } | null>(null)
  const pendingTrack = useRef<{ track: Track; from: string | undefined; until: number } | null>(null)
  const [pending, setPending] = useState<string | null>(null)
  const volumeTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const queueTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  const commit = useCallback((next: Clock) => {
    clockRef.current = next
    setClock(next)
  }, [])

  const apply = useCallback(
    (incoming: Status) => {
      if (incoming.removed && clockRef.current.status) return
      const now = performance.now()
      const s = { ...incoming }
      const wall = Date.now()
      for (const key of Object.keys(overrides.current) as OverrideKey[]) {
        const o = overrides.current[key]
        if (!o) continue
        if (wall > o.until || s[key] === o.value) delete overrides.current[key]
        else Object.assign(s, { [key]: o.value })
      }
      const skip = pendingTrack.current
      if (skip) {
        if (wall > skip.until || s.track?.uri !== skip.from) pendingTrack.current = null
        else {
          s.track = skip.track
          s.duration_ms = skip.track.duration_ms
          s.position_ms = 0
        }
      }
      const seek = pendingSeek.current
      if (seek) {
        const sameTrack = clockRef.current.status?.track?.uri === s.track?.uri
        const expected = seek.ms + (s.state === 'playing' ? now - seek.at : 0)
        if (!sameTrack || wall > seek.until || Math.abs(s.position_ms - expected) < 1500) pendingSeek.current = null
        else s.position_ms = expected
      }
      commit({ status: s, at: now })
    },
    [commit],
  )

  const refreshQueue = useCallback(() => {
    if (queueTimer.current) clearTimeout(queueTimer.current)
    queueTimer.current = setTimeout(() => {
      api.queue().then(setQueue).catch(() => {})
    }, 150)
  }, [])

  const refreshStatus = useCallback(() => api.status().then(apply).catch(() => {}), [apply])

  useEffect(() => {
    let es: EventSource | null = null
    let retryIn = 1000
    let timer: ReturnType<typeof setTimeout> | undefined
    let disposed = false
    let everOpened = false

    const connect = () => {
      if (disposed) return
      es = new EventSource(eventsUrl())
      es.addEventListener('open', () => {
        setConnected(true)
        retryIn = 1000
        void (everOpened ? activity.catchUp() : activity.load()).catch(() => {})
        everOpened = true
      })
      es.addEventListener('activity', (e) => activity.receive(JSON.parse((e as MessageEvent).data)))
      es.addEventListener('status', (e) => apply(JSON.parse((e as MessageEvent).data)))
      es.addEventListener('queue', (e) => setQueue(JSON.parse((e as MessageEvent).data)))
      es.addEventListener('error', (e) => {
        if (e instanceof MessageEvent && e.data) return
        setConnected(false)
        if (es?.readyState !== EventSource.CLOSED) return
        es.close()
        timer = setTimeout(() => {
          refreshStatus()
          connect()
        }, retryIn)
        retryIn = Math.min(retryIn * 2, 15000)
      })
    }

    refreshStatus()
    refreshQueue()
    connect()
    return () => {
      disposed = true
      clearTimeout(timer)
      es?.close()
    }
  }, [apply, refreshQueue, refreshStatus])

  const optimistic = useCallback(
    (patch: Partial<Pick<Status, OverrideKey>>, ttl = 3000) => {
      const now = performance.now()
      const current = clockRef.current
      if (current.status) commit({ status: { ...current.status, ...patch, position_ms: positionOf(current, now) }, at: now })
      for (const [key, value] of Object.entries(patch) as [OverrideKey, Status[OverrideKey]][])
        overrides.current[key] = { value, until: Date.now() + ttl }
    },
    [commit],
  )

  const send = useCallback(
    async (call: () => Promise<unknown>, rollback: OverrideKey[] = []) => {
      try {
        const result = await call()
        if (isStatus(result)) apply(result)
      } catch (err) {
        for (const key of rollback) delete overrides.current[key]
        toast.error(err)
        refreshStatus()
      }
    },
    [apply, refreshStatus, toast],
  )

  const status = clock.status
  const isPlaying = status?.state === 'playing' || status?.state === 'buffering'

  const positionAt = useCallback((now: number) => positionOf(clock, now), [clock])

  const seek = useCallback(
    (ms: number) => {
      const current = clockRef.current
      const duration = current.status?.duration_ms ?? Infinity
      const target = Math.max(0, Math.min(ms, duration - 500))
      const now = performance.now()
      pendingSeek.current = { ms: target, at: now, until: Date.now() + 4000 }
      if (current.status) commit({ status: { ...current.status, position_ms: target }, at: now })
      void send(() => api.seek(target))
    },
    [commit, send],
  )

  const volumeLatest = useRef(0)
  const volumeSentAt = useRef(0)
  const volumeSentValue = useRef<number | null>(null)
  const setVolume = useCallback(
    (volume: number, final = false) => {
      const v = Math.max(0, Math.min(100, Math.round(volume)))
      volumeLatest.current = v
      overrides.current.volume = { value: v, until: Date.now() + 3000 }
      const flush = () => {
        volumeTimer.current = null
        volumeSentAt.current = Date.now()
        const latest = volumeLatest.current
        optimistic({ volume: latest })
        if (latest === volumeSentValue.current) return
        volumeSentValue.current = latest
        void send(() => api.volume(latest), ['volume'])
      }
      if (final) {
        if (volumeTimer.current) clearTimeout(volumeTimer.current)
        return flush()
      }
      const wait = VOLUME_INTERVAL_MS - (Date.now() - volumeSentAt.current)
      if (wait <= 0) flush()
      else if (!volumeTimer.current) volumeTimer.current = setTimeout(flush, wait)
    },
    [optimistic, send],
  )

  const value = useMemo<Player>(
    () => ({
      status,
      at: clock.at,
      queue,
      connected,
      isPlaying,
      positionAt,
      togglePlay: () => {
        optimistic({ state: isPlaying ? 'paused' : 'playing' })
        void send(() => (isPlaying ? api.pause() : api.play()), ['state'])
      },
      next: () => {
        const upcoming = queue?.upcoming.find((e) => e.item)?.item
        const now = performance.now()
        const current = clockRef.current.status
        if (upcoming && current) {
          pendingTrack.current = { track: upcoming, from: current.track?.uri, until: Date.now() + 4000 }
          commit({ status: { ...current, track: upcoming, duration_ms: upcoming.duration_ms, position_ms: 0 }, at: now })
        }
        void send(api.next)
      },
      previous: () => {
        const current = clockRef.current
        if (positionOf(current, performance.now()) > 3000 && current.status) {
          pendingSeek.current = { ms: 0, at: performance.now(), until: Date.now() + 3000 }
          commit({ status: { ...current.status, position_ms: 0 }, at: performance.now() })
        }
        void send(api.previous)
      },
      seek,
      seekBy: (delta) => seek(positionOf(clockRef.current, performance.now()) + delta),
      setVolume,
      toggleMute: () => {
        const v = status?.volume ?? 0
        if (v > 0) {
          storage.set(LAST_VOLUME_KEY, String(v))
          setVolume(0, true)
        } else setVolume(Number(storage.get(LAST_VOLUME_KEY)) || 50, true)
      },
      toggleShuffle: () => {
        const enabled = !status?.shuffle
        optimistic({ shuffle: enabled })
        void send(() => api.shuffle(enabled), ['shuffle'])
      },
      cycleRepeat: () => {
        const mode = REPEAT_ORDER[(REPEAT_ORDER.indexOf(status?.repeat ?? 'off') + 1) % REPEAT_ORDER.length]
        optimistic({ repeat: mode })
        void send(() => api.repeat(mode), ['repeat'])
      },
      start: async (key, call, shuffle) => {
        if (shuffle !== undefined) optimistic({ shuffle })
        setPending(key)
        await send(call)
        setPending((k) => (k === key ? null : k))
      },
      pending,
      refreshQueue,
      replaceQueue: setQueue,
      addToQueue: async (uris) => {
        try {
          await api.addToQueue(uris)
          toast.show(uris.length === 1 ? 'Added to queue' : `Added ${uris.length} songs to queue`)
          refreshQueue()
        } catch (err) {
          toast.error(err)
        }
      },
    }),
    [status, clock.at, queue, connected, isPlaying, positionAt, optimistic, send, seek, setVolume, refreshQueue, toast, commit, pending],
  )

  return <PlayerContext.Provider value={value}>{children}</PlayerContext.Provider>
}

export function usePlayer() {
  const ctx = useContext(PlayerContext)
  if (!ctx) throw new Error('usePlayer outside PlayerProvider')
  return ctx
}

export function usePosition() {
  const { positionAt, isPlaying } = usePlayer()
  const [pos, setPos] = useState(() => positionAt(performance.now()))
  useEffect(() => {
    let raf = 0
    const tick = () => {
      setPos(positionAt(performance.now()))
      if (isPlaying) raf = requestAnimationFrame(tick)
    }
    tick()
    return () => cancelAnimationFrame(raf)
  }, [positionAt, isPlaying])
  return pos
}
