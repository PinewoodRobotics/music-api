import { api, type Album } from '../lib/api'
import { year } from '../lib/format'
import { useAsync } from '../lib/useAsync'
import { BigPlayButton, CollectionHeader } from '../components/CollectionHeader'
import { CardGrid, MediaCard, Section } from '../components/MediaCard'
import { usePlayer } from '../state/player'
import { CardsSkeleton, HeaderSkeleton } from '../components/Skeleton'
import { Message } from './Message'

export function ArtistPage({ id }: { id: string }) {
  const artist = useAsync(() => api.artist(id), [id])
  const albums = useAsync(() => api.artistAlbums(id), [id])
  const { status, isPlaying, togglePlay, start, pending } = usePlayer()

  if (artist.loading) return <HeaderSkeleton />
  if (!artist.data) return <Message title="Couldn't load this artist" body={(artist.error as Error)?.message} />
  const a = artist.data
  const isCurrent = status?.context?.uri === a.uri
  const groups: [string, Album[]][] = [
    ['Albums', albums.data?.items.filter((x) => x.album_type === 'album') ?? []],
    ['Singles and EPs', albums.data?.items.filter((x) => x.album_type !== 'album') ?? []],
  ]

  return (
    <div>
      <CollectionHeader artwork={a.artwork} round kind="Artist" title={a.name} meta={a.genres?.length ? <span className="text-white/70">{a.genres.slice(0, 3).join(', ')}</span> : undefined}>
        <BigPlayButton
          pending={pending === a.uri}
          playing={isCurrent && isPlaying}
          label={isCurrent && isPlaying ? 'Pause' : `Play ${a.name}`}
          onClick={() => (isCurrent ? togglePlay() : void start(a.uri, () => api.play({ uri: a.uri })))}
        />
      </CollectionHeader>
      <div className="relative px-3 pb-10">
        {albums.loading && (
          <div className="mt-8">
            <CardsSkeleton />
          </div>
        )}
        {groups.map(([title, list]) =>
          list.length ? (
            <Section key={title} title={title}>
              <CardGrid>
                {list.map((al) => (
                  <MediaCard
                    key={al.id}
                    title={al.name}
                    subtitle={year(al.release_date)}
                    artwork={al.artwork}
                    href={`/album/${al.id}`}
                    playing={status?.context?.uri === al.uri && isPlaying}
                    pending={pending === al.uri}
                    onPlay={() => (status?.context?.uri === al.uri ? togglePlay() : void start(al.uri, () => api.play({ uri: al.uri })))}
                  />
                ))}
              </CardGrid>
            </Section>
          ) : null,
        )}
      </div>
    </div>
  )
}
