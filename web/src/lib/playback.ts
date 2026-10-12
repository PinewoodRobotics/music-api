import type { Status } from './api'

export type Hold = { kind: 'airplay'; sender: string | null; resume: boolean } | { kind: 'quiet'; until: string } | null

export function clockLabel(hhmm: string) {
  const [h, m] = hhmm.split(':').map(Number)
  return new Date(2000, 0, 1, h, m).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
}

export function timeLabel(unixSeconds: number) {
  return new Date(unixSeconds * 1000).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
}

export function playbackHold(status: Status | null | undefined): Hold {
  if (status?.source === 'airplay')
    return { kind: 'airplay', sender: status.airplay?.sender ?? null, resume: !!status.airplay?.resume_spotify }
  const q = status?.quiet_hours
  if (q?.phase === 'locked') return { kind: 'quiet', until: clockLabel(q.until ?? '08:00') }
  return null
}

export function holdMessage(hold: Hold) {
  if (!hold) return ''
  if (hold.kind === 'quiet') return `Quiet hours: playback is off until ${hold.until}.`
  return `${airplayFrom(hold.sender)} is playing. Spotify is paused until it ends.`
}

export function airplayFrom(sender: string | null | undefined) {
  return sender ? `AirPlay from ${sender}` : 'AirPlay'
}

const AIRPLAY_ACTIONS = ['skip_next', 'skip_prev']

export function allowed(status: Status | null | undefined, action: string) {
  if (!status?.track) return false
  const hold = playbackHold(status)
  if (hold?.kind === 'airplay') return AIRPLAY_ACTIONS.includes(action)
  if (hold?.kind === 'quiet' && (action === 'skip_next' || action === 'skip_prev')) return false
  return status.actions.length === 0 || status.actions.includes(action)
}

export function playBlocked(status: Status | null | undefined, isPlaying: boolean) {
  const hold = playbackHold(status)
  return hold?.kind === 'quiet' && !isPlaying
}
