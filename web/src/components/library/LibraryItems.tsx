import { Copy, Disc3, ListMusic, MoreHorizontal, Play, Trash2 } from 'lucide-react'
import { useState, type MouseEvent } from 'react'
import { api, type LibraryItem } from '../../lib/api'
import { plural } from '../../lib/format'
import { albumYear, itemHref, useLibraryActions } from '../../lib/library'
import { navigate } from '../../lib/router'
import { usePlayer } from '../../state/player'
import { useUI } from '../../state/ui'
import { Artwork } from '../Artwork'
import { Attribution } from '../Attribution'
import { Link } from '../Link'
import { MediaCard } from '../MediaCard'
import { MenuDivider, MenuItem, Popover, pointRect, type AnchorRect } from '../Popover'

export function KindBadge({ kind }: { kind: LibraryItem['kind'] }) {
  return (
    <span className="inline-flex shrink-0 items-center gap-1 rounded-[4px] bg-white/[0.08] px-1.5 py-px text-[10px] font-semibold uppercase leading-4 tracking-wide text-dim">
      {kind === 'album' ? <Disc3 className="size-3" /> : <ListMusic className="size-3" />}
      {kind === 'album' ? 'Album' : 'Playlist'}
    </span>
  )
}

export function ItemSubtitle({ item, className = '' }: { item: LibraryItem; className?: string }) {
  if (item.kind === 'album')
    return (
      <span className={`truncate ${className}`}>
        {item.artists.map((a) => a.name).join(', ')}
        {albumYear(item) && ` · ${albumYear(item)}`}
      </span>
    )
  if (!item.created_by && !item.source_url) return <span className={className}>{plural(item.total, 'song')}</span>
  return <Attribution person={item.created_by} sourceUrl={item.source_url} className={className} />
}

function usePlayItem() {
  const { status, isPlaying, togglePlay, start, pending } = usePlayer()
  return (item: LibraryItem) => {
    const current = status?.context?.uri === item.uri
    return {
      playing: current && isPlaying,
      pending: pending === item.uri,
      play: () =>
        current
          ? togglePlay()
          : void start(
              item.uri,
              () => (item.kind === 'album' ? api.play({ uri: item.uri, shuffle: false }) : api.playPlaylist(item.id, { shuffle: false })),
              false,
            ),
    }
  }
}

export function LibraryCard({ item }: { item: LibraryItem }) {
  const playState = usePlayItem()(item)
  return (
    <MediaCard
      title={item.name}
      subtitle={
        <span className="flex min-w-0 items-center gap-1.5">
          <KindBadge kind={item.kind} />
          <ItemSubtitle item={item} className="min-w-0" />
        </span>
      }
      artwork={item.artwork}
      href={itemHref(item)}
      playing={playState.playing}
      pending={playState.pending}
      onPlay={playState.play}
    />
  )
}

export function LibraryItemMenu({ item, anchor, onClose }: { item: LibraryItem; anchor: AnchorRect; onClose: () => void }) {
  const playState = usePlayItem()(item)
  const { removeAlbum, duplicatePlaylist } = useLibraryActions()
  const { openDialog } = useUI()
  const run = (fn: () => void) => () => {
    onClose()
    fn()
  }
  return (
    <Popover anchor={anchor} onClose={onClose} align="end">
      <MenuItem icon={<Play />} onSelect={run(playState.play)}>
        Play
      </MenuItem>
      <MenuItem icon={item.kind === 'album' ? <Disc3 /> : <ListMusic />} onSelect={run(() => navigate(itemHref(item)))}>
        Open {item.kind}
      </MenuItem>
      {item.kind === 'playlist' && (
        <MenuItem icon={<Copy />} onSelect={run(() => void duplicatePlaylist(item.id, item.name))}>
          Duplicate playlist
        </MenuItem>
      )}
      {item.can_edit && (
        <>
          <MenuDivider />
          {item.kind === 'album' ? (
            <MenuItem danger icon={<Trash2 />} onSelect={run(() => void removeAlbum(item))}>
              Remove from Library
            </MenuItem>
          ) : (
            <MenuItem danger icon={<Trash2 />} onSelect={run(() => openDialog({ kind: 'delete', playlist: item }))}>
              Delete playlist
            </MenuItem>
          )}
        </>
      )}
    </Popover>
  )
}

function addedLabel(item: LibraryItem) {
  const at = item.kind === 'album' ? item.added : item.created
  if (!at) return ''
  const date = new Date(at)
  const days = Math.floor((Date.now() - date.getTime()) / 86_400_000)
  if (days < 1) return 'Today'
  if (days < 7) return `${days} day${days === 1 ? '' : 's'} ago`
  return date.toLocaleDateString([], { month: 'short', day: 'numeric', year: date.getFullYear() === new Date().getFullYear() ? undefined : 'numeric' })
}

export function LibraryListRow({ item }: { item: LibraryItem }) {
  const [menu, setMenu] = useState<AnchorRect | null>(null)
  const playState = usePlayItem()(item)
  const open = (e: MouseEvent) => {
    e.preventDefault()
    setMenu(e.type === 'contextmenu' ? pointRect(e.clientX, e.clientY) : (e.currentTarget as HTMLElement).getBoundingClientRect())
  }
  return (
    <div className="group relative">
      <Link
        href={itemHref(item)}
        onContextMenu={open}
        onDoubleClick={(e) => {
          e.preventDefault()
          playState.play()
        }}
        className="grid grid-cols-[3rem_minmax(0,1fr)_7rem_5rem_2.5rem] items-center gap-4 rounded-md px-3 py-2 hover:bg-white/[0.05] active:bg-white/[0.08] max-md:grid-cols-[3rem_minmax(0,1fr)_2.75rem]"
      >
        <Artwork src={item.artwork} className="size-12" />
        <div className="min-w-0">
          <div className={`truncate text-[15px] ${playState.playing ? 'text-accent' : ''}`}>{item.name}</div>
          <div className="mt-0.5 flex min-w-0 items-center gap-1.5 text-[13px] text-dim">
            <KindBadge kind={item.kind} />
            <ItemSubtitle item={item} className="min-w-0" />
          </div>
        </div>
        <span className="text-sm text-dim max-md:hidden">{addedLabel(item)}</span>
        <span className="text-right text-sm text-dim tabular max-md:hidden">{plural(item.total, 'song')}</span>
        <span />
      </Link>
      <button
        type="button"
        aria-label={`More options for ${item.name}`}
        onClick={open}
        className="absolute right-3 top-1/2 grid size-9 -translate-y-1/2 place-items-center rounded-full text-dim hover:text-fg active:bg-white/10 md:invisible md:group-hover:visible [@media(hover:none)]:visible"
      >
        <MoreHorizontal className="size-5" />
      </button>
      {menu && <LibraryItemMenu item={item} anchor={menu} onClose={() => setMenu(null)} />}
    </div>
  )
}
