import { Download, ListEnd, ListPlus, MoreHorizontal, Play } from 'lucide-react'
import { useEffect, useState, type MouseEvent } from 'react'
import { api, ApiError, type Resolved, type ResolvedTrack, type Track } from '../../lib/api'
import { formatTime, idFromUri, plural } from '../../lib/format'
import type { DetectedLink } from '../../lib/links'
import { useElapsed } from '../../lib/useElapsed'
import { Artwork } from '../../components/Artwork'
import { BigPlayButton } from '../../components/CollectionHeader'
import { Button } from '../../components/Modal'
import { pointRect, type AnchorRect } from '../../components/Popover'
import { RowsSkeleton } from '../../components/Skeleton'
import { SourceIcon } from '../../components/SourceIcon'
import { TrackMenu } from '../../components/TrackMenu'
import { usePlayer } from '../../state/player'
import { useUI } from '../../state/ui'
import { ErrorState, Message } from '../Message'

const SOURCE = { spotify: 'Spotify', apple: 'Apple Music' }
const NOUN = { track: 'song', album: 'album', playlist: 'playlist' }

function toTrack(t: ResolvedTrack & { uri: string }): Track {
  return {
    uri: t.uri,
    id: idFromUri(t.uri),
    type: 'track',
    name: t.name,
    artists: t.artists.map((name) => ({ uri: '', name })),
    album: null,
    duration_ms: t.duration_ms,
    artwork: t.artwork,
  }
}

const isMatched = (t: ResolvedTrack): t is ResolvedTrack & { uri: string } => !!t.uri

type ResolveState = { url: string; data: Resolved | null; error: unknown }

const resolved = new Map<string, Promise<ResolveState>>()

function resolveOnce(url: string) {
  let request = resolved.get(url)
  if (!request) {
    request = api.resolve(url).then(
      (data) => ({ url, data, error: null }),
      (err) => {
        resolved.delete(url)
        return { url, data: null, error: err }
      },
    )
    resolved.set(url, request)
  }
  return request
}

function useResolve(url: string) {
  const [state, setState] = useState<ResolveState | null>(null)
  const [attempt, setAttempt] = useState(0)
  useEffect(() => {
    let live = true
    setState(null)
    resolveOnce(url).then((result) => live && setState(result))
    return () => {
      live = false
    }
  }, [url, attempt])
  return { state: state?.url === url ? state : null, retry: () => setAttempt((n) => n + 1) }
}

function Resolving({ link }: { link: DetectedLink }) {
  const seconds = useElapsed(true)
  const slow = link.source === 'apple' && (link.kind === 'playlist' || link.kind === 'album')
  return (
    <div className="px-3 max-sm:px-2">
      <div className="flex items-center gap-6 rounded-lg bg-white/[0.04] p-5 max-sm:flex-col max-sm:items-start">
        <div className="grid size-32 shrink-0 animate-pulse place-items-center rounded-[6px] bg-white/[0.07]">
          <SourceIcon source={link.source} className="size-10" />
        </div>
        <div className="w-full min-w-0 flex-1 space-y-3" aria-live="polite">
          <p className="text-sm font-medium text-dim">{link.label}</p>
          <p className="font-display text-2xl font-bold tracking-tight">
            {slow ? 'Matching songs from Apple Music…' : `Looking up this ${link.label}…`}
          </p>
          <div className="h-1 max-w-md overflow-hidden rounded-full bg-white/10">
            <div className="h-full w-1/3 animate-[indeterminate_1.2s_ease-in-out_infinite] rounded-full bg-accent" />
          </div>
          <p className="text-xs text-dim tabular">
            {slow ? 'Playlists can take up to 30 seconds. ' : ''}
            {seconds}s
          </p>
        </div>
      </div>
      <div className="mt-6">
        <RowsSkeleton count={6} />
      </div>
    </div>
  )
}

function Header({ data }: { data: Resolved }) {
  const { status, isPlaying, togglePlay, start, pending, addToQueue } = usePlayer()
  const { openDialog } = useUI()
  const [menu, setMenu] = useState<AnchorRect | null>(null)
  const first = data.tracks.find(isMatched)
  const playUri = data.kind === 'track' ? (data.spotify_uri ?? first?.uri ?? null) : data.spotify_uri
  const current = !!playUri && (data.kind === 'track' ? status?.track?.uri === playUri : status?.context?.uri === playUri)
  const missing = data.total - data.matched
  const stats =
    data.kind === 'track'
      ? playUri
        ? null
        : 'Not on Spotify'
      : missing > 0
        ? `${data.matched.toLocaleString()} of ${plural(data.total, 'song')} found on Spotify`
        : plural(data.total, 'song')

  return (
    <div className="relative flex items-end gap-6 rounded-lg bg-white/[0.04] p-5 max-sm:flex-col max-sm:items-start">
      <Artwork src={data.artwork} className="size-[clamp(128px,14vw,176px)] shrink-0 shadow-[0_12px_32px_rgba(0,0,0,0.5)]" />
      <div className="min-w-0 flex-1">
        <p className="flex items-center gap-2 text-sm font-medium text-white/80">
          <SourceIcon source={data.source} className="size-4" />
          {SOURCE[data.source]} {NOUN[data.kind]}
        </p>
        <h2 className="mt-2 line-clamp-2 font-display text-[clamp(1.75rem,3.4vw,2.75rem)] font-extrabold leading-tight tracking-tight">
          {data.name}
        </h2>
        <p className="mt-1 truncate text-white/70">
          {data.subtitle}
          {stats && <span className={data.kind === 'track' ? 'ml-2 text-danger' : 'ml-2 text-white/55'}>{stats}</span>}
        </p>
        {data.truncated && <p className="mt-1 text-xs text-dim">Showing the first {plural(data.tracks.length, 'song')}.</p>}
        <div className="mt-5 flex flex-wrap items-center gap-3">
          {playUri && (
            <BigPlayButton
              playing={current && isPlaying}
              pending={pending === 'link:play'}
              label={current && isPlaying ? 'Pause' : `Play ${data.name}`}
              onClick={() => (current ? togglePlay() : void start('link:play', () => api.play({ uri: playUri, shuffle: false }), false))}
            />
          )}
          {data.kind === 'track' && playUri && (
            <>
              <Button variant="ghost" className="ring-1 ring-white/20" onClick={() => void addToQueue([playUri])}>
                <ListEnd className="size-4" />
                Add to queue
              </Button>
              <Button variant="ghost" className="ring-1 ring-white/20" onClick={(e) => setMenu(e.currentTarget.getBoundingClientRect())}>
                <ListPlus className="size-4" />
                Add to playlist
              </Button>
            </>
          )}
          {data.kind !== 'track' && (
            <Button variant={playUri ? 'ghost' : 'primary'} className={playUri ? 'ring-1 ring-white/20' : ''} onClick={() => openDialog({ kind: 'import', url: data.url })}>
              <Download className="size-4" />
              Import as playlist
            </Button>
          )}
        </div>
      </div>
      {menu && first && (
        <TrackMenu
          track={{ ...toTrack(first), uri: playUri ?? first.uri, name: data.name }}
          anchor={menu}
          initialView="playlists"
          onClose={() => setMenu(null)}
        />
      )}
    </div>
  )
}

function Tracks({ data }: { data: Resolved }) {
  const { status, start, pending } = usePlayer()
  const [menu, setMenu] = useState<{ track: Track; anchor: AnchorRect; align: 'start' | 'end' } | null>(null)
  const context = data.kind !== 'track' && data.source === 'spotify' ? data.spotify_uri : null

  const play = (t: ResolvedTrack & { uri: string }, i: number) =>
    void start(`link#${i}`, () => (context ? api.play({ context, offset: t.uri }) : api.play({ uri: t.uri })))

  const openMenu = (t: ResolvedTrack & { uri: string }, e: MouseEvent, fromButton: boolean) => {
    e.preventDefault()
    e.stopPropagation()
    const anchor = fromButton ? (e.currentTarget as HTMLElement).getBoundingClientRect() : pointRect(e.clientX, e.clientY)
    setMenu({ track: toTrack(t), anchor, align: fromButton ? 'end' : 'start' })
  }

  return (
    <div className="mt-6" role="table">
      {data.tracks.map((t, i) => {
        if (!isMatched(t))
          return (
            <div key={i} role="row" className="grid h-14 grid-cols-[2rem_minmax(0,1fr)_auto_3.5rem_2rem] items-center gap-4 px-4 opacity-45 max-md:grid-cols-[minmax(0,1fr)_auto] max-md:px-2">
              <span className="text-right text-sm text-dim tabular max-md:hidden">{i + 1}</span>
              <div className="flex min-w-0 items-center gap-3">
                <Artwork src={t.artwork} className="size-10 shrink-0 rounded-[4px] grayscale" />
                <div className="min-w-0">
                  <div className="truncate text-[15px]">{t.name}</div>
                  <div className="truncate text-[13px] text-dim">{t.artists.join(', ')}</div>
                </div>
              </div>
              <span className="rounded-full bg-white/10 px-2 py-0.5 text-[11px] font-medium text-dim">Not on Spotify</span>
              <span className="text-right text-sm text-dim tabular max-md:hidden">{formatTime(t.duration_ms)}</span>
              <span className="max-md:hidden" />
            </div>
          )
        const current = status?.track?.uri === t.uri
        return (
          <div
            key={i}
            role="row"
            tabIndex={0}
            onDoubleClick={() => play(t, i)}
            onKeyDown={(e) => e.key === 'Enter' && play(t, i)}
            onContextMenu={(e) => openMenu(t, e, false)}
            className="group grid h-14 grid-cols-[2rem_minmax(0,1fr)_minmax(0,0.8fr)_3.5rem_2rem] items-center gap-4 rounded-md px-4 outline-none hover:bg-white/[0.05] focus-visible:bg-white/[0.07] max-md:grid-cols-[minmax(0,1fr)_2.75rem_2rem] max-md:gap-2 max-md:px-2"
          >
            <div className="relative flex justify-end text-sm text-dim tabular max-md:hidden">
              <span className="group-hover:invisible">{i + 1}</span>
              <button
                type="button"
                aria-label={`Play ${t.name}`}
                onClick={() => play(t, i)}
                className="invisible absolute -right-1 top-1/2 grid size-7 -translate-y-1/2 place-items-center text-fg group-hover:visible"
              >
                <Play className="size-4 fill-current" strokeWidth={0} />
              </button>
            </div>
            <button type="button" onClick={() => play(t, i)} className="flex min-w-0 items-center gap-3 text-left md:pointer-events-none">
              <div className="relative shrink-0">
                <Artwork src={t.artwork} className="size-10 rounded-[4px]" />
                {pending === `link#${i}` && <span className="absolute inset-0 animate-pulse rounded-[4px] bg-black/50" />}
              </div>
              <div className="min-w-0">
                <div className={`truncate text-[15px] ${current ? 'text-accent' : ''}`}>{t.name}</div>
                <div className="truncate text-[13px] text-dim">{t.artists.join(', ')}</div>
              </div>
            </button>
            <div className="truncate text-sm text-dim max-md:hidden">{t.album}</div>
            <div className="text-right text-sm text-dim tabular max-md:text-xs">{formatTime(t.duration_ms)}</div>
            <button
              type="button"
              aria-label={`More options for ${t.name}`}
              onClick={(e) => openMenu(t, e, true)}
              className="grid size-8 place-items-center rounded-full text-dim hover:text-fg active:bg-white/10 md:invisible md:group-hover:visible md:group-focus-within:visible [@media(hover:none)]:visible [@media(hover:none)]:size-11"
            >
              <MoreHorizontal className="size-5" />
            </button>
          </div>
        )
      })}
      {menu && <TrackMenu track={menu.track} anchor={menu.anchor} align={menu.align} onClose={() => setMenu(null)} />}
    </div>
  )
}

export function LinkResult({ url, link }: { url: string; link: DetectedLink }) {
  const { state, retry } = useResolve(url)
  if (!state) return <Resolving link={link} />
  if (!state.data) {
    const permanent = state.error instanceof ApiError && state.error.status >= 400 && state.error.status < 500
    if (permanent) return <Message title="Couldn't open this link" body={state.error instanceof Error ? state.error.message : undefined} />
    return <ErrorState title="Couldn't open this link" error={state.error} onRetry={retry} />
  }
  return (
    <div className="px-3 max-sm:px-2">
      <Header data={state.data} />
      {state.data.kind !== 'track' && <Tracks data={state.data} />}
    </div>
  )
}
