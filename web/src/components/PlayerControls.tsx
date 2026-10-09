import { Pause, Play, Repeat, Repeat1, Shuffle, SkipBack, SkipForward, Volume, Volume1, Volume2, VolumeX } from 'lucide-react'
import { useState } from 'react'
import { formatTime } from '../lib/format'
import { usePlayer, usePosition } from '../state/player'
import { IconButton } from './IconButton'
import { Slider } from './Slider'

export function PlayButton({ size = 'md', className = '' }: { size?: 'sm' | 'md' | 'lg'; className?: string }) {
  const { isPlaying, togglePlay, status } = usePlayer()
  const dims = { sm: 'size-9', md: 'size-10', lg: 'size-16' }[size]
  const icon = { sm: 'size-4', md: 'size-[18px]', lg: 'size-7' }[size]
  const Icon = isPlaying ? Pause : Play
  return (
    <button
      type="button"
      onClick={togglePlay}
      disabled={!status}
      aria-label={isPlaying ? 'Pause' : 'Play'}
      title={isPlaying ? 'Pause (Space)' : 'Play (Space)'}
      className={`grid ${dims} shrink-0 place-items-center rounded-full bg-fg text-canvas transition-transform hover:scale-105 active:scale-95 disabled:opacity-40 ${className}`}
    >
      <Icon className={`${icon} fill-current ${isPlaying ? '' : 'translate-x-[1px]'}`} strokeWidth={0} />
    </button>
  )
}

export function Transport({ size = 'md' }: { size?: 'md' | 'lg' }) {
  const { status, next, previous, toggleShuffle, cycleRepeat } = usePlayer()
  const can = (action: string) => !!status?.track && (status.actions.length === 0 || status.actions.includes(action))
  const RepeatIcon = status?.repeat === 'track' ? Repeat1 : Repeat
  const repeatLabel = { off: 'Enable repeat', context: 'Enable repeat one', track: 'Disable repeat' }[status?.repeat ?? 'off']
  const skip = size === 'lg' ? 'size-7' : 'size-5'
  const side = size === 'lg' ? 'size-5' : 'size-4'
  return (
    <div className={`flex items-center justify-center ${size === 'lg' ? 'gap-6' : 'gap-3'}`}>
      <IconButton label={status?.shuffle ? 'Disable shuffle' : 'Enable shuffle'} active={!!status?.shuffle} onClick={toggleShuffle} disabled={!can('shuffle')}>
        <Shuffle className={side} />
      </IconButton>
      <IconButton label="Previous" onClick={previous} disabled={!can('skip_prev')} className={size === 'lg' ? 'size-12' : ''}>
        <SkipBack className={`${skip} fill-current`} />
      </IconButton>
      <PlayButton size={size === 'lg' ? 'lg' : 'md'} />
      <IconButton label="Next" onClick={next} disabled={!can('skip_next')} className={size === 'lg' ? 'size-12' : ''}>
        <SkipForward className={`${skip} fill-current`} />
      </IconButton>
      <IconButton label={repeatLabel} active={!!status?.repeat && status.repeat !== 'off'} onClick={cycleRepeat} disabled={!can('set_repeat')}>
        <RepeatIcon className={side} />
      </IconButton>
    </div>
  )
}

export function SeekBar({ className = '', large = false }: { className?: string; large?: boolean }) {
  const { status, seek } = usePlayer()
  const position = usePosition()
  const [preview, setPreview] = useState<number | null>(null)
  const duration = status?.track ? status.duration_ms ?? status.track.duration_ms : 0
  const shown = preview ?? position
  const canSeek = !!status?.track && (status.actions.length === 0 || status.actions.includes('seek'))
  const time = `tabular text-[11px] text-dim ${large ? 'sm:text-xs' : ''} w-10 shrink-0`
  return (
    <div className={`flex items-center gap-2 ${className}`}>
      <span className={`${time} text-right`}>{formatTime(status?.track ? shown : 0)}</span>
      <Slider
        className={`flex-1 ${canSeek ? '' : 'pointer-events-none'}`}
        label="Seek"
        value={status?.track ? position : 0}
        max={duration}
        step={10000}
        valueText={`${formatTime(shown)} of ${formatTime(duration)}`}
        onPreview={setPreview}
        onCommit={seek}
        thick={large}
      />
      <span className={time}>{formatTime(duration)}</span>
    </div>
  )
}

export function VolumeControl({ className = '' }: { className?: string }) {
  const { status, setVolume, toggleMute } = usePlayer()
  const volume = status?.volume ?? 0
  const disabled = status?.volume == null
  const Icon = volume === 0 ? VolumeX : volume < 34 ? Volume : volume < 67 ? Volume1 : Volume2
  return (
    <div className={`flex items-center gap-1 ${className} ${disabled ? 'opacity-40' : ''}`}>
      <IconButton label={volume === 0 ? 'Unmute' : 'Mute'} onClick={toggleMute} disabled={disabled} size="sm">
        <Icon className="size-[18px]" />
      </IconButton>
      <Slider
        className="w-24 flex-1"
        label="Volume"
        value={volume}
        max={100}
        step={5}
        valueText={`${volume}%`}
        onPreview={(v) => v !== null && setVolume(v)}
        onCommit={setVolume}
      />
    </div>
  )
}
