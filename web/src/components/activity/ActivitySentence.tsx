import { Lock, SquareTerminal } from 'lucide-react'
import type { ReactNode } from 'react'
import type { ActivityEntry } from '../../lib/api'
import { formatTime } from '../../lib/format'
import { SlackLogo } from '../SlackLogo'

const str = (v: unknown) => (typeof v === 'string' && v.trim() ? v : null)
const num = (v: unknown) => (typeof v === 'number' && Number.isFinite(v) ? v : null)
const songs = (n: number) => `${n} song${n === 1 ? '' : 's'}`

const Em = ({ children }: { children: ReactNode }) => <em className="font-medium not-italic text-fg">{children}</em>

export function describeActivity(entry: ActivityEntry, count = 1, total?: number): ReactNode {
  const d = entry.detail ?? {}
  const name = str(d.name)
  switch (entry.action) {
    case 'play':
      return 'resumed playback'
    case 'pause':
      return 'paused'
    case 'play_item':
      return name ? <>played <Em>{name}</Em></> : `played ${str(d.type) ?? 'something'}`
    case 'next':
      if (count > 1) return `skipped ${songs(count)}`
      return str(d.from) ? <>skipped <Em>{str(d.from)}</Em></> : 'skipped a song'
    case 'previous':
      if (count > 1) return `went back ${count} times`
      return str(d.from) ? <>went back from <Em>{str(d.from)}</Em></> : 'went back a song'
    case 'jump':
      return name ? <>jumped to <Em>{name}</Em></> : 'jumped ahead in Up Next'
    case 'seek':
      return `seeked to ${formatTime(num(d.position_ms) ?? 0)}`
    case 'volume':
      return `set volume to ${num(d.volume) ?? 0}%`
    case 'shuffle':
      return `turned shuffle ${d.enabled ? 'on' : 'off'}`
    case 'repeat':
      return d.mode === 'track' ? 'set repeat to one song' : d.mode === 'context' ? 'turned repeat on' : 'turned repeat off'
    case 'queue_add': {
      const n = total ?? num(d.count) ?? 1
      const first = Array.isArray(d.names) ? str(d.names[0]) : null
      return n === 1 && first ? <>queued <Em>{first}</Em></> : `queued ${songs(n)}`
    }
    case 'playlist_create':
      return <>created playlist <Em>{name ?? 'a playlist'}</Em></>
    case 'playlist_import': {
      const imported = num(d.imported)
      return (
        <>
          imported <Em>{name ?? 'a playlist'}</Em>
          {imported != null && ` (${songs(imported)})`}
        </>
      )
    }
    case 'playlist_rename':
      return <>renamed a playlist to <Em>{name ?? 'something new'}</Em></>
    case 'playlist_delete':
      return <>deleted playlist <Em>{name ?? 'a playlist'}</Em></>
    case 'playlist_add': {
      const n = total ?? num(d.count) ?? 1
      const first = Array.isArray(d.names) ? str(d.names[0]) : null
      return (
        <>
          added {n === 1 && first ? <Em>{first}</Em> : songs(n)} to <Em>{name ?? 'a playlist'}</Em>
        </>
      )
    }
    case 'playlist_remove': {
      const n = num(d.count) ?? 1
      return <>removed {songs(n)} from <Em>{name ?? 'a playlist'}</Em></>
    }
    case 'playlist_play':
      return <>played playlist <Em>{name ?? 'a playlist'}</Em></>
    default:
      return entry.action.replace(/_/g, ' ')
  }
}

export function OriginIcon({ origin, className = 'size-3.5' }: { origin: ActivityEntry['origin']; className?: string }) {
  if (origin === 'slack')
    return (
      <span title="From Slack" className="inline-flex shrink-0">
        <SlackLogo className={className} />
      </span>
    )
  if (origin === 'media-session')
    return (
      <span title="From a lock screen or media keys" className="inline-flex shrink-0 text-dim">
        <Lock className={className} />
      </span>
    )
  if (origin === 'api')
    return (
      <span title="Through the API" className="inline-flex shrink-0 text-dim">
        <SquareTerminal className={className} />
      </span>
    )
  return null
}
