import { Loader2 } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { api, errorMessage, type Album } from '../lib/api'
import { year } from '../lib/format'
import { useAsync } from '../lib/useAsync'
import { BigPlayButton, CollectionHeader } from '../components/CollectionHeader'
import { CardGrid, MediaCard, Section } from '../components/MediaCard'
import { Button } from '../components/Modal'
import { CardsSkeleton, HeaderSkeleton } from '../components/Skeleton'
import { usePlayer } from '../state/player'
import { Message } from './Message'

function useDiscography(id: string) {
  const [albums, setAlbums] = useState<Album[]>([])
  const [next, setNext] = useState<number | null>(0)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(
    async (offset: number) => {
      setLoading(true)
      setError(null)
      try {
        const page = await api.artistAlbums(id, offset)
        setAlbums((list) => (offset === 0 ? page.items : [...list, ...page.items]))
        setNext(page.next ? page.offset + page.limit : null)
      } catch (err) {
        setError(errorMessage(err))
      } finally {
        setLoading(false)
      }
    },
    [id],
  )

  useEffect(() => {
    void load(0)
  }, [load])

  return { albums, loading, error, more: next !== null ? () => load(next) : null, retry: () => load(next ?? 0) }
}

export function ArtistPage({ id }: { id: string }) {
  const [attempt, setAttempt] = useState(0)
  const artist = useAsync(() => api.artist(id), [id, attempt])
  const discography = useDiscography(id)
  const { status, isPlaying, togglePlay, start, pending } = usePlayer()

  if (artist.loading) return <HeaderSkeleton />
  if (!artist.data)
    return (
      <Message
        title="Couldn't load this artist"
        body={errorMessage(artist.error)}
        action={<Button onClick={() => setAttempt((n) => n + 1)}>Try again</Button>}
      />
    )
  const a = artist.data
  const isCurrent = status?.context?.uri === a.uri
  const groups: [string, Album[]][] = [
    ['Albums', discography.albums.filter((x) => x.album_type === 'album')],
    ['Singles and EPs', discography.albums.filter((x) => x.album_type !== 'album')],
  ]

  return (
    <div>
      <CollectionHeader
        artwork={a.artwork}
        round
        kind="Artist"
        title={a.name}
        meta={a.genres?.length ? <span className="text-white/70">{a.genres.slice(0, 3).join(', ')}</span> : undefined}
      >
        <BigPlayButton
          playing={isCurrent && isPlaying}
          pending={pending === a.uri}
          label={isCurrent && isPlaying ? 'Pause' : `Play ${a.name}`}
          onClick={() => (isCurrent ? togglePlay() : void start(a.uri, () => api.play({ uri: a.uri })))}
        />
      </CollectionHeader>
      <div className="relative px-3 pb-10">
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
        {discography.loading && discography.albums.length === 0 && (
          <div className="mt-8">
            <CardsSkeleton />
          </div>
        )}
        {discography.error && (
          <Message
            title="Couldn't load the discography"
            body={discography.error}
            action={<Button onClick={() => void discography.retry()}>Try again</Button>}
          />
        )}
        {!discography.error && !discography.loading && discography.albums.length === 0 && (
          <Message title="No albums yet" body="This artist hasn't released any albums or singles on Spotify." />
        )}
        {discography.more && !discography.error && discography.albums.length > 0 && (
          <div className="mt-6 flex justify-center">
            <Button variant="ghost" className="ring-1 ring-white/20" disabled={discography.loading} onClick={() => void discography.more?.()}>
              {discography.loading && <Loader2 className="size-4 animate-spin" />}
              Show more
            </Button>
          </div>
        )}
      </div>
    </div>
  )
}
