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

const KIND_ORDER: TopResult['kind'][] = ['artist', 'album', 'track', 'playlist']

type Candidate = { result: TopResult; score: number }

export function pickTopResult(query: string, data: SearchResults): TopResult | null {
  const q = normalize(query)
  const artists = first<Artist>(data.artists)
  const albums = first<Album>(data.albums)
  const playlists = first<SpotifyPlaylist>(data.playlists)
  const tracks = first<Track>(data.tracks)
  const credited = (list: { name: string }[] | undefined, name: string) => (list ?? []).some((a) => normalize(a.name) === name)

  const presence = (artistName: string | undefined) => {
    if (!artistName) return 0
    const name = normalize(artistName)
    return (
      tracks.filter((t) => credited(t.artists, name)).length +
      albums.filter((a) => credited(a.artists, name)).length +
      playlists.filter((p) => normalize(p.owner) === name).length
    )
  }

  const candidates: Candidate[] = []
  const exactArtists = new Set<string>()
  artists.slice(0, 3).forEach((artist, rank) => {
    const name = normalize(artist.name)
    const exact = name === q
    if (!exact && !name.startsWith(`${q} `)) return
    if (exact) exactArtists.add(name)
    candidates.push({ result: { kind: 'artist', item: artist }, score: presence(artist.name) + (exact ? 3 : 0) + (rank === 0 ? 2 : 0) })
  })

  const album = albums[0]
  const singleOfTopSong = album?.album_type === 'single' && !!tracks[0] && normalize(tracks[0].name) === normalize(album.name)
  if (album && normalize(album.name) === q && !singleOfTopSong) {
    const main = album.artists[0]?.name
    const penalty = main && exactArtists.has(normalize(main)) ? 2 : 0
    candidates.push({ result: { kind: 'album', item: album }, score: presence(main) + 3 - penalty })
  }

  const playlist = playlists[0]
  if (playlist && normalize(playlist.name) === q) candidates.push({ result: { kind: 'playlist', item: playlist }, score: 3 })

  const track = tracks[0]
  if (track) {
    const exact = normalize(track.name) === q
    candidates.push({ result: { kind: 'track', item: track }, score: presence(track.artists?.[0]?.name) + (exact ? 3 : 0) })
  }

  candidates.sort((a, b) => b.score - a.score || KIND_ORDER.indexOf(a.result.kind) - KIND_ORDER.indexOf(b.result.kind))
  return candidates[0]?.result ?? (artists[0] ? { kind: 'artist', item: artists[0] } : album ? { kind: 'album', item: album } : null)
}
