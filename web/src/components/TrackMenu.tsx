import { ChevronLeft, ChevronRight, Disc3, LibraryBig, ListEnd, ListPlus, MicVocal, Plus, Trash2 } from 'lucide-react'
import { useCallback, useState, type ReactNode } from 'react'
import { api, type AppPlaylist, type Track } from '../lib/api'
import { idFromUri } from '../lib/format'
import { useLibraryActions } from '../lib/library'
import { navigate } from '../lib/router'
import { usePlayer } from '../state/player'
import { useSession } from '../state/session'
import { useToast } from '../state/toast'
import { useUI } from '../state/ui'
import { Artwork } from './Artwork'
import { MenuDivider, MenuItem, Popover, type AnchorRect } from './Popover'

export type ExtraAction = { label: string; icon: ReactNode; run: () => void }

type Props = {
  track?: Track
  tracks?: Track[]
  anchor: AnchorRect
  onClose: () => void
  playlist?: AppPlaylist
  onRemoved?: (uri: string) => void
  onRemove?: () => void
  align?: 'start' | 'end'
  initialView?: 'main' | 'playlists'
  extraActions?: ExtraAction[]
}

const songs = (n: number) => `${n} song${n === 1 ? '' : 's'}`

export function useTrackActions() {
  const { addToQueue } = usePlayer()
  const { upsertPlaylist } = useSession()
  const toast = useToast()
  const addTo = useCallback(
    async (target: AppPlaylist, uris: string[]) => {
      try {
        await api.addToPlaylist(target.id, uris)
        upsertPlaylist({ ...target, total: target.total + uris.length })
        toast.show(uris.length === 1 ? `Added to ${target.name}` : `Added ${songs(uris.length)} to ${target.name}`)
      } catch (err) {
        toast.error(err)
      }
    },
    [toast, upsertPlaylist],
  )
  return { queue: (uris: string[]) => addToQueue(uris), addTo }
}

export function TrackMenu(props: Props) {
  const { anchor, onClose, playlist, onRemoved, onRemove, align, initialView = 'main', extraActions = [] } = props
  const list = props.tracks ?? (props.track ? [props.track] : [])
  const single = list.length === 1 ? list[0] : null
  const uris = list.map((t) => t.uri)
  const [view, setView] = useState<'main' | 'playlists'>(initialView)
  const { playlists } = useSession()
  const { openDialog } = useUI()
  const { albumInLibrary, addAlbum } = useLibraryActions()
  const { queue, addTo } = useTrackActions()
  const toast = useToast()

  const close = (fn: () => void) => () => {
    onClose()
    fn()
  }

  const remove = async () => {
    onClose()
    if (onRemove) return onRemove()
    if (!playlist) return
    try {
      await api.removeFromPlaylist(playlist.id, uris)
      uris.forEach((u) => onRemoved?.(u))
      toast.show(`Removed from ${playlist.name}`)
    } catch (err) {
      toast.error(err)
    }
  }

  const artist = single?.artists?.find((a) => a.uri)
  const album = single?.album?.uri ? single.album : null

  return (
    <Popover anchor={anchor} onClose={onClose} align={align} className="w-64">
      {view === 'main' ? (
        <>
          {list.length > 1 && <div className="px-3 pb-1.5 pt-2 text-xs font-semibold text-dim">{songs(list.length)}</div>}
          {extraActions.map((a) => (
            <MenuItem key={a.label} icon={a.icon} onSelect={close(a.run)}>
              {a.label}
            </MenuItem>
          ))}
          <MenuItem icon={<ListEnd />} onSelect={close(() => void queue(uris))}>
            Add to queue
          </MenuItem>
          <MenuItem icon={<ListPlus />} trailing={<ChevronRight />} onSelect={() => setView('playlists')}>
            Add to playlist
          </MenuItem>
          {(onRemove || playlist?.can_edit) && (
            <MenuItem icon={<Trash2 />} onSelect={() => void remove()}>
              {list.length > 1 ? `Remove ${songs(list.length)} from this playlist` : 'Remove from this playlist'}
            </MenuItem>
          )}
          {(album || artist) && <MenuDivider />}
          {album && !albumInLibrary(album.uri) && (
            <MenuItem icon={<LibraryBig />} onSelect={close(() => void addAlbum({ uri: album.uri }, album.name))}>
              Add album to Library
            </MenuItem>
          )}
          {album && (
            <MenuItem icon={<Disc3 />} onSelect={close(() => navigate(`/album/${idFromUri(album.uri)}`))}>
              Go to album
            </MenuItem>
          )}
          {artist && (
            <MenuItem icon={<MicVocal />} onSelect={close(() => navigate(`/artist/${idFromUri(artist.uri)}`))}>
              Go to artist
            </MenuItem>
          )}
        </>
      ) : (
        <>
          <MenuItem icon={<ChevronLeft />} onSelect={() => setView('main')}>
            <span className="text-dim">Add {list.length > 1 ? songs(list.length) : ''} to playlist</span>
          </MenuItem>
          <MenuDivider />
          <MenuItem icon={<Plus />} onSelect={close(() => openDialog({ kind: 'new' }))}>
            New playlist
          </MenuItem>
          <div className="scroll-thin max-h-72 overflow-y-auto">
            {(playlists ?? []).map((p) => (
              <button
                key={p.id}
                type="button"
                role="menuitem"
                onClick={close(() => void addTo(p, uris))}
                className="flex w-full items-center gap-3 rounded-[5px] px-2 py-1.5 text-left text-sm hover:bg-white/[0.08]"
              >
                <Artwork src={p.artwork} className="size-8 shrink-0" />
                <span className="min-w-0 flex-1 truncate">{p.name}</span>
              </button>
            ))}
            {playlists?.length === 0 && <p className="px-3 py-2 text-xs text-dim">No playlists yet.</p>}
          </div>
        </>
      )}
    </Popover>
  )
}
