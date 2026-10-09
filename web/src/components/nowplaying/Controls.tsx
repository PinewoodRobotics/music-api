import { FastForward, ListMusic, MessageSquareQuote, MoreHorizontal, Pause, Play, Repeat, Repeat1, Rewind, Shuffle, Speaker, Volume, Volume2 } from 'lucide-react'
import { useState, type ReactNode } from 'react'
import { byline, formatTime } from '../../lib/format'
import { usePlayer, usePosition } from '../../state/player'
import type { Panel } from '../../state/ui'
import { CreditLine } from '../CreditLine'
import type { AnchorRect } from '../Popover'
import { Slider } from '../Slider'
import { TrackMenu } from '../TrackMenu'

const can = (actions: string[] | undefined, hasTrack: boolean, action: string) =>
  hasTrack && (!actions?.length || actions.includes(action))

export function GlassSeek({ timesAbove = false }: { timesAbove?: boolean }) {
  const { status, seek } = usePlayer()
  const position = usePosition()
  const [preview, setPreview] = useState<number | null>(null)
  const duration = status?.track ? (status.duration_ms ?? status.track.duration_ms) : 0
  const shown = status?.track ? (preview ?? position) : 0
  const times = (
    <div className={`flex justify-between text-xs font-medium text-white/60 tabular ${timesAbove ? 'mb-2' : 'mt-2.5'}`}>
      <span>{formatTime(shown)}</span>
      <span>−{formatTime(Math.max(0, duration - shown))}</span>
    </div>
  )
  return (
    <div>
      {timesAbove && times}
      <Slider
        tone="glass"
        className={can(status?.actions, !!status?.track, 'seek') ? '' : 'pointer-events-none'}
        label="Seek"
        value={status?.track ? position : 0}
        max={duration}
        step={10000}
        valueText={`${formatTime(shown)} of ${formatTime(duration)}`}
        onPreview={setPreview}
        onCommit={seek}
      />
      {!timesAbove && times}
    </div>
  )
}

function GlyphButton({ label, onClick, disabled, size, children }: { label: string; onClick: () => void; disabled?: boolean; size: 'md' | 'lg'; children: ReactNode }) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      onClick={onClick}
      disabled={disabled}
      className={`grid shrink-0 place-items-center rounded-full text-white transition active:scale-90 active:bg-white/10 disabled:opacity-40 ${size === 'lg' ? 'size-[72px]' : 'size-11'}`}
    >
      {children}
    </button>
  )
}

export function Transport({ size, withModes = false }: { size: 'md' | 'lg'; withModes?: boolean }) {
  const { status, isPlaying, togglePlay, next, previous } = usePlayer()
  const has = !!status?.track
  const lg = size === 'lg'
  const skip = lg ? 'size-10' : 'size-6'
  const main = lg ? 'size-12' : 'size-8'
  return (
    <div className={`flex items-center ${lg ? 'justify-between' : 'justify-center gap-4'}`}>
      {withModes && <ModeButton kind="shuffle" />}
      <GlyphButton size={size} label="Previous" onClick={previous} disabled={!can(status?.actions, has, 'skip_prev')}>
        <Rewind className={`${skip} fill-current`} strokeWidth={0} />
      </GlyphButton>
      <GlyphButton size={size} label={isPlaying ? 'Pause' : 'Play'} onClick={togglePlay} disabled={!status}>
        {isPlaying ? <Pause className={`${main} fill-current`} strokeWidth={0} /> : <Play className={`${main} fill-current`} strokeWidth={0} />}
      </GlyphButton>
      <GlyphButton size={size} label="Next" onClick={next} disabled={!can(status?.actions, has, 'skip_next')}>
        <FastForward className={`${skip} fill-current`} strokeWidth={0} />
      </GlyphButton>
      {withModes && <ModeButton kind="repeat" />}
    </div>
  )
}

function ModeButton({ kind }: { kind: 'shuffle' | 'repeat' }) {
  const { status, toggleShuffle, cycleRepeat } = usePlayer()
  const on = kind === 'shuffle' ? !!status?.shuffle : !!status?.repeat && status.repeat !== 'off'
  const Icon = kind === 'shuffle' ? Shuffle : status?.repeat === 'track' ? Repeat1 : Repeat
  return (
    <button
      type="button"
      aria-label={kind === 'shuffle' ? 'Shuffle' : 'Repeat'}
      aria-pressed={on}
      onClick={kind === 'shuffle' ? toggleShuffle : cycleRepeat}
      disabled={!can(status?.actions, !!status?.track, kind === 'shuffle' ? 'shuffle' : 'set_repeat')}
      className={`grid size-11 place-items-center rounded-full transition active:scale-90 disabled:opacity-40 ${on ? 'text-white' : 'text-white/55'}`}
    >
      <Icon className="size-6" />
    </button>
  )
}

export function ModePills({ className = '' }: { className?: string }) {
  const { status, toggleShuffle, cycleRepeat } = usePlayer()
  const has = !!status?.track
  const RepeatIcon = status?.repeat === 'track' ? Repeat1 : Repeat
  const pill = (on: boolean) =>
    `flex h-10 flex-1 items-center justify-center rounded-full transition active:scale-95 disabled:opacity-40 ${
      on ? 'bg-white/90 text-black/75' : 'bg-white/15 text-white hover:bg-white/20'
    }`
  const repeatOn = !!status?.repeat && status.repeat !== 'off'
  return (
    <div className={`flex gap-3 ${className}`}>
      <button type="button" aria-label="Shuffle" aria-pressed={!!status?.shuffle} onClick={toggleShuffle} disabled={!can(status?.actions, has, 'shuffle')} className={pill(!!status?.shuffle)}>
        <Shuffle className="size-5" />
      </button>
      <button
        type="button"
        aria-label={status?.repeat === 'track' ? 'Repeat one' : 'Repeat'}
        aria-pressed={repeatOn}
        onClick={cycleRepeat}
        disabled={!can(status?.actions, has, 'set_repeat')}
        className={pill(repeatOn)}
      >
        <RepeatIcon className="size-5" />
      </button>
    </div>
  )
}

export function GlassVolume({ className = '' }: { className?: string }) {
  const { status, setVolume, toggleMute } = usePlayer()
  const volume = status?.volume ?? 0
  const disabled = status?.volume == null
  return (
    <div className={`flex items-center gap-3 text-white/70 ${disabled ? 'opacity-40' : ''} ${className}`}>
      <button type="button" onClick={toggleMute} disabled={disabled} aria-label={volume === 0 ? 'Unmute' : 'Mute'} className="-m-2 grid size-10 place-items-center active:scale-90">
        <Volume className="size-[18px] fill-current" />
      </button>
      <Slider
        tone="glass"
        className="flex-1"
        label="Volume"
        value={volume}
        max={100}
        step={5}
        valueText={`${volume}%`}
        onPreview={(v) => v !== null && setVolume(v)}
        onCommit={(v) => setVolume(v, true)}
      />
      <button type="button" onClick={() => setVolume(100, true)} disabled={disabled} aria-label="Full volume" className="-m-2 grid size-10 place-items-center active:scale-90">
        <Volume2 className="size-[22px]" />
      </button>
    </div>
  )
}

export function ViewToggle({ panel, current, onToggle, small = false }: { panel: Panel; current: Panel | null; onToggle: (p: Panel) => void; small?: boolean }) {
  const active = current === panel
  const Icon = panel === 'lyrics' ? MessageSquareQuote : ListMusic
  return (
    <button
      type="button"
      aria-label={panel === 'lyrics' ? 'Lyrics' : 'Up next'}
      title={panel === 'lyrics' ? 'Lyrics' : 'Up next'}
      aria-pressed={active}
      onClick={() => onToggle(panel)}
      className={`grid shrink-0 place-items-center rounded-full transition active:scale-90 ${small ? 'size-9' : 'size-12'} ${
        active ? 'bg-white/90 text-black/70' : 'text-white/75 hover:text-white active:bg-white/10'
      }`}
    >
      <Icon className={small ? 'size-[18px]' : 'size-6'} />
    </button>
  )
}

export function DeviceIndicator() {
  const { status } = usePlayer()
  return (
    <div className="flex min-w-0 items-center gap-1.5 text-[13px] font-medium text-white/70">
      <Speaker className="size-4 shrink-0" />
      <span className="truncate">{status?.device?.name ?? 'Lab Speakers'}</span>
    </div>
  )
}

export function TrackMenuButton({ subtle = false }: { subtle?: boolean }) {
  const { status } = usePlayer()
  const [menu, setMenu] = useState<AnchorRect | null>(null)
  const track = status?.track
  if (!track) return <span className="size-11" />
  return (
    <>
      <button
        type="button"
        aria-label="More options"
        title="More options"
        onClick={(e) => setMenu(e.currentTarget.getBoundingClientRect())}
        className={`grid shrink-0 place-items-center rounded-full text-white transition active:scale-90 ${
          subtle ? 'size-9 text-white/75 hover:text-white' : 'size-11 bg-white/15 hover:bg-white/20'
        }`}
      >
        <MoreHorizontal className="size-5" />
      </button>
      {menu && <TrackMenu track={track} anchor={menu} align={subtle ? 'start' : 'end'} onClose={() => setMenu(null)} />}
    </>
  )
}

export function TrackTitle({ size, withMenu = true }: { size: 'sm' | 'md' | 'lg'; withMenu?: boolean }) {
  const { status } = usePlayer()
  const track = status?.track
  if (!track) return <div className="min-w-0 flex-1 text-lg font-semibold text-white/70">Nothing playing</div>
  const title = { sm: 'text-[17px]', md: 'text-[22px]', lg: 'text-2xl' }[size]
  const sub = { sm: 'text-[15px]', md: 'text-[19px]', lg: 'text-lg' }[size]
  return (
    <div className="flex min-w-0 flex-1 items-center gap-2">
      <div className="min-w-0 flex-1">
        <div className={`truncate font-semibold leading-tight ${title}`}>{track.name}</div>
        <div className={`truncate text-white/70 ${sub}`}>{byline(track)}</div>
        <CreditLine credit={status?.credit} className="mt-1 text-[13px] text-white/60" />
      </div>
      {withMenu && <TrackMenuButton />}
    </div>
  )
}
