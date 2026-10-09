export type LinkSource = 'spotify' | 'apple'
export type LinkKind = 'track' | 'album' | 'playlist' | 'artist' | 'episode' | 'show' | 'unknown'
export type DetectedLink = { source: LinkSource; kind: LinkKind; label: string; importable: boolean }

const NOUNS: Record<LinkKind, string> = {
  track: 'song',
  album: 'album',
  playlist: 'playlist',
  artist: 'artist',
  episode: 'episode',
  show: 'podcast',
  unknown: 'link',
}

const SOURCE_NAMES: Record<LinkSource, string> = { spotify: 'Spotify', apple: 'Apple Music' }

function make(source: LinkSource, kind: LinkKind): DetectedLink {
  return { source, kind, label: `${SOURCE_NAMES[source]} ${NOUNS[kind]}`, importable: kind === 'album' || kind === 'playlist' }
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
  return null
}

export function sourceOfUrl(url: string | null | undefined): string | null {
  if (!url) return null
  if (/music\.apple\.com/i.test(url)) return 'Apple Music'
  if (/spotify/i.test(url)) return 'Spotify'
  return null
}
