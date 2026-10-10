import { Clock3, Disc3, ListMusic, Loader2, MoreHorizontal, Music2, Play } from 'lucide-react'
import { useCallback, useEffect, useLayoutEffect, useRef, useState, type MouseEvent, type RefObject } from 'react'
import { api, type LibrarySong, type SongSort, type Track } from '../../lib/api'
import { isTouch } from '../../lib/device'
import { byline, formatTime, idFromUri } from '../../lib/format'
import { ErrorState, Message } from '../../pages/Message'
import { usePlayer } from '../../state/player'
import { Artwork } from '../Artwork'
import { Equalizer } from '../Equalizer'
import { Link } from '../Link'
import { pointRect, type AnchorRect } from '../Popover'
import { RowsSkeleton } from '../Skeleton'
import { TrackMenu } from '../TrackMenu'

const ROW = 56
const PAGE = 100
const OVERSCAN = 8
const GRID = 'grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)_minmax(0,1fr)_3.5rem_2.5rem] max-md:grid-cols-[minmax(0,1fr)_2.75rem_2.5rem]'

function useSongs(q: string, sort: SongSort) {
  const [items, setItems] = useState<LibrarySong[]>([])
  const [total, setTotal] = useState<number | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [attempt, setAttempt] = useState(0)
  const loading = useRef(false)
  const generation = useRef(0)

  const fetchPage = useCallback(
    async (offset: number, gen: number) => {
      loading.current = true
      try {
        const page = await api.librarySongs({ q, sort, offset, limit: PAGE })
        if (gen !== generation.current) return
        setItems((list) => (offset === 0 ? page.items : [...list, ...page.items]))
        setTotal(page.total)
      } catch (err) {
        if (gen === generation.current) setError(err)
      } finally {
        if (gen === generation.current) loading.current = false
      }
    },
    [q, sort],
  )

  useEffect(() => {
    const gen = ++generation.current
    setItems([])
    setTotal(null)
    setError(null)
    void fetchPage(0, gen)
  }, [fetchPage, attempt])

  const ensure = useCallback(
    (index: number) => {
      if (loading.current || total === null || items.length >= total || index < items.length - 20) return
      void fetchPage(items.length, generation.current)
    },
    [fetchPage, items.length, total],
  )

  return { items, total, error, ensure, retry: () => setAttempt((n) => n + 1) }
}

function useWindow(container: RefObject<HTMLDivElement | null>, count: number) {
  const [range, setRange] = useState({ start: 0, end: 30 })
  useLayoutEffect(() => {
    const el = container.current
    const scroller = el?.closest('main')
    if (!el || !scroller) return
    const update = () => {
      const top = el.getBoundingClientRect().top - scroller.getBoundingClientRect().top + scroller.scrollTop
      const first = Math.floor((scroller.scrollTop - top) / ROW)
      const start = Math.max(0, first - OVERSCAN)
      const end = Math.min(count, first + Math.ceil(scroller.clientHeight / ROW) + OVERSCAN)
      setRange((r) => (r.start === start && r.end === end ? r : { start, end }))
    }
    update()
    scroller.addEventListener('scroll', update, { passive: true })
    window.addEventListener('resize', update)
    return () => {
      scroller.removeEventListener('scroll', update)
      window.removeEventListener('resize', update)
    }
  }, [container, count])
  return range
}

function SourceChips({ song }: { song: LibrarySong }) {
  const shown = song.sources.slice(0, 2)
  const extra = song.sources.length - shown.length
  return (
    <div className="flex min-w-0 items-center gap-1.5 max-md:hidden">
      {shown.map((s) => (
        <Link
          key={`${s.kind}:${s.id}`}
          href={s.kind === 'album' ? `/album/${s.id}` : `/playlist/${s.id}`}
          onClick={(e) => e.stopPropagation()}
          title={`From ${s.kind} ${s.name}`}
          className="inline-flex min-w-0 max-w-[11rem] items-center gap-1 rounded-full bg-white/[0.07] px-2 py-0.5 text-xs text-dim hover:bg-white/[0.12] hover:text-fg"
        >
          {s.kind === 'album' ? <Disc3 className="size-3 shrink-0" /> : <ListMusic className="size-3 shrink-0" />}
          <span className="truncate">{s.name}</span>
        </Link>
      ))}
      {extra > 0 && <span className="text-xs text-faint">+{extra}</span>}
    </div>
  )
}

export function SongsView({ q, sort }: { q: string; sort: SongSort }) {
  const { items, total, error, ensure, retry } = useSongs(q, sort)
  const { status, isPlaying, start, pending } = usePlayer()
  const container = useRef<HTMLDivElement>(null)
  const count = total ?? 0
  const { start: first, end } = useWindow(container, count)
  const [menu, setMenu] = useState<{ track: Track; anchor: AnchorRect; align: 'start' | 'end' } | null>(null)

  useEffect(() => ensure(end), [end, ensure])

  if (error) return <ErrorState title="Couldn't load your songs" error={error} onRetry={retry} />
  if (total === null)
    return (
      <div className="px-3">
        <RowsSkeleton count={10} />
      </div>
    )
  if (total === 0)
    return (
      <Message
        icon={<Music2 className="size-10" />}
        title={q ? `No songs match “${q}”` : 'No songs yet'}
        body={q ? 'Try a different search.' : 'Songs from the Library’s playlists and albums show up here.'}
      />
    )

  const play = (index: number) => {
    const song = items[index]
    if (song) void start(`songs#${index}`, () => api.playLibrarySongs({ uri: song.uri, sort, q: q || undefined }))
  }
  const openMenu = (track: Track, e: MouseEvent, fromButton: boolean) => {
    e.preventDefault()
    e.stopPropagation()
    const anchor = fromButton ? (e.currentTarget as HTMLElement).getBoundingClientRect() : pointRect(e.clientX, e.clientY)
    setMenu({ track, anchor, align: fromButton ? 'end' : 'start' })
  }

  const rows = []
  for (let i = first; i < Math.min(end, count); i++) {
    const song = items[i]
    const top = i * ROW
    if (!song) {
      rows.push(
        <div key={`p${i}`} className="absolute inset-x-0 flex h-14 items-center gap-3 px-4" style={{ transform: `translateY(${top}px)` }}>
          <div className="size-10 animate-pulse rounded-[4px] bg-white/[0.06]" />
          <div className="h-3 w-48 animate-pulse rounded bg-white/[0.06]" />
        </div>,
      )
      continue
    }
    const track = song
    const current = status?.track?.uri === track.uri
    const starting = pending === `songs#${i}`
    rows.push(
      <div
        key={`${track.uri}-${i}`}
        role="row"
        tabIndex={0}
        onClick={() => isTouch() && play(i)}
        onDoubleClick={() => play(i)}
        onKeyDown={(e) => e.key === 'Enter' && play(i)}
        onContextMenu={(e) => openMenu(track, e, false)}
        style={{ transform: `translateY(${top}px)` }}
        className={`group absolute inset-x-0 grid h-14 items-center gap-4 rounded-md px-4 outline-none hover:bg-white/[0.05] focus-visible:bg-white/[0.07] active:bg-white/[0.08] max-md:gap-1 max-md:px-2 ${GRID}`}
      >
        <div className="flex min-w-0 items-center gap-3">
          <div className="relative shrink-0">
            <Artwork src={track.artwork} className="size-10 rounded-[4px]" />
            <button
              type="button"
              aria-label={`Play ${track.name}`}
              onClick={(e) => {
                e.stopPropagation()
                play(i)
              }}
              className={`absolute inset-0 grid place-items-center rounded-[4px] bg-black/55 ${starting || current ? '' : 'opacity-0 group-hover:opacity-100'}`}
            >
              {starting ? <Loader2 className="size-4 animate-spin" /> : current ? <Equalizer playing={isPlaying} /> : <Play className="size-4 fill-current" strokeWidth={0} />}
            </button>
          </div>
          <div className="min-w-0">
            <div className={`truncate text-[15px] leading-tight ${current ? 'text-accent' : ''}`}>{track.name}</div>
            <div className="truncate text-[13px] text-dim">{byline(track)}</div>
          </div>
        </div>
        <div className="min-w-0 truncate text-sm text-dim max-md:hidden">
          {track.album && (
            <Link href={`/album/${idFromUri(track.album.uri)}`} onClick={(e) => e.stopPropagation()} className="hover:text-fg hover:underline">
              {track.album.name}
            </Link>
          )}
        </div>
        <SourceChips song={song} />
        <div className="text-right text-sm text-dim tabular max-md:text-xs">{formatTime(track.duration_ms)}</div>
        <button
          type="button"
          aria-label={`More options for ${track.name}`}
          onClick={(e) => openMenu(track, e, true)}
          onDoubleClick={(e) => e.stopPropagation()}
          className="grid size-9 place-items-center rounded-full text-dim hover:text-fg active:bg-white/10 md:invisible md:group-hover:visible [@media(hover:none)]:visible"
        >
          <MoreHorizontal className="size-5" />
        </button>
      </div>,
    )
  }

  return (
    <div className="px-3 pb-10 max-sm:px-1">
      <div className={`mb-2 grid items-center gap-4 border-b border-white/[0.07] px-4 pb-2 text-xs text-dim max-md:hidden ${GRID}`}>
        <span>Title</span>
        <span>Album</span>
        <span>From</span>
        <span className="flex justify-end">
          <Clock3 className="size-4" aria-label="Duration" />
        </span>
        <span />
      </div>
      <div ref={container} role="table" aria-rowcount={count} className="relative select-none" style={{ height: count * ROW }}>
        {rows}
      </div>
      {menu && <TrackMenu track={menu.track} anchor={menu.anchor} align={menu.align} onClose={() => setMenu(null)} />}
    </div>
  )
}
