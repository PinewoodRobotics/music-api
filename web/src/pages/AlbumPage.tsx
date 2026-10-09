import { useEffect, useMemo, useState } from 'react'
import { api, type Track } from '../lib/api'
import { formatLength, idFromUri, plural, year } from '../lib/format'
import { useAsync } from '../lib/useAsync'
import { BigPlayButton, CollectionHeader, Dot } from '../components/CollectionHeader'
import { Link } from '../components/Link'
import { TrackList } from '../components/TrackList'
import { usePlayer } from '../state/player'
import { HeaderSkeleton, RowsSkeleton } from '../components/Skeleton'
import { Message } from './Message'

export function AlbumPage({ id }: { id: string }) {
  const album = useAsync(() => api.album(id), [id])
  const [tracks, setTracks] = useState<Track[]>([])
  const { status, isPlaying, togglePlay, start, pending } = usePlayer()

  useEffect(() => {
    const first = album.data?.tracks
    if (!first) return
    setTracks(first.items)
    let live = true
    ;(async () => {
      let all = first.items
      for (let page = first; page.next; ) {
        page = await api.albumTracks(id, page.offset + page.limit)
        if (!live) return
        all = [...all, ...page.items]
        setTracks(all)
      }
    })().catch(() => {})
    return () => {
      live = false
    }
  }, [album.data, id])

  const duration = useMemo(() => tracks.reduce((s, t) => s + t.duration_ms, 0), [tracks])

  if (album.loading)
    return (
      <>
        <HeaderSkeleton />
        <div className="px-4 max-sm:px-2">
          <RowsSkeleton numbered />
        </div>
      </>
    )
  if (!album.data) return <Message title="Couldn't load this album" body={(album.error as Error)?.message} />
  const a = album.data
  const isCurrent = status?.context?.uri === a.uri

  return (
    <div>
      <CollectionHeader
        artwork={a.artwork}
        kind={a.album_type === 'single' ? 'Single' : a.album_type === 'compilation' ? 'Compilation' : 'Album'}
        title={a.name}
        meta={
          <>
            {a.artists.map((ar, i) => (
              <span key={ar.uri} className="font-semibold">
                {i > 0 && ', '}
                <Link href={`/artist/${idFromUri(ar.uri)}`} className="hover:underline">
                  {ar.name}
                </Link>
              </span>
            ))}
            <Dot />
            <span>{year(a.release_date)}</span>
            <Dot />
            <span>
              {plural(a.total_tracks, 'song')}
              <span className="text-white/65">, {formatLength(duration)}</span>
            </span>
          </>
        }
      >
        <BigPlayButton
          pending={pending === a.uri}
          playing={isCurrent && isPlaying}
          label={isCurrent && isPlaying ? 'Pause' : `Play ${a.name}`}
          onClick={() => (isCurrent ? togglePlay() : void start(a.uri, () => api.play({ uri: a.uri })))}
        />
      </CollectionHeader>
      <div className="relative px-4 pb-10 max-sm:px-2">
        <TrackList
          tracks={tracks}
          context={a.uri}
          showArt={false}
          showAlbum={false}
          onPlay={(i) => void start(`${a.uri}#${i}`, () => api.play({ context: a.uri, offset: i }))}
        />
        {a.label && <p className="mt-6 px-4 text-xs text-faint">{a.label}</p>}
      </div>
    </div>
  )
}
