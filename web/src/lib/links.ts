export type LinkSource = 'spotify' | 'apple' | 'youtube'
export type LinkKind = 'track' | 'album' | 'playlist' | 'artist' | 'episode' | 'show' | 'unknown'
export type DetectedLink = { source: LinkSource; kind: LinkKind; name: string; label: string; importable: boolean }

const NOUNS: Record<LinkKind, string> = {
  track: 'song',
  album: 'album',
  playlist: 'playlist',
  artist: 'artist',
  episode: 'episode',
  show: 'podcast',
  unknown: 'link',
}

const SOURCE_NAMES: Record<LinkSource, string> = { spotify: 'Spotify', apple: 'Apple Music', youtube: 'YouTube' }

function make(source: LinkSource, kind: LinkKind, name = SOURCE_NAMES[source]): DetectedLink {
  return { source, kind, name, label: `${name} ${NOUNS[kind]}`, importable: kind === 'album' || kind === 'playlist' }
}

const YOUTUBE_HOST = /^(?:https?:\/\/)?(?:(?:www|m|music)\.)?(?:youtube(?:-nocookie)?\.com|youtu\.be)(?:\/|$)/i

function detectYouTube(t: string): DetectedLink {
  const name = /^(?:https?:\/\/)?music\./i.test(t) ? 'YouTube Music' : 'YouTube'
  const video = (u: string) => /^[\w-]{11}$/.test(u)
  try {
    const url = new URL(/^https?:\/\//i.test(t) ? t : `https://${t}`)
    const host = url.hostname.replace(/^(?:www|m|music)\./, '')
    const parts = url.pathname.split('/').filter(Boolean)
    const v = url.searchParams.get('v') ?? ''
    const list = url.searchParams.get('list') ?? ''
    const byList = (): DetectedLink => {
      if (/^(?:RD|LL|FL|LM|WL)/.test(list) || !list) return make('youtube', 'unknown', name)
      return make('youtube', list.startsWith('OLAK5uy_') ? 'album' : 'playlist', name)
    }
    if (host === 'youtu.be') return video(parts[0] ?? '') ? make('youtube', 'track', name) : make('youtube', 'unknown', name)
    if (parts[0] === 'watch') return video(v) ? make('youtube', 'track', name) : byList()
    if (['shorts', 'live', 'embed', 'v'].includes(parts[0]) && video(parts[1] ?? '')) return make('youtube', 'track', name)
    if (parts[0] === 'playlist') return byList()
    if (parts[0] === 'browse' && parts[1]?.startsWith('MPREb_')) return make('youtube', 'album', name)
  } catch {
    return make('youtube', 'unknown', name)
  }
  return make('youtube', 'unknown', name)
}

export function detectLink(text: string): DetectedLink | null {
  const t = text.trim()
  if (!t || /\s/.test(t)) return null
  const spotify =
    t.match(/^spotify:(track|album|playlist|artist|episode|show):/i) ??
    t.match(/^(?:https?:\/\/)?open\.spotify\.com\/(?:intl-[a-z-]+\/)?(?:embed\/)?(track|album|playlist|artist|episode|show)\//i)
  if (spotify) return make('spotify', spotify[1].toLowerCase() as LinkKind)
  if (/^spotify:|open\.spotify\.com/i.test(t)) return make('spotify', 'unknown')
  const apple = t.match(/^(?:https?:\/\/)?(?:embed\.)?music\.apple\.com\/(?:[a-z]{2}\/)?(album|playlist|song|artist)\//i)
  if (apple) {
    const kind = apple[1].toLowerCase()
    if (kind === 'song' || (kind === 'album' && /[?&]i=\d+/.test(t))) return make('apple', 'track')
    return make('apple', kind as LinkKind)
  }
  if (/music\.apple\.com/i.test(t)) return make('apple', 'unknown')
  if (YOUTUBE_HOST.test(t)) return detectYouTube(t)
  return null
}

export function sourceOfUrl(url: string | null | undefined): LinkSource | null {
  if (!url) return null
  if (/music\.apple\.com/i.test(url)) return 'apple'
  if (YOUTUBE_HOST.test(url.trim())) return 'youtube'
  if (/spotify/i.test(url)) return 'spotify'
  return null
}

export const SOURCE_LABELS: Record<LinkSource, string> = SOURCE_NAMES

export function sourceName(source: LinkSource, url: string) {
  return source === 'youtube' && /^(?:https?:\/\/)?music\./i.test(url.trim()) ? 'YouTube Music' : SOURCE_NAMES[source]
}

export function looksLikeUrl(text: string) {
  const t = text.trim()
  return /^(https?:\/\/|spotify:)/i.test(t) || /^(www\.)?[a-z0-9-]+(\.[a-z0-9-]+)+\/\S*$/i.test(t)
}
