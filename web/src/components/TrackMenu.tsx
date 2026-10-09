import { ChevronLeft, ChevronRight, Disc3, ListEnd, ListPlus, MicVocal, Plus, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { api, type AppPlaylist, type Track } from '../lib/api'
import { idFromUri } from '../lib/format'
import { navigate } from '../lib/router'
import { usePlayer } from '../state/player'
import { useSession } from '../state/session'
import { useToast } from '../state/toast'
import { useUI } from '../state/ui'
import { Artwork } from './Artwork'
import { MenuDivider, MenuItem, Popover, type AnchorRect } from './Popover'

type Props = {
  track: Track
  anchor: AnchorRect
  onClose: () => void
  playlist?: AppPlaylist
  onRemoved?: (uri: string) => void
  align?: 'start' | 'end'
}

export function TrackMenu({ track, anchor, onClose, playlist, onRemoved, align }: Props) {
  const [view, setView] = useState<'main' | 'playlists'>('main')
  const { addToQueue } = usePlayer()
  const { playlists, upsertPlaylist } = useSession()
  const { openDialog } = useUI()
  const toast = useToast()

  const addTo = async (target: AppPlaylist) => {
    onClose()
    try {
      await api.addToPlaylist(target.id, [track.uri])
      upsertPlaylist({ ...target, total: target.total + 1 })
      toast.show(`Added to ${target.name}`)
    } catch (err) {
      toast.error(err)
    }
  }

  const remove = async () => {
    if (!playlist) return
    onClose()
    try {
      await api.removeFromPlaylist(playlist.id, [track.uri])
      onRemoved?.(track.uri)
      toast.show(`Removed from ${playlist.name}`)
    } catch (err) {
      toast.error(err)
    }
  }

  const go = (path: string) => {
    onClose()
    navigate(path)
  }

  const artist = track.artists?.[0]

  return (
    <Popover anchor={anchor} onClose={onClose} align={align} className="w-64">
      {view === 'main' ? (
        <>
          <MenuItem icon={<ListEnd />} onSelect={() => {
              onClose()
              void addToQueue([track.uri])
            }}>
            Add to queue
          </MenuItem>
          <MenuItem icon={<ListPlus />} trailing={<ChevronRight />} onSelect={() => setView('playlists')}>
            Add to playlist
          </MenuItem>
          {playlist && (
            <MenuItem icon={<Trash2 />} onSelect={remove}>
              Remove from this playlist
            </MenuItem>
          )}
          {(track.album || artist) && <MenuDivider />}
          {track.album && (
            <MenuItem icon={<Disc3 />} onSelect={() => go(`/album/${idFromUri(track.album!.uri)}`)}>
              Go to album
            </MenuItem>
          )}
          {artist && (
            <MenuItem icon={<MicVocal />} onSelect={() => go(`/artist/${idFromUri(artist.uri)}`)}>
              Go to artist
            </MenuItem>
          )}
        </>
      ) : (
        <>
          <MenuItem icon={<ChevronLeft />} onSelect={() => setView('main')}>
            <span className="text-dim">Add to playlist</span>
          </MenuItem>
          <MenuDivider />
          <MenuItem icon={<Plus />} onSelect={() => {
              onClose()
              openDialog({ kind: 'new' })
            }}>
            New playlist
          </MenuItem>
          <div className="scroll-thin max-h-72 overflow-y-auto">
            {(playlists ?? []).map((p) => (
              <button
                key={p.id}
                type="button"
                role="menuitem"
                onClick={() => addTo(p)}
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
