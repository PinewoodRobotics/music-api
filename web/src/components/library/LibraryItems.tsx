import { Copy, Disc3, ListEnd, ListMusic, MoreHorizontal, Play, Trash2 } from 'lucide-react'
import { useCallback, type HTMLAttributes, type MouseEvent } from 'react'
import { api, type LibraryItem } from '../../lib/api'
import { plural } from '../../lib/format'
import { albumYear, itemHref, QUEUE_CAP, tracksOf, useLibraryActions } from '../../lib/library'
import { navigate } from '../../lib/router'
import { usePlayer } from '../../state/player'
import { useToast } from '../../state/toast'
import { useUI } from '../../state/ui'
import { Artwork } from '../Artwork'
import { Attribution } from '../Attribution'
import { MediaCard } from '../MediaCard'
import { MenuDivider, MenuItem, Popover, type AnchorRect } from '../Popover'

export type ItemSelection = { props: HTMLAttributes<HTMLDivElement> & { 'data-row-index': number }; selected: boolean; openMenu: (e: MouseEvent) => void }

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

export function usePlayItem() {
  const { status, isPlaying, togglePlay, start, pending } = usePlayer()
  return useCallback(
    (item: LibraryItem) => {
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
    },
    [status?.context?.uri, isPlaying, togglePlay, start, pending],
  )
}

export function useLibraryBulk() {
  const playItem = usePlayItem()
  const { addToQueue } = usePlayer()
  const { removeAlbum, duplicatePlaylist } = useLibraryActions()
  const { openDialog } = useUI()
  const toast = useToast()
  return {
    play: (items: LibraryItem[]) => items[0] && playItem(items[0]).play(),
    queue: async (items: LibraryItem[]) => {
      try {
        const { tracks, capped } = await tracksOf(items)
        if (!tracks.length) return toast.show('Nothing to queue')
        await addToQueue(tracks.map((t) => t.uri))
        if (capped) toast.show(`Queued the first ${QUEUE_CAP} songs`)
      } catch (err) {
        toast.error(err)
      }
    },
    duplicate: (items: LibraryItem[]) => items.forEach((i) => i.kind === 'playlist' && void duplicatePlaylist(i.id, i.name)),
    remove: (items: LibraryItem[]) => {
      if (items.length === 1 && items[0].kind === 'album' && items[0].can_edit) return void removeAlbum(items[0])
      if (items.length === 1 && items[0].kind === 'playlist' && items[0].can_edit) return openDialog({ kind: 'delete', playlist: items[0] })
      openDialog({ kind: 'remove-items', items })
    },
  }
}

export function LibraryCard({ item, selection }: { item: LibraryItem; selection?: ItemSelection }) {
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
      selectable={selection && { props: selection.props, selected: selection.selected }}
    />
  )
}

export function LibraryItemMenu({ items, anchor, onClose }: { items: LibraryItem[]; anchor: AnchorRect; onClose: () => void }) {
  const bulk = useLibraryBulk()
  const single = items.length === 1 ? items[0] : null
  const editable = items.filter((i) => i.can_edit)
  const playlists = items.filter((i) => i.kind === 'playlist')
  const run = (fn: () => void) => () => {
    onClose()
    fn()
  }
  const removeLabel = single
    ? single.kind === 'album'
      ? 'Remove from Library'
      : 'Delete playlist'
    : `Remove ${editable.length} from Library`
  return (
    <Popover anchor={anchor} onClose={onClose} align="end">
      {!single && <div className="px-3 pb-1.5 pt-2 text-xs font-semibold text-dim">{plural(items.length, 'item')}</div>}
      <MenuItem icon={<Play />} onSelect={run(() => bulk.play(items))}>
        {single ? 'Play' : `Play ${items[0].name}`}
      </MenuItem>
      <MenuItem icon={<ListEnd />} onSelect={run(() => void bulk.queue(items))}>
        Add to queue
      </MenuItem>
      {single && (
        <MenuItem icon={single.kind === 'album' ? <Disc3 /> : <ListMusic />} onSelect={run(() => navigate(itemHref(single)))}>
          Open {single.kind}
        </MenuItem>
      )}
      {playlists.length > 0 && (
        <MenuItem icon={<Copy />} onSelect={run(() => bulk.duplicate(playlists))}>
          {playlists.length === 1 ? 'Duplicate playlist' : `Duplicate ${playlists.length} playlists`}
        </MenuItem>
      )}
      {editable.length > 0 && (
        <>
          <MenuDivider />
          <MenuItem danger icon={<Trash2 />} onSelect={run(() => bulk.remove(items))}>
            {removeLabel}
          </MenuItem>
          {editable.length < items.length && (
            <p className="px-3 pb-2 text-xs text-dim">
              {items.length - editable.length} of {items.length} can't be removed
            </p>
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

export function LibraryListRow({ item, selection }: { item: LibraryItem; selection: ItemSelection }) {
  const playState = usePlayItem()(item)
  return (
    <div
      role="row"
      tabIndex={0}
      {...selection.props}
      className={`group relative grid cursor-pointer grid-cols-[3rem_minmax(0,1fr)_7rem_5rem_2.5rem] items-center gap-4 rounded-md px-3 py-2 outline-none max-md:grid-cols-[3rem_minmax(0,1fr)_2.75rem] ${
        selection.selected ? 'bg-white/[0.12]' : 'hover:bg-white/[0.05] focus-visible:bg-white/[0.07] active:bg-white/[0.08]'
      }`}
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
      <button
        type="button"
        aria-label={`More options for ${item.name}`}
        onClick={(e) => {
          e.stopPropagation()
          selection.openMenu(e)
        }}
        className={`grid size-9 place-items-center rounded-full text-dim hover:text-fg active:bg-white/10 [@media(hover:none)]:visible ${
          selection.selected ? '' : 'md:invisible md:group-hover:visible'
        }`}
      >
        <MoreHorizontal className="size-5" />
      </button>
    </div>
  )
}
