import { Check, Clock3, GripVertical, Loader2, MoreHorizontal, Play } from 'lucide-react'
import { useRef, useState, type MouseEvent, type PointerEvent } from 'react'
import type { AppPlaylist, Track } from '../lib/api'
import { isTouch } from '../lib/device'
import { byline, formatTime, idFromUri } from '../lib/format'
import { usePlayer } from '../state/player'
import { Artwork } from './Artwork'
import { Equalizer } from './Equalizer'
import { Link } from './Link'
import { pointRect, type AnchorRect } from './Popover'
import { TrackMenu } from './TrackMenu'

export type SelectModifiers = { shiftKey: boolean; metaKey: boolean; ctrlKey: boolean; toggle?: boolean }

type Props = {
  tracks: Track[]
  onPlay: (index: number) => void
  context: string
  playlist?: AppPlaylist
  onRemoved?: (uri: string) => void
  onRemoveIndex?: (index: number) => void
  showArt?: boolean
  showAlbum?: boolean
  numbered?: boolean
  header?: boolean
  selection?: { selected: Set<number>; onSelect: (index: number, modifiers: SelectModifiers) => void }
  editMode?: boolean
  onReorder?: (from: number, to: number) => void
}

type Drag = { from: number; to: number; dy: number; rowHeight: number; startY: number }

const touch = isTouch

export function TrackList(props: Props) {
  const { tracks, onPlay, context, playlist, onRemoved, onRemoveIndex, showArt = true, showAlbum = true, numbered = true, header = true } = props
  const { selection, editMode = false, onReorder } = props
  const { status, isPlaying, pending } = usePlayer()
  const [focused, setFocused] = useState<number | null>(null)
  const [menu, setMenu] = useState<{ index: number; anchor: AnchorRect; align: 'start' | 'end' } | null>(null)
  const [drag, setDrag] = useState<Drag | null>(null)
  const dragRef = useRef<Drag | null>(null)
  const withHandle = !!onReorder

  const cols = [
    withHandle || editMode ? '1.75rem' : null,
    numbered ? '2rem' : null,
    'minmax(0,1.4fr)',
    showAlbum ? 'minmax(0,1fr)' : null,
    '3.5rem',
    '2rem',
  ]
    .filter(Boolean)
    .join(' ')
  const grid = { gridTemplateColumns: cols }
  const mobileGrid = editMode
    ? 'max-md:!grid-cols-[1.75rem_minmax(0,1fr)_2.75rem]'
    : withHandle
      ? 'max-md:!grid-cols-[0_minmax(0,1fr)_2.75rem_2.75rem]'
      : 'max-md:!grid-cols-[minmax(0,1fr)_2.75rem_2.75rem]'

  const openMenu = (index: number, e: MouseEvent, fromButton: boolean) => {
    e.preventDefault()
    e.stopPropagation()
    const anchor = fromButton ? (e.currentTarget as HTMLElement).getBoundingClientRect() : pointRect(e.clientX, e.clientY)
    setMenu({ index, anchor, align: fromButton ? 'end' : 'start' })
  }

  const startDrag = (index: number, e: PointerEvent<HTMLElement>) => {
    e.preventDefault()
    e.stopPropagation()
    e.currentTarget.setPointerCapture(e.pointerId)
    const row = e.currentTarget.closest<HTMLElement>('[role="row"]')
    const next = { from: index, to: index, dy: 0, rowHeight: row?.offsetHeight ?? 56, startY: e.clientY }
    dragRef.current = next
    setDrag(next)
  }
  const moveDrag = (e: PointerEvent<HTMLElement>) => {
    const d = dragRef.current
    if (!d) return
    const dy = e.clientY - d.startY
    const to = Math.max(0, Math.min(tracks.length - 1, d.from + Math.round(dy / d.rowHeight)))
    const next = { ...d, dy, to }
    dragRef.current = next
    setDrag(next)
  }
  const endDrag = () => {
    const d = dragRef.current
    dragRef.current = null
    setDrag(null)
    if (d && d.to !== d.from) onReorder?.(d.from, d.to)
  }

  const offsetFor = (i: number) => {
    if (!drag) return undefined
    if (i === drag.from) return { transform: `translateY(${drag.dy}px)`, zIndex: 10, transition: 'none' }
    if (drag.from < drag.to && i > drag.from && i <= drag.to) return { transform: `translateY(${-drag.rowHeight}px)` }
    if (drag.to < drag.from && i >= drag.to && i < drag.from) return { transform: `translateY(${drag.rowHeight}px)` }
    return undefined
  }

  const click = (i: number, e: MouseEvent) => {
    if (selection && editMode) return selection.onSelect(i, { shiftKey: e.shiftKey, metaKey: false, ctrlKey: false, toggle: true })
    if (touch()) return onPlay(i)
    if (selection) selection.onSelect(i, e)
    else setFocused(i)
  }

  return (
    <div role="table" className="select-none" onBlur={(e) => !selection && !e.currentTarget.contains(e.relatedTarget) && setFocused(null)}>
      {header && (
        <div role="row" className="mb-2 grid items-center gap-4 border-b border-white/[0.07] px-4 pb-2 text-xs text-dim max-md:hidden" style={grid}>
          {(withHandle || editMode) && <span />}
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
        const isSelected = selection ? selection.selected.has(i) : focused === i
        const active = isSelected || menu?.index === i || drag?.from === i
        return (
          <div
            key={`${track.uri}-${i}`}
            role="row"
            aria-selected={selection ? isSelected : undefined}
            tabIndex={0}
            onClick={(e) => click(i, e)}
            onDoubleClick={() => !editMode && onPlay(i)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') onPlay(i)
            }}
            onContextMenu={(e) => openMenu(i, e, false)}
            className={`group relative grid h-14 items-center gap-4 rounded-md px-4 outline-none transition-transform duration-150 max-md:h-16 max-md:gap-1 max-md:px-2 ${mobileGrid} ${
              drag?.from === i ? 'bg-raised shadow-xl shadow-black/40' : active ? 'bg-white/[0.1]' : 'hover:bg-white/[0.05] focus-visible:bg-white/[0.07] active:bg-white/[0.08]'
            }`}
            style={{ ...grid, ...offsetFor(i) }}
          >
            {(withHandle || editMode) && (
              <div className={`flex items-center justify-center ${editMode ? '' : 'max-md:invisible'}`}>
                {editMode && selection ? (
                  <span
                    aria-hidden
                    className={`grid size-5 place-items-center rounded-full border ${isSelected ? 'border-accent bg-accent text-ink' : 'border-white/40'}`}
                  >
                    {isSelected && <Check className="size-3.5" strokeWidth={3} />}
                  </span>
                ) : withHandle ? (
                  <button
                    type="button"
                    aria-label={`Drag to reorder ${track.name}`}
                    onPointerDown={(e) => startDrag(i, e)}
                    onPointerMove={moveDrag}
                    onPointerUp={endDrag}
                    onPointerCancel={endDrag}
                    onClick={(e) => e.stopPropagation()}
                    className="grid size-7 cursor-grab touch-none place-items-center rounded text-dim hover:text-fg active:cursor-grabbing md:invisible md:group-hover:visible"
                  >
                    <GripVertical className="size-4" />
                  </button>
                ) : null}
              </div>
            )}
            {numbered && (
              <div className="relative flex justify-end text-sm text-dim tabular max-md:hidden">
                {starting ? (
                  <Loader2 className="size-4 animate-spin text-fg" />
                ) : (
                  <span className={`group-hover:invisible ${current ? 'hidden' : ''}`}>{i + 1}</span>
                )}
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
                  {track.explicit && (
                    <span className="grid h-4 shrink-0 place-items-center rounded-[3px] bg-white/25 px-1 text-[9px] font-semibold text-canvas">E</span>
                  )}
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
            <div className={`text-right text-sm text-dim tabular max-md:text-xs ${editMode ? 'max-md:hidden' : ''}`}>{formatTime(track.duration_ms)}</div>
            {editMode && withHandle ? (
              <button
                type="button"
                aria-label={`Drag to reorder ${track.name}`}
                onPointerDown={(e) => startDrag(i, e)}
                onPointerMove={moveDrag}
                onPointerUp={endDrag}
                onPointerCancel={endDrag}
                onClick={(e) => e.stopPropagation()}
                className="grid size-11 cursor-grab touch-none place-items-center text-dim active:cursor-grabbing md:size-8"
              >
                <GripVertical className="size-5" />
              </button>
            ) : (
              <button
                type="button"
                aria-label={`More options for ${track.name}`}
                onClick={(e) => openMenu(i, e, true)}
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
      {menu && tracks[menu.index] && (
        <TrackMenu
          track={tracks[menu.index]}
          anchor={menu.anchor}
          align={menu.align}
          onClose={() => setMenu(null)}
          playlist={playlist}
          onRemoved={onRemoved}
          onRemove={onRemoveIndex ? () => onRemoveIndex(menu.index) : undefined}
        />
      )}
    </div>
  )
}
