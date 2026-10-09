import { ChevronUp, ListMusic, Maximize2, MicVocal } from 'lucide-react'
import { byline } from '../lib/format'
import { usePlayer, usePosition } from '../state/player'
import { useUI } from '../state/ui'
import { Artwork } from './Artwork'
import { CreditLine } from './CreditLine'
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
  const { setExpanded, panel, togglePanel } = useUI()
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
            {track && <CreditLine credit={status?.credit} className="mt-1 text-[11px] text-faint" />}
          </div>
        </button>
      </div>
      <div className="mx-auto flex w-full max-w-[680px] flex-col gap-1">
        <Transport />
        <SeekBar />
      </div>
      <div className="flex items-center justify-end gap-1">
        <IconButton label="Lyrics" active={panel === 'lyrics'} onClick={() => togglePanel('lyrics')}>
          <MicVocal className="size-[18px]" />
        </IconButton>
        <IconButton label="Up next" active={panel === 'queue'} onClick={() => togglePanel('queue')}>
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
  const { status } = usePlayer()
  const { setExpanded } = useUI()
  const track = status?.track
  if (!track) return null
  return (
    <div className="px-2 pb-1 md:hidden">
      <div
        role="button"
        tabIndex={0}
        onClick={() => setExpanded(true)}
        onKeyDown={(e) => e.key === 'Enter' && setExpanded(true)}
        className="relative flex h-14 items-center gap-3 overflow-hidden rounded-lg bg-glow px-2 shadow-lg shadow-black/50"
      >
        <Artwork src={track.artwork} className="size-10 shrink-0 rounded-[4px]" />
        <div className="min-w-0 flex-1">
          <div className="truncate text-[13px] font-semibold">{track.name}</div>
          <div className="truncate text-xs text-white/70">{byline(track)}</div>
        </div>
        <div onClick={(e) => e.stopPropagation()}>
          <PlayButton size="sm" className="!bg-transparent !text-fg" />
        </div>
        <MiniProgress />
      </div>
    </div>
  )
}
