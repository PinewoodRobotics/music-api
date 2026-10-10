import { CheckSquare, Copy, ListMusic, Plus, Trash2 } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api, ApiError, type AppPlaylist, type Track } from '../lib/api'
import { formatLength, plural } from '../lib/format'
import { useLibraryActions } from '../lib/library'
import { navigate } from '../lib/router'
import { useAsync } from '../lib/useAsync'
import { Attribution } from '../components/Attribution'
import { BigPlayButton, CollectionHeader, Dot, ShuffleButton } from '../components/CollectionHeader'
import { IconButton } from '../components/IconButton'
import { AddSongsPanel } from '../components/library/PlaylistTools'
import { Button } from '../components/Modal'
import { HeaderSkeleton, RowsSkeleton } from '../components/Skeleton'
import { TrackList, trackKeys } from '../components/TrackList'
import { usePlayer } from '../state/player'
import { useSession } from '../state/session'
import { useToast } from '../state/toast'
import { useUI } from '../state/ui'
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

const songs = (n: number) => `${n} song${n === 1 ? '' : 's'}`

function usePlaylistEditing(playlist: AppPlaylist | undefined, items: Track[] | null, setItems: (t: Track[]) => void) {
  const { upsertPlaylist } = useSession()
  const toast = useToast()
  const latest = useRef(items)
  latest.current = items

  const setLocal = useCallback(
    (next: Track[]) => {
      setItems(next)
      if (playlist) upsertPlaylist({ ...playlist, total: next.length })
    },
    [playlist, setItems, upsertPlaylist],
  )

  const rename = useCallback(
    async (patch: { name?: string; description?: string }) => {
      if (!playlist) return
      upsertPlaylist({ ...playlist, ...patch })
      try {
        upsertPlaylist(await api.updatePlaylist(playlist.id, patch))
      } catch (err) {
        upsertPlaylist(playlist)
        toast.error(err)
      }
    },
    [playlist, toast, upsertPlaylist],
  )

  const remove = useCallback(
    async (indices: number[]) => {
      const current = latest.current
      if (!playlist || !current || !indices.length) return
      const uris = [...new Set(indices.map((i) => current[i].uri))]
      const removed = current.map((t, i) => ({ t, i })).filter(({ t }) => uris.includes(t.uri))
      setLocal(current.filter((t) => !uris.includes(t.uri)))
      try {
        await api.removeFromPlaylist(playlist.id, uris)
        toast.show(removed.length === 1 ? `Removed ${removed[0].t.name}` : `Removed ${songs(removed.length)}`, {
          label: 'Undo',
          run: async () => {
            const restored = [...(latest.current ?? [])]
            for (const { t, i } of removed) restored.splice(i, 0, t)
            setLocal(restored)
            try {
              for (const { t, i } of removed) await api.addToPlaylistAt(playlist.id, [t.uri], i)
            } catch (err) {
              toast.error(err)
            }
          },
        })
      } catch (err) {
        setLocal(current)
        toast.error(err)
      }
    },
    [playlist, setLocal, toast],
  )

  const applyOrder = useCallback(
    async (from: Track[], to: Track[]) => {
      if (!playlist) return
      const fromKeys = trackKeys(from)
      const toKeys = trackKeys(to)
      const work = [...fromKeys]
      const moves: [number, number][] = []
      toKeys.forEach((key, i) => {
        const j = work.indexOf(key, i)
        if (j === i || j < 0) return
        work.splice(i, 0, work.splice(j, 1)[0])
        moves.push([j, i])
      })
      for (const [j, i] of moves) await api.reorderPlaylist(playlist.id, j, i)
    },
    [playlist],
  )

  const reorder = useCallback(
    async (indices: number[], to: number, undoable = true) => {
      const current = latest.current
      if (!playlist || !current || !indices.length) return
      const block = indices.map((i) => current[i])
      const picked = new Set(indices)
      const grabbed = indices.includes(to) ? to : indices[0]
      const down = to > grabbed
      const insertAt = current.filter((_, i) => !picked.has(i) && (down ? i <= to : i < to)).length
      const rest = current.filter((_, i) => !picked.has(i))
      const next = [...rest.slice(0, insertAt), ...block, ...rest.slice(insertAt)]
      if (next.every((t, i) => t === current[i])) return
      setLocal(next)
      try {
        await applyOrder(current, next)
        if (undoable)
          toast.show(block.length === 1 ? `Moved ${block[0].name}` : `Moved ${songs(block.length)}`, {
            label: 'Undo',
            run: async () => {
              setLocal(current)
              await applyOrder(next, current).catch(toast.error)
            },
          })
      } catch (err) {
        setLocal(current)
        toast.error(err)
      }
    },
    [applyOrder, playlist, setLocal, toast],
  )

  const append = useCallback(
    async (track: Track) => {
      const current = latest.current ?? []
      if (!playlist) return
      setLocal([...current, track])
      try {
        await api.addToPlaylist(playlist.id, [track.uri])
        toast.show(`Added ${track.name}`, {
          label: 'Undo',
          run: async () => {
            setLocal((latest.current ?? []).filter((t) => t.uri !== track.uri))
            await api.removeFromPlaylist(playlist.id, [track.uri]).catch(toast.error)
          },
        })
      } catch (err) {
        setLocal(current)
        toast.error(err)
      }
    },
    [playlist, setLocal, toast],
  )

  return { rename, remove, reorder, append }
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
  const { duplicatePlaylist } = useLibraryActions()
  const editing = usePlaylistEditing(playlist, items, setItems)
  const [editMode, setEditMode] = useState(false)
  const [adding, setAdding] = useState(false)
  const existing = useMemo(() => new Set((items ?? []).map((t) => t.uri)), [items])

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
      return <Message title="Playlist not found" body="It may have been deleted." action={<Button onClick={() => navigate('/')}>Go to Library</Button>} />
    return <ErrorState title="Couldn't load this playlist" error={meta.error} onRetry={retry} />
  }

  const isCurrent = status?.context?.uri === playlist.uri
  const count = items?.length ?? playlist.total
  const creator = playlist.created_by
  const editable = playlist.can_edit

  return (
    <div>
      <CollectionHeader
        artwork={playlist.artwork}
        kind="Playlist"
        title={playlist.name}
        description={playlist.description}
        onRename={editable ? (name) => void editing.rename({ name }) : undefined}
        onDescribe={editable ? (description) => void editing.rename({ description }) : undefined}
        meta={
          <>
            <Attribution person={creator} sourceUrl={playlist.source_url} linkSource className="font-semibold" avatarClass="size-6 text-[11px]" />
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
        <ShuffleButton
          pending={pending === `${playlist.uri}:shuffle`}
          onClick={() => void start(`${playlist.uri}:shuffle`, () => api.playPlaylist(playlist.id, { shuffle: true }), true)}
        />
        {editable && (
          <IconButton size="lg" label="Add songs" onClick={() => setAdding(true)}>
            <Plus className="size-6" />
          </IconButton>
        )}
        <IconButton size="lg" label="Duplicate playlist" onClick={() => void duplicatePlaylist(playlist.id, playlist.name)}>
          <Copy className="size-5" />
        </IconButton>
        {editable && (
          <IconButton size="lg" label="Delete playlist" onClick={() => openDialog({ kind: 'delete', playlist })}>
            <Trash2 className="size-5" />
          </IconButton>
        )}
        {items && items.length > 0 && (
          <button
            type="button"
            onClick={() => setEditMode((v) => !v)}
            className={`ml-auto inline-flex h-9 items-center gap-1.5 rounded-full px-4 text-sm font-semibold transition active:scale-95 ${
              editMode ? 'bg-fg text-canvas' : 'text-fg ring-1 ring-white/25 hover:bg-white/10'
            }`}
          >
            <CheckSquare className="size-4" />
            {editMode ? 'Done' : editable ? 'Edit' : 'Select'}
          </button>
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
            body={editable ? 'Search for songs and add them right here.' : 'Nothing has been added yet.'}
            action={
              editable && (
                <Button onClick={() => setAdding(true)}>
                  <Plus className="size-4" />
                  Add songs
                </Button>
              )
            }
          />
        ) : (
          <>
            <TrackList
              tracks={items}
              playlist={playlist}
              context={playlist.uri}
              editMode={editMode}
              onExitEdit={() => setEditMode(false)}
              onReorder={editable ? (indices, to) => void editing.reorder(indices, to) : undefined}
              onRemoveIndices={editable ? (indices) => void editing.remove(indices) : undefined}
              onPlay={(i) => void start(`${playlist.uri}#${i}`, () => api.playPlaylist(playlist.id, { offset: offsetFor(items, i) }))}
            />
          </>
        )}
      </div>
      {adding && <AddSongsPanel playlist={playlist} existing={existing} onAdd={(t) => void editing.append(t)} onClose={() => setAdding(false)} />}
    </div>
  )
}
