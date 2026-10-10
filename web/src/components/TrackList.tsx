import { Check, Clock3, GripVertical, ListEnd, ListPlus, Loader2, MoreHorizontal, Play, Trash2 } from 'lucide-react'
import { useMemo, useRef, useState, type MouseEvent, type PointerEvent } from 'react'
import type { AppPlaylist, Track } from '../lib/api'
import { byline, formatTime, idFromUri } from '../lib/format'
import { useSelection } from '../lib/selection'
import { usePlayer } from '../state/player'
import { Artwork } from './Artwork'
import { Equalizer } from './Equalizer'
import { PlaylistPicker } from './library/PlaylistTools'
import { Link } from './Link'
import { pointRect, type AnchorRect } from './Popover'
import { SelectionBar } from './SelectionBar'
import { TrackMenu, useTrackActions } from './TrackMenu'

type Props = {
  tracks: Track[]
  onPlay: (index: number) => void
  context: string
  playlist?: AppPlaylist
  onRemoveIndices?: (indices: number[]) => void
  onReorder?: (indices: number[], to: number) => void
  showArt?: boolean
  showAlbum?: boolean
  numbered?: boolean
  header?: boolean
  editMode?: boolean
  onExitEdit?: () => void
}

type Drag = { from: number; to: number; dy: number; rowHeight: number; startY: number }

export function trackKeys(tracks: Track[]) {
  const seen = new Map<string, number>()
  return tracks.map((t) => {
    const n = seen.get(t.uri) ?? 0
    seen.set(t.uri, n + 1)
    return `${t.uri}:${n}`
  })
}

export function TrackList(props: Props) {
  const { tracks, onPlay, context, playlist, onRemoveIndices, onReorder, showArt = true, showAlbum = true, numbered = true, header = true } = props
  const { editMode = false, onExitEdit } = props
  const { status, isPlaying, pending } = usePlayer()
  const keys = useMemo(() => trackKeys(tracks), [tracks])
  const sel = useSelection(keys, { forceTouchMode: editMode })
  const { queue, addTo } = useTrackActions()
  const [menu, setMenu] = useState<{ indices: number[]; anchor: AnchorRect; align: 'start' | 'end' } | null>(null)
  const [picker, setPicker] = useState<AnchorRect | null>(null)
  const [drag, setDrag] = useState<Drag | null>(null)
  const dragRef = useRef<Drag | null>(null)
  const withHandle = !!onReorder
  const touchMode = sel.touchMode

  const cols = [withHandle || touchMode ? '1.75rem' : null, numbered ? '2rem' : null, 'minmax(0,1.4fr)', showAlbum ? 'minmax(0,1fr)' : null, '3.5rem', '2rem']
    .filter(Boolean)
    .join(' ')
  const grid = { gridTemplateColumns: cols }
  const mobileGrid = touchMode
    ? 'max-md:!grid-cols-[1.75rem_minmax(0,1fr)_2.75rem]'
    : withHandle
      ? 'max-md:!grid-cols-[0_minmax(0,1fr)_2.75rem_2.75rem]'
      : 'max-md:!grid-cols-[minmax(0,1fr)_2.75rem_2.75rem]'

  const openMenu = (indices: number[], e: MouseEvent, fromButton: boolean) => {
    e.preventDefault()
    e.stopPropagation()
    const anchor = fromButton ? (e.currentTarget as HTMLElement).getBoundingClientRect() : pointRect(e.clientX, e.clientY)
    setMenu({ indices, anchor, align: fromButton ? 'end' : 'start' })
  }

  const startDrag = (index: number, e: PointerEvent<HTMLElement>) => {
    e.preventDefault()
    e.stopPropagation()
    e.currentTarget.setPointerCapture(e.pointerId)
    const row = e.currentTarget.closest<HTMLElement>('[data-row-index]')
    const next = { from: index, to: index, dy: 0, rowHeight: row?.offsetHeight ?? 56, startY: e.clientY }
    dragRef.current = next
    setDrag(next)
  }
  const moveDrag = (e: PointerEvent<HTMLElement>) => {
    const d = dragRef.current
    if (!d) return
    const dy = e.clientY - d.startY
    const to = Math.max(0, Math.min(tracks.length - 1, d.from + Math.round(dy / d.rowHeight)))
    dragRef.current = { ...d, dy, to }
    setDrag(dragRef.current)
  }
  const endDrag = () => {
    const d = dragRef.current
    dragRef.current = null
    setDrag(null)
    if (!d || d.to === d.from) return
    const block = sel.isSelected(d.from) && sel.indices.length > 1 ? sel.indices : [d.from]
    onReorder?.(block, d.to)
  }

  const offsetFor = (i: number) => {
    if (!drag) return undefined
    if (i === drag.from) return { transform: `translateY(${drag.dy}px)`, zIndex: 10, transition: 'none' }
    if (drag.from < drag.to && i > drag.from && i <= drag.to) return { transform: `translateY(${-drag.rowHeight}px)` }
    if (drag.to < drag.from && i >= drag.to && i < drag.from) return { transform: `translateY(${drag.rowHeight}px)` }
    return undefined
  }

  const handle = (i: number, big: boolean) => (
    <button
      type="button"
      aria-label={`Drag to reorder ${tracks[i].name}`}
      onPointerDown={(e) => startDrag(i, e)}
      onPointerMove={moveDrag}
      onPointerUp={endDrag}
      onPointerCancel={endDrag}
      onClick={(e) => e.stopPropagation()}
      className={`grid cursor-grab touch-none place-items-center rounded text-dim hover:text-fg active:cursor-grabbing ${big ? 'size-11 md:size-8' : 'size-7 md:invisible md:group-hover:visible'}`}
    >
      <GripVertical className={big ? 'size-5' : 'size-4'} />
    </button>
  )

  const selectedTracks = sel.indices.map((i) => tracks[i])

  return (
    <div role="table" className="select-none" {...sel.rootProps({ primary: (ix) => onPlay(ix[0]), remove: onRemoveIndices })}>
      {header && (
        <div role="row" className="mb-2 grid items-center gap-4 border-b border-white/[0.07] px-4 pb-2 text-xs text-dim max-md:hidden" style={grid}>
          {(withHandle || touchMode) && <span />}
          {numbered && <span className="text-right">#</span>}
          <span>Title</span>
          {showAlbum && <span>Album</span>}
          <span className="flex justify-end pr-1">
            <Clock3 className="size-4" aria-label="Duration" />
          </span>
          <span />
        </div>
      )}
      {tracks.map((track, i) => {
        const current = status?.track?.uri === track.uri
        const starting = pending === `${context}#${i}`
        const isSelected = sel.isSelected(i)
        const active = isSelected || drag?.from === i
        const row = sel.rowProps(i, { primary: () => onPlay(i), openMenu: (e, ix) => openMenu(ix, e, false) })
        return (
          <div
            key={keys[i]}
            role="row"
            tabIndex={0}
            {...row}
            className={`group relative grid h-14 items-center gap-4 rounded-md px-4 outline-none transition-transform duration-150 max-md:h-16 max-md:gap-1 max-md:px-2 ${mobileGrid} ${
              drag?.from === i
                ? 'bg-raised shadow-xl shadow-black/40'
                : active
                  ? 'bg-white/[0.12] hover:bg-white/[0.15]'
                  : 'hover:bg-white/[0.05] focus-visible:bg-white/[0.07] active:bg-white/[0.08]'
            }`}
            style={{ ...grid, ...row.style, ...offsetFor(i) }}
          >
            {(withHandle || touchMode) && (
              <div className={`flex items-center justify-center ${touchMode ? '' : 'max-md:invisible'}`}>
                {touchMode ? (
                  <span aria-hidden className={`grid size-5 place-items-center rounded-full border ${isSelected ? 'border-accent bg-accent text-ink' : 'border-white/40'}`}>
                    {isSelected && <Check className="size-3.5" strokeWidth={3} />}
                  </span>
                ) : (
                  handle(i, false)
                )}
              </div>
            )}
            {numbered && (
              <div className="relative flex justify-end text-sm text-dim tabular max-md:hidden">
                {starting ? <Loader2 className="size-4 animate-spin text-fg" /> : <span className={`group-hover:invisible ${current ? 'hidden' : ''}`}>{i + 1}</span>}
                {current && !starting && (
                  <span className="group-hover:invisible">
                    <Equalizer playing={isPlaying} />
                  </span>
                )}
                <button
                  type="button"
                  aria-label={`Play ${track.name}`}
                  onClick={(e) => {
                    e.stopPropagation()
                    onPlay(i)
                  }}
                  className="invisible absolute -right-1 top-1/2 grid size-7 -translate-y-1/2 place-items-center text-fg group-hover:visible"
                >
                  <Play className="size-4 fill-current" strokeWidth={0} />
                </button>
              </div>
            )}
            <div className="flex min-w-0 items-center gap-3">
              {showArt && (
                <div className="relative shrink-0">
                  <Artwork src={track.artwork} className="size-10 rounded-[4px]" />
                  {(starting || (!numbered && current)) && (
                    <span className="absolute inset-0 grid place-items-center rounded-[4px] bg-black/55">
                      {starting ? <Loader2 className="size-4 animate-spin" /> : <Equalizer playing={isPlaying} />}
                    </span>
                  )}
                </div>
              )}
              <div className="min-w-0">
                <div className={`truncate text-[15px] leading-tight ${current ? 'text-accent' : 'text-fg'}`}>{track.name}</div>
                <div className="mt-0.5 flex min-w-0 items-center gap-1.5 text-[13px] text-dim">
                  {track.explicit && <span className="grid h-4 shrink-0 place-items-center rounded-[3px] bg-white/25 px-1 text-[9px] font-semibold text-canvas">E</span>}
                  <span className="truncate">
                    {track.artists?.length
                      ? track.artists.map((a, j) => (
                          <span key={a.uri}>
                            {j > 0 && ', '}
                            <Link
                              href={`/artist/${idFromUri(a.uri)}`}
                              onClick={(e) => e.stopPropagation()}
                              className="hover:text-fg hover:underline [@media(hover:none)]:pointer-events-none"
                            >
                              {a.name}
                            </Link>
                          </span>
                        ))
                      : byline(track)}
                  </span>
                </div>
              </div>
            </div>
            {showAlbum && (
              <div className="min-w-0 truncate text-sm text-dim max-md:hidden">
                {track.album && (
                  <Link
                    href={`/album/${idFromUri(track.album.uri)}`}
                    onClick={(e) => e.stopPropagation()}
                    className="hover:text-fg hover:underline [@media(hover:none)]:pointer-events-none"
                  >
                    {track.album.name}
                  </Link>
                )}
              </div>
            )}
            <div className={`text-right text-sm text-dim tabular max-md:text-xs ${touchMode ? 'max-md:hidden' : ''}`}>{formatTime(track.duration_ms)}</div>
            {touchMode && withHandle ? (
              handle(i, true)
            ) : touchMode ? (
              <span />
            ) : (
              <button
                type="button"
                aria-label={`More options for ${track.name}`}
                onClick={(e) => openMenu(sel.ensureSelected(i), e, true)}
                onDoubleClick={(e) => e.stopPropagation()}
                className={`grid size-8 place-items-center rounded-full text-dim hover:text-fg active:bg-white/10 [@media(hover:none)]:size-11 ${
                  active ? 'visible' : 'md:invisible md:group-hover:visible md:group-focus-within:visible [@media(hover:none)]:visible'
                }`}
              >
                <MoreHorizontal className="size-5" />
              </button>
            )}
          </div>
        )
      })}
      {menu && (
        <TrackMenu
          tracks={menu.indices.map((i) => tracks[i]).filter(Boolean)}
          anchor={menu.anchor}
          align={menu.align}
          onClose={() => setMenu(null)}
          playlist={playlist}
          onRemove={onRemoveIndices ? () => onRemoveIndices(menu.indices) : undefined}
        />
      )}
      {touchMode && (
        <SelectionBar
          count={selectedTracks.length}
          noun="song"
          onDone={() => {
            sel.exitTouchMode()
            onExitEdit?.()
          }}
          actions={[
            { label: 'Add to queue', icon: <ListEnd />, onClick: () => void queue(selectedTracks.map((t) => t.uri)) },
            { label: 'Add to playlist', icon: <ListPlus />, onClick: (e) => setPicker(e.currentTarget.getBoundingClientRect()) },
            ...(onRemoveIndices ? [{ label: 'Remove', icon: <Trash2 />, danger: true, onClick: () => onRemoveIndices(sel.indices) }] : []),
          ]}
        />
      )}
      {picker && (
        <PlaylistPicker
          anchor={picker}
          exclude={playlist?.id}
          onPick={(p) => void addTo(p, selectedTracks.map((t) => t.uri))}
          onClose={() => setPicker(null)}
        />
      )}
    </div>
  )
}
