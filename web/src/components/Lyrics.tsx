import { Loader2 } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { api, ApiError, type Lyrics as LyricsData } from '../lib/api'
import { usePlayer } from '../state/player'

type Loaded = { uri: string; lyrics: LyricsData | null; error: string | null }

const cache = new Map<string, Loaded>()
const inflight = new Map<string, Promise<Loaded>>()
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))

async function load(uri: string): Promise<Loaded> {
  for (let attempt = 0; attempt < 3; attempt++) {
    try {
      const lyrics = await api.lyrics()
      if (lyrics.track.uri === uri) {
        const result = { uri, lyrics, error: null }
        cache.set(uri, result)
        return result
      }
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        const result = { uri, lyrics: null, error: null }
        cache.set(uri, result)
        return result
      }
      return { uri, lyrics: null, error: err instanceof Error ? err.message : String(err) }
    }
    await sleep(1200)
  }
  return { uri, lyrics: null, error: 'track changed' }
}

function fetchLyrics(uri: string): Promise<Loaded> {
  const hit = cache.get(uri)
  if (hit) return Promise.resolve(hit)
  let request = inflight.get(uri)
  if (!request) {
    request = load(uri).finally(() => inflight.delete(uri))
    inflight.set(uri, request)
  }
  return request
}

function useLyrics(uri: string | undefined) {
  const [loaded, setLoaded] = useState<Loaded | null>(() => (uri && cache.get(uri)) || null)
  useEffect(() => {
    if (!uri) return
    let live = true
    fetchLyrics(uri).then((result) => live && setLoaded(result))
    return () => {
      live = false
    }
  }, [uri])
  return loaded?.uri === uri ? loaded : null
}

function useLineIndex(times: number[]) {
  const { positionAt, isPlaying } = usePlayer()
  const [index, setIndex] = useState(-1)
  useEffect(() => {
    let raf = 0
    const tick = () => {
      const pos = positionAt(performance.now()) + 250
      let lo = 0
      let hi = times.length - 1
      let found = -1
      while (lo <= hi) {
        const mid = (lo + hi) >> 1
        if (times[mid] <= pos) {
          found = mid
          lo = mid + 1
        } else hi = mid - 1
      }
      setIndex(found)
      if (isPlaying) raf = requestAnimationFrame(tick)
    }
    tick()
    return () => cancelAnimationFrame(raf)
  }, [times, positionAt, isPlaying])
  return index
}

type LyricsSize = 'sm' | 'lg' | 'immersive'

export function Lyrics({ size = 'sm' }: { size?: LyricsSize }) {
  const { status } = usePlayer()
  const track = status?.track
  const loaded = useLyrics(track?.type === 'track' ? track.uri : undefined)

  const message = (text: string) => (
    <div className="grid h-full place-items-center p-8 text-center">
      <p className={`${size === 'sm' ? 'text-sm' : 'text-lg'} text-white/60`}>{text}</p>
    </div>
  )

  if (!track) return message('Play a song to see its lyrics.')
  if (track.type !== 'track') return message('Lyrics are only available for songs.')
  if (!loaded)
    return (
      <div className="grid h-full place-items-center">
        <Loader2 className="size-6 animate-spin text-white/50" />
      </div>
    )
  if (loaded.error) return message("Couldn't load lyrics. Try again in a moment.")
  const lyrics = loaded.lyrics
  if (!lyrics) return message("No lyrics for this song.")
  if (lyrics.instrumental) return message('This song is instrumental.')
  if (lyrics.synced.length) return <SyncedLyrics key={track.uri} lines={lyrics.synced} size={size} />
  if (lyrics.plain)
    return (
      <div className="scroll-thin h-full overflow-y-auto px-6 py-8">
        <p className={`whitespace-pre-line font-display font-bold leading-snug text-white/80 ${size === 'sm' ? 'text-lg' : 'text-2xl'}`}>
          {lyrics.plain}
        </p>
      </div>
    )
  return message('No lyrics for this song.')
}

function SyncedLyrics({ lines, size }: { lines: LyricsData['synced']; size: LyricsSize }) {
  const { seek } = usePlayer()
  const [times] = useState(() => lines.map((l) => l.time_ms))
  const index = useLineIndex(times)
  const container = useRef<HTMLDivElement>(null)
  const userScrollUntil = useRef(0)
  const first = useRef(true)

  useEffect(() => {
    const box = container.current
    if (!box || Date.now() < userScrollUntil.current) return
    const el = box.querySelector<HTMLElement>(`[data-line="${Math.max(0, index)}"]`)
    if (!el) return
    box.scrollTo({ top: el.offsetTop - box.clientHeight * 0.36, behavior: first.current ? 'auto' : 'smooth' })
    first.current = false
  }, [index])

  const [browsing, setBrowsing] = useState(false)
  const browseTimer = useRef<ReturnType<typeof setTimeout>>(undefined)
  const pauseAutoScroll = () => {
    userScrollUntil.current = Date.now() + 4000
    setBrowsing(true)
    clearTimeout(browseTimer.current)
    browseTimer.current = setTimeout(() => setBrowsing(false), 4000)
  }
  useEffect(() => () => clearTimeout(browseTimer.current), [])

  const immersive = size === 'immersive'
  const text = immersive
    ? 'text-[clamp(1.7rem,2.9vw,2.9rem)] leading-[1.18] font-extrabold'
    : size === 'lg'
      ? 'text-[clamp(1.5rem,2.4vw,2.25rem)] leading-[1.25] font-bold'
      : 'text-xl leading-snug font-bold'
  const pad = immersive ? 'px-1' : size === 'lg' ? 'px-2' : 'px-5'
  const lineStyle = (i: number) => {
    if (!immersive || browsing || i === index) return undefined
    const distance = i - index
    const blur = distance > 0 ? Math.min(3.5, distance * 0.75) : 1.2
    return { filter: `blur(${blur}px)` }
  }

  return (
    <div
      ref={container}
      onWheel={pauseAutoScroll}
      onTouchMove={pauseAutoScroll}
      className={`no-scrollbar mask-fade-y relative h-full overflow-y-auto overscroll-contain ${pad}`}
    >
      <div className="h-[34%]" aria-hidden />
      {lines.map((line, i) => {
        const state = i === index ? 'now' : i < index ? 'past' : 'future'
        return (
          <button
            key={i}
            type="button"
            data-line={i}
            onClick={() => seek(line.time_ms)}
            style={lineStyle(i)}
            className={`block w-full origin-left text-left font-display tracking-tight transition-[color,opacity,transform,filter] duration-500 ${immersive ? 'py-2.5' : 'py-2'} ${text} ${
              state === 'now'
                ? 'text-white'
                : state === 'past'
                  ? `${immersive ? 'text-white/35' : 'text-white/30'} hover:text-white/70`
                  : `${immersive ? 'text-white/45' : 'text-white/40'} hover:text-white/70`
            } ${state === 'now' && size !== 'sm' ? 'scale-[1.02]' : ''}`}
          >
            {line.text || <span aria-label="Instrumental break" className="tracking-[0.25em]">•••</span>}
          </button>
        )
      })}
      <div className="h-[60%]" aria-hidden />
    </div>
  )
}
