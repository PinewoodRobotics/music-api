import type { Track } from './api'

export function formatTime(ms: number | null | undefined) {
  const total = Math.max(0, Math.floor((ms ?? 0) / 1000))
  const h = Math.floor(total / 3600)
  const m = Math.floor((total % 3600) / 60)
  const s = String(total % 60).padStart(2, '0')
  return h ? `${h}:${String(m).padStart(2, '0')}:${s}` : `${m}:${s}`
}

export function formatLength(ms: number) {
  const minutes = Math.round(ms / 60000)
  if (minutes < 60) return `${minutes} min`
  const h = Math.floor(minutes / 60)
  const m = minutes % 60
  return m ? `${h} hr ${m} min` : `${h} hr`
}

export function plural(n: number, word: string) {
  return `${n.toLocaleString()} ${word}${n === 1 ? '' : 's'}`
}

export function byline(track: Pick<Track, 'artists' | 'show'> | null | undefined) {
  if (!track) return ''
  return track.artists?.map((a) => a.name).join(', ') || track.show?.name || ''
}

export function idFromUri(uri: string) {
  return uri.split(':').pop() ?? uri
}

export function year(date: string | null | undefined) {
  return date ? date.slice(0, 4) : ''
}

export function decodeEntities(text: string) {
  if (!text.includes('&')) return text
  const el = document.createElement('textarea')
  el.innerHTML = text
  return el.value
}

const relative = new Intl.RelativeTimeFormat(undefined, { numeric: 'always' })

export function fromNow(unixSeconds: number) {
  const s = unixSeconds - Date.now() / 1000
  const abs = Math.abs(s)
  if (Math.round(abs / 60) < 60) return relative.format(Math.round(s / 60), 'minute')
  if (Math.round(abs / 3600) < 24) return relative.format(Math.round(s / 3600), 'hour')
  if (Math.round(abs / 86400) < 60) return relative.format(Math.round(s / 86400), 'day')
  return relative.format(Math.round(s / (86400 * 30)), 'month')
}

export function formatMoment(unixSeconds: number) {
  const d = new Date(unixSeconds * 1000)
  return d.toLocaleString([], {
    weekday: 'short',
    month: 'short',
    day: 'numeric',
    ...(d.getFullYear() !== new Date().getFullYear() && { year: 'numeric' }),
    hour: 'numeric',
    minute: '2-digit',
  })
}
