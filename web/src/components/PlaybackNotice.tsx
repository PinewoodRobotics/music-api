import { Airplay, Loader2, Moon, Square } from 'lucide-react'
import { useState, type ReactNode } from 'react'
import type { Status } from '../lib/api'
import { airplayFrom, clockLabel, timeLabel } from '../lib/playback'
import { usePlayer } from '../state/player'

type Notice = { kind: 'airplay' | 'quiet'; title: string; detail: string }

function noticeFor(status: Status | null): Notice | null {
  if (status?.source === 'airplay')
    return {
      kind: 'airplay',
      title: airplayFrom(status.airplay?.sender),
      detail: status.airplay?.resume_spotify
        ? 'Spotify is paused and picks up right where it left off when AirPlay ends.'
        : 'Spotify is paused. Its queue stays as it is.',
    }
  const q = status?.quiet_hours
  if (!q?.enabled || q.phase === 'open') return null
  const until = clockLabel(q.until ?? '08:00')
  if (q.phase === 'locked')
    return { kind: 'quiet', title: `Quiet hours until ${until}`, detail: 'Playback is off for the night. Search, playlists, the library and the queue still work.' }
  if (isAudible(status)) return null
  const minutes = Math.round((q.grace_s ?? 300) / 60)
  return {
    kind: 'quiet',
    title: q.locks_at ? `Paused. Playback locks at ${timeLabel(q.locks_at)} unless something plays.` : `Paused. Playback locks after ${minutes} min unless something plays.`,
    detail: `Quiet hours until ${until}. Once locked, playback stays off until then.`,
  }
}

function isAudible(status: Status | null) {
  return status?.state === 'playing' || status?.state === 'buffering'
}

export function QuietMoon({ className = '' }: { className?: string }) {
  const { status } = usePlayer()
  const q = status?.quiet_hours
  if (!q?.enabled || q.phase !== 'grace' || !isAudible(status)) return null
  const label = `Quiet hours: locks ${Math.round((q.grace_s ?? 300) / 60)} min after music stops`
  return (
    <span role="img" aria-label={label} title={label} className={`inline-grid shrink-0 place-items-center ${className}`}>
      <Moon className="size-3.5" aria-hidden />
    </span>
  )
}

export function StopAirPlayButton({ tone }: { tone: 'glass' | 'panel' }) {
  const { stopAirPlay } = usePlayer()
  const [busy, setBusy] = useState(false)
  const look = tone === 'glass' ? 'bg-white/90 text-black/80 hover:bg-white' : 'bg-fg text-canvas hover:scale-[1.03]'
  return (
    <button
      type="button"
      disabled={busy}
      onClick={() => {
        setBusy(true)
        void stopAirPlay().finally(() => setBusy(false))
      }}
      className={`inline-flex h-9 shrink-0 items-center gap-2 rounded-full px-4 text-sm font-semibold transition active:scale-95 disabled:opacity-60 ${look}`}
    >
      {busy ? <Loader2 className="size-4 animate-spin" /> : <Square className="size-3.5 fill-current" strokeWidth={0} />}
      Stop AirPlay
    </button>
  )
}

function Icon({ kind, className }: { kind: Notice['kind']; className: string }) {
  return kind === 'airplay' ? <Airplay className={className} aria-hidden /> : <Moon className={className} aria-hidden />
}

function Frame({ notice, action, className }: { notice: Notice; action?: ReactNode; className: string }) {
  return (
    <div role="status" className={`flex items-center gap-3 ${className}`}>
      <Icon kind={notice.kind} className="size-5 shrink-0" />
      <div className="min-w-0 flex-1">
        <div className="font-semibold">{notice.title}</div>
        <div className="opacity-70">{notice.detail}</div>
      </div>
      {action}
    </div>
  )
}

export function PlaybackBanner() {
  const { status } = usePlayer()
  const notice = noticeFor(status)
  if (!notice) return null
  return (
    <Frame
      notice={notice}
      action={notice.kind === 'airplay' && <StopAirPlayButton tone="panel" />}
      className="mx-4 mb-3 rounded-lg bg-white/[0.07] px-4 py-3 text-sm text-fg max-sm:flex-wrap"
    />
  )
}

export function SheetNotice({ className = '' }: { className?: string }) {
  const { status } = usePlayer()
  const found = noticeFor(status)
  if (!found) return null
  const notice =
    found.kind === 'airplay'
      ? {
          ...found,
          title: 'Spotify is paused',
          detail: status?.airplay?.resume_spotify ? 'It picks up where it left off when AirPlay ends.' : 'Its queue stays as it is.',
        }
      : found
  return (
    <Frame
      notice={notice}
      action={notice.kind === 'airplay' && <StopAirPlayButton tone="glass" />}
      className={`rounded-2xl bg-white/12 px-4 py-3 text-[13px] text-white backdrop-blur-md ${className}`}
    />
  )
}

export function QueuePausedNote() {
  const { status } = usePlayer()
  if (status?.source !== 'airplay') return null
  return (
    <div role="status" className="mx-2 mb-4 flex items-start gap-2.5 rounded-lg bg-white/10 px-3 py-2.5 text-sm text-white/80">
      <Airplay className="mt-0.5 size-4 shrink-0" aria-hidden />
      <span>
        Up Next is paused while {airplayFrom(status.airplay?.sender)} plays.{' '}
        {status.airplay?.resume_spotify ? 'Spotify picks up here when AirPlay ends.' : 'It stays here for when Spotify plays again.'}
      </span>
    </div>
  )
}
