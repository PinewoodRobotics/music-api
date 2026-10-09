import { Clock3, Loader2, MoreHorizontal, Play } from 'lucide-react'
import { useState, type MouseEvent } from 'react'
import type { AppPlaylist, Track } from '../lib/api'
import { isTouch } from '../lib/device'
import { byline, formatTime, idFromUri } from '../lib/format'
import { usePlayer } from '../state/player'
import { Artwork } from './Artwork'
import { Equalizer } from './Equalizer'
import { Link } from './Link'
import { pointRect, type AnchorRect } from './Popover'
import { TrackMenu } from './TrackMenu'

type Props = {
  tracks: Track[]
  onPlay: (index: number) => void
  context: string
  playlist?: AppPlaylist
  onRemoved?: (uri: string) => void
  showArt?: boolean
  showAlbum?: boolean
  numbered?: boolean
  header?: boolean
}

const touch = isTouch

export function TrackList({ tracks, onPlay, context, playlist, onRemoved, showArt = true, showAlbum = true, numbered = true, header = true }: Props) {
  const { status, isPlaying, pending } = usePlayer()
  const [selected, setSelected] = useState<number | null>(null)
  const [menu, setMenu] = useState<{ index: number; anchor: AnchorRect; align: 'start' | 'end' } | null>(null)

  const cols = [
    numbered ? '2rem' : null,
    'minmax(0,1.4fr)',
    showAlbum ? 'minmax(0,1fr)' : null,
    '3.5rem',
    '2rem',
  ]
    .filter(Boolean)
    .join(' ')
  const grid = { gridTemplateColumns: cols }

  const openMenu = (index: number, e: MouseEvent, fromButton: boolean) => {
    e.preventDefault()
    e.stopPropagation()
    const anchor = fromButton ? (e.currentTarget as HTMLElement).getBoundingClientRect() : pointRect(e.clientX, e.clientY)
    setMenu({ index, anchor, align: fromButton ? 'end' : 'start' })
  }

  return (
    <div role="table" className="select-none" onBlur={(e) => !e.currentTarget.contains(e.relatedTarget) && setSelected(null)}>
      {header && (
      <div
        role="row"
        className="mb-2 grid items-center gap-4 border-b border-white/[0.07] px-4 pb-2 text-xs text-dim max-md:hidden"
        style={grid}
      >
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
        const active = selected === i || menu?.index === i
        return (
          <div
            key={`${track.uri}-${i}`}
            role="row"
            tabIndex={0}
            onClick={() => (touch() ? onPlay(i) : setSelected(i))}
            onDoubleClick={() => onPlay(i)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') onPlay(i)
            }}
            onContextMenu={(e) => openMenu(i, e, false)}
            className={`group grid h-14 items-center gap-4 rounded-md px-4 outline-none max-md:px-2 max-md:!grid-cols-[minmax(0,1fr)_2.75rem_2.75rem] max-md:gap-1 max-md:h-16 ${
              active ? 'bg-white/[0.1]' : 'hover:bg-white/[0.05] focus-visible:bg-white/[0.07] active:bg-white/[0.08]'
            }`}
            style={grid}
          >
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
                    <span className="grid h-4 shrink-0 place-items-center rounded-[3px] bg-white/25 px-1 text-[9px] font-semibold text-canvas">
                      E
                    </span>
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
            <div className="text-right text-sm text-dim tabular max-md:text-xs">{formatTime(track.duration_ms)}</div>
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
        />
      )}
    </div>
  )
}
