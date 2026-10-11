import { Airplay, ChevronUp, ListMusic, Maximize2, MicVocal, SkipForward } from 'lucide-react'
import { byline } from '../lib/format'
import { airplayFrom, allowed } from '../lib/playback'
import { usePlayer, usePosition } from '../state/player'
import { useUI } from '../state/ui'
import { Artwork } from './Artwork'
import { CreditOrSkip, SkipNote } from './SkipNote'
import { useSkipNote } from '../lib/skipNote'
import { IconButton } from './IconButton'
import { PlayButton, SeekBar, Transport, VolumeControl } from './PlayerControls'

export function NowPlayingBar() {
  return (
    <>
      <DesktopBar />
      <MiniPlayer />
    </>
  )
}

function DesktopBar() {
  const { status } = usePlayer()
  const { setExpanded, panel, showPanel } = useUI()
  const track = status?.track
  return (
    <footer className="hidden h-[88px] shrink-0 grid-cols-[minmax(0,1fr)_minmax(0,1.7fr)_minmax(0,1fr)] items-center gap-4 px-4 md:grid">
      <div className="flex min-w-0 items-center">
        <button
          type="button"
          onClick={() => setExpanded(true)}
          disabled={!track}
          className="group flex min-w-0 items-center gap-3.5 rounded-md p-1 pr-3 text-left"
          aria-label="Open Now Playing"
        >
          <div className="relative shrink-0">
            <Artwork src={track?.artwork} className="size-14 shadow-lg shadow-black/40" />
            {track && (
              <span className="absolute right-1 top-1 grid size-6 place-items-center rounded-full bg-black/70 opacity-0 transition-opacity group-hover:opacity-100">
                <ChevronUp className="size-4" />
              </span>
            )}
          </div>
          <div className="min-w-0">
            <div className="truncate text-sm font-medium text-fg group-hover:underline">{track?.name ?? 'Nothing playing'}</div>
            <div className="truncate text-xs text-dim">{track ? byline(track) : status?.device?.name ?? 'Lab Speakers'}</div>
            {track?.type === 'airplay' ? (
              <div className="mt-1 flex min-w-0 items-center gap-1 text-[11px] text-faint">
                <Airplay className="size-3 shrink-0" aria-hidden />
                <span className="truncate">{airplayFrom(status?.airplay?.sender)}</span>
              </div>
            ) : (
              track && <CreditOrSkip credit={status?.credit} className="mt-1 text-[11px] text-faint" />
            )}
          </div>
        </button>
      </div>
      <div className="mx-auto flex w-full max-w-[680px] flex-col gap-1">
        <Transport />
        <SeekBar />
      </div>
      <div className="flex items-center justify-end gap-1">
        <IconButton label="Lyrics" active={panel === 'lyrics'} onClick={() => showPanel('lyrics')}>
          <MicVocal className="size-[18px]" />
        </IconButton>
        <IconButton label="Up next" active={panel === 'queue'} onClick={() => showPanel('queue')}>
          <ListMusic className="size-[18px]" />
        </IconButton>
        <VolumeControl className="w-36" />
        <IconButton label="Open Now Playing" onClick={() => setExpanded(true)} disabled={!track}>
          <Maximize2 className="size-4" />
        </IconButton>
      </div>
    </footer>
  )
}

function MiniProgress() {
  const { status } = usePlayer()
  const position = usePosition()
  const duration = status?.duration_ms ?? status?.track?.duration_ms ?? 0
  const pct = duration ? Math.min(100, (position / duration) * 100) : 0
  return (
    <div className="absolute inset-x-2 bottom-0 h-[2px] overflow-hidden rounded-full bg-white/20">
      <div className="h-full bg-white" style={{ width: `${pct}%` }} />
    </div>
  )
}

function MiniPlayer() {
  const { status, next } = usePlayer()
  const { setExpanded } = useUI()
  const track = status?.track
  if (!track) return null
  const canSkip = allowed(status, 'skip_next')
  return (
    <div className="px-2 pb-1.5 md:hidden">
      <div className="relative flex h-16 items-center overflow-hidden rounded-xl bg-glow shadow-lg shadow-black/50 transition-colors">
        <button
          type="button"
          onClick={() => setExpanded(true)}
          aria-label="Open Now Playing"
          className="flex h-full min-w-0 flex-1 items-center gap-3 pl-2 text-left active:opacity-70"
        >
          <Artwork src={track.artwork} className="size-12 shrink-0 rounded-md" />
          <div className="min-w-0">
            <div className="truncate text-[15px] font-semibold leading-tight">{track.name}</div>
            <MiniSubtitle text={track.type === 'airplay' ? airplayFrom(status.airplay?.sender) : byline(track)} />
          </div>
        </button>
        <PlayButton size="mini" />
        <button
          type="button"
          onClick={next}
          disabled={!canSkip}
          aria-label="Next"
          className="mr-1 grid size-11 shrink-0 place-items-center text-fg transition active:scale-90 disabled:opacity-35"
        >
          <SkipForward className="size-6 fill-current" />
        </button>
        <MiniProgress />
      </div>
    </div>
  )
}

function MiniSubtitle({ text }: { text: string }) {
  const note = useSkipNote()
  if (note) return <SkipNote className="text-[13px] text-white/80" />
  return <div className="truncate text-[13px] text-white/70">{text}</div>
}
