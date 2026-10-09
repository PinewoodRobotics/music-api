import { ListMusic, Pencil, Search, Trash2 } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { api, ApiError, type AppPlaylist, type Track } from '../lib/api'
import { formatLength, plural } from '../lib/format'
import { navigate } from '../lib/router'
import { useAsync } from '../lib/useAsync'
import { Attribution } from '../components/Attribution'
import { BigPlayButton, CollectionHeader, Dot, ShuffleButton } from '../components/CollectionHeader'
import { IconButton } from '../components/IconButton'
import { Button } from '../components/Modal'
import { TrackList } from '../components/TrackList'
import { usePlayer } from '../state/player'
import { useSession } from '../state/session'
import { useUI } from '../state/ui'
import { HeaderSkeleton, RowsSkeleton } from '../components/Skeleton'
import { ErrorState, Message } from './Message'

function useAllItems(id: string, attempt: number) {
  const [items, setItems] = useState<Track[] | null>(null)
  const [error, setError] = useState<unknown>(null)
  useEffect(() => {
    let live = true
    setItems(null)
    setError(null)
    ;(async () => {
      let all: Track[] = []
      for (let offset = 0; ; ) {
        const page = await api.playlistItems(id, offset)
        if (!live) return
        all = [...all, ...page.items]
        setItems(all)
        if (!page.next) break
        offset = page.offset + page.limit
      }
    })().catch((err) => live && setError(err))
    return () => {
      live = false
    }
  }, [id, attempt])
  return { items, setItems, error }
}

export function offsetFor(tracks: Track[], index: number): number | string {
  const uri = tracks[index].uri
  return tracks.filter((t) => t.uri === uri).length === 1 ? uri : index
}

export function PlaylistPage({ id }: { id: string }) {
  const { playlists, upsertPlaylist } = useSession()
  const cached = playlists?.find((p) => p.id === id)
  const [attempt, setAttempt] = useState(0)
  const retry = () => setAttempt((n) => n + 1)
  const meta = useAsync(() => api.playlist(id), [id, attempt])
  const playlist: AppPlaylist | undefined = cached ?? meta.data
  const { items, setItems, error } = useAllItems(id, attempt)
  const { status, isPlaying, togglePlay, start, pending } = usePlayer()
  const { openDialog } = useUI()

  useEffect(() => {
    if (meta.data) upsertPlaylist(meta.data)
  }, [meta.data, upsertPlaylist])

  const duration = useMemo(() => (items ?? []).reduce((sum, t) => sum + (t.duration_ms || 0), 0), [items])

  if (!playlist) {
    if (meta.loading)
      return (
        <>
          <HeaderSkeleton />
          <div className="px-4 max-sm:px-2">
            <RowsSkeleton numbered />
          </div>
        </>
      )
    if (meta.error instanceof ApiError && meta.error.status === 404)
      return <Message title="Playlist not found" body="It may have been deleted." action={<Button onClick={() => navigate('/')}>Go home</Button>} />
    return <ErrorState title="Couldn't load this playlist" error={meta.error} onRetry={retry} />
  }

  const isCurrent = status?.context?.uri === playlist.uri
  const count = items?.length ?? playlist.total
  const creator = playlist.created_by
  const removeLocal = (uri: string) => {
    const remaining = (items ?? []).filter((t) => t.uri !== uri)
    setItems(remaining)
    upsertPlaylist({ ...playlist, total: remaining.length })
  }

  return (
    <div>
      <CollectionHeader
        artwork={playlist.artwork}
        kind="Playlist"
        title={playlist.name}
        description={playlist.description}
        meta={
          <>
            <Attribution
              person={creator}
              sourceUrl={playlist.source_url}
              linkSource
              className="font-semibold"
              avatarClass="size-6 text-[11px]"
            />
            {(creator || playlist.source_url) && <Dot />}
            <span>
              {plural(count, 'song')}
              {items && items.length > 0 && <span className="text-white/65">, {formatLength(duration)}</span>}
            </span>
          </>
        }
      >
        <BigPlayButton
          pending={pending === playlist.uri}
          playing={isCurrent && isPlaying}
          label={isCurrent && isPlaying ? 'Pause' : `Play ${playlist.name}`}
          onClick={() => (isCurrent ? togglePlay() : void start(playlist.uri, () => api.playPlaylist(playlist.id, { shuffle: false }), false))}
        />
        <ShuffleButton pending={pending === `${playlist.uri}:shuffle`} onClick={() => void start(`${playlist.uri}:shuffle`, () => api.playPlaylist(playlist.id, { shuffle: true }), true)} />
        {playlist.can_edit && (
          <>
            <IconButton size="lg" label="Edit details" onClick={() => openDialog({ kind: 'edit', playlist })}>
              <Pencil className="size-5" />
            </IconButton>
            <IconButton size="lg" label="Delete playlist" onClick={() => openDialog({ kind: 'delete', playlist })}>
              <Trash2 className="size-5" />
            </IconButton>
          </>
        )}
      </CollectionHeader>

      <div className="relative px-4 pb-10 max-sm:px-2">
        {error ? (
          <ErrorState title="Couldn't load the songs" error={error} onRetry={retry} />
        ) : items === null ? (
          <RowsSkeleton numbered />
        ) : items.length === 0 ? (
          <Message
            icon={<ListMusic className="size-10" />}
            title="This playlist is empty"
            body="Find songs in Search and add them with the ••• menu."
            action={
              <Button onClick={() => navigate('/search')}>
                <Search className="size-4" />
                Search for songs
              </Button>
            }
          />
        ) : (
          <TrackList
            tracks={items}
            playlist={playlist}
            onRemoved={removeLocal}
            context={playlist.uri}
            onPlay={(i) => void start(`${playlist.uri}#${i}`, () => api.playPlaylist(playlist.id, { offset: offsetFor(items, i) }))}
          />
        )}
      </div>
    </div>
  )
}
