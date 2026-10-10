import { useCallback } from 'react'
import { useSession } from '../state/session'
import { useToast } from '../state/toast'
import { useUI } from '../state/ui'
import { api, ApiError, type LibraryAlbum, type LibraryItem, type LibrarySort } from './api'
import { idFromUri } from './format'
import { navigate } from './router'

export type LibraryView = 'all' | 'playlists' | 'albums' | 'songs'

export const itemHref = (item: LibraryItem) => (item.kind === 'album' ? `/album/${idFromUri(item.uri)}` : `/playlist/${item.id}`)

export const addedBy = (item: LibraryItem) => (item.kind === 'album' ? item.added_by : item.created_by)

const addedAt = (item: LibraryItem) => (item.kind === 'album' ? item.added : item.created) ?? ''

export function albumYear(album: Pick<LibraryAlbum, 'year'>) {
  return album.year ? String(album.year).slice(0, 4) : ''
}

export function filterLibrary(
  items: LibraryItem[],
  { view, query, mine, sort, myId }: { view: LibraryView; query: string; mine: boolean; sort: LibrarySort; myId: string | null | undefined },
) {
  const q = query.trim().toLowerCase()
  const matches = (item: LibraryItem) => {
    if (view === 'playlists' && item.kind !== 'playlist') return false
    if (view === 'albums' && item.kind !== 'album') return false
    if (mine && addedBy(item)?.id !== myId) return false
    if (!q) return true
    const haystack = [item.name, addedBy(item)?.name, item.kind === 'album' ? item.artists.map((a) => a.name).join(' ') : item.description]
    return haystack.some((s) => s?.toLowerCase().includes(q))
  }
  const compare = {
    recent: (a: LibraryItem, b: LibraryItem) => addedAt(b).localeCompare(addedAt(a)),
    name: (a: LibraryItem, b: LibraryItem) => a.name.localeCompare(b.name, undefined, { sensitivity: 'base' }),
    creator: (a: LibraryItem, b: LibraryItem) =>
      (addedBy(a)?.name ?? '~').localeCompare(addedBy(b)?.name ?? '~') || addedAt(b).localeCompare(addedAt(a)),
  }[sort]
  return items.filter(matches).sort(compare)
}

export function useLibraryActions() {
  const { library, upsertAlbum, dropAlbum, upsertPlaylist } = useSession()
  const toast = useToast()
  const { openDialog } = useUI()

  const albumInLibrary = useCallback(
    (uri: string | undefined) => (uri ? (library?.find((x) => x.kind === 'album' && x.uri === uri) as LibraryAlbum | undefined) : undefined),
    [library],
  )

  const addAlbum = useCallback(
    async (target: { uri?: string; url?: string }, label?: string) => {
      try {
        const album = await api.addAlbum(target)
        upsertAlbum(album)
        toast.show(album.already ? `${album.name} is already in the Library` : `Added ${album.name} to the Library`)
        return album
      } catch (err) {
        if (err instanceof ApiError && err.status === 422 && target.url) {
          const url = target.url
          toast.show(err.message, { label: 'Import as playlist', run: () => openDialog({ kind: 'import', url, asPlaylist: true }) })
        } else if (err instanceof ApiError && err.status === 422) toast.show(`${label ?? 'That album'} isn't on Spotify as a whole album.`)
        else toast.error(err)
        return null
      }
    },
    [openDialog, toast, upsertAlbum],
  )

  const removeAlbum = useCallback(
    async (album: LibraryAlbum) => {
      dropAlbum(album.id)
      try {
        await api.removeAlbum(album.id)
        toast.show(`Removed ${album.name} from the Library`, {
          label: 'Undo',
          run: () => {
            upsertAlbum(album)
            api.addAlbum({ uri: album.uri }).then(upsertAlbum, (err) => {
              dropAlbum(album.id)
              toast.error(err)
            })
          },
        })
      } catch (err) {
        upsertAlbum(album)
        toast.error(err)
      }
    },
    [dropAlbum, toast, upsertAlbum],
  )

  const duplicatePlaylist = useCallback(
    async (id: string, name: string) => {
      try {
        const copy = await api.duplicatePlaylist(id, `${name} (copy)`)
        upsertPlaylist(copy)
        toast.show(`Duplicated as ${copy.name}`)
        navigate(`/playlist/${copy.id}`)
      } catch (err) {
        toast.error(err)
      }
    },
    [toast, upsertPlaylist],
  )

  return { albumInLibrary, addAlbum, removeAlbum, duplicatePlaylist }
}
