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

const first = <T,>(page: { items: (T | null)[] } | undefined) => page?.items.filter((x): x is T => !!x) ?? []

export function pickTopResult(query: string, data: SearchResults): TopResult | null {
  const q = normalize(query)
  const same = (name: string) => normalize(name) === q
  const artists = first<Artist>(data.artists)
  const albums = first<Album>(data.albums)
  const playlists = first<SpotifyPlaylist>(data.playlists)
  const tracks = first<Track>(data.tracks)
  const [album, playlist, track] = [albums[0], playlists[0], tracks[0]]

  const albumHit = album && same(album.name)
  const playlistHit = playlist && same(playlist.name)
  const trackHit = track && same(track.name)

  const artist = artists.slice(0, 2).find((a) => same(a.name))
  if (artist && !albumHit && !playlistHit) return { kind: 'artist', item: artist }
  if (albumHit && !(album.album_type === 'single' && trackHit)) return { kind: 'album', item: album }
  if (playlistHit && !trackHit) return { kind: 'playlist', item: playlist }
  if (artists[0] && normalize(artists[0].name).startsWith(`${q} `)) return { kind: 'artist', item: artists[0] }
  if (trackHit) return { kind: 'track', item: track }
  if (track) return { kind: 'track', item: track }
  if (artists[0]) return { kind: 'artist', item: artists[0] }
  if (album) return { kind: 'album', item: album }
  return playlist ? { kind: 'playlist', item: playlist } : null
}
