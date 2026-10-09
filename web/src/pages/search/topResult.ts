import type { Album, Artist, SearchResults, SpotifyPlaylist, Track } from '../../lib/api'

export type TopResult =
  | { kind: 'artist'; item: Artist }
  | { kind: 'album'; item: Album }
  | { kind: 'playlist'; item: SpotifyPlaylist }
  | { kind: 'track'; item: Track }

const normalize = (s: string) =>
  s
    .normalize('NFD')
    .replace(/\p{Diacritic}/gu, '')
    .toLowerCase()
    .replace(/\s+/g, ' ')
    .trim()

export function pickTopResult(query: string, data: SearchResults): TopResult | null {
  const q = normalize(query)
  const same = (name: string) => normalize(name) === q
  const artist = data.artists?.items.find((a) => a && same(a.name))
  if (artist) return { kind: 'artist', item: artist }
  const album = data.albums?.items.find((a) => a && same(a.name))
  if (album) return { kind: 'album', item: album }
  const playlist = data.playlists?.items.find((p) => p && same(p.name))
  if (playlist) return { kind: 'playlist', item: playlist }
  const track = data.tracks?.items.find(Boolean)
  return track ? { kind: 'track', item: track } : null
}
