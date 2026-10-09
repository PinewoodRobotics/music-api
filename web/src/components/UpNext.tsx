import { useEffect, useState, type MouseEvent } from 'react'
import { api, type Person, type QueueEntry, type Track } from '../lib/api'
import { byline, formatTime } from '../lib/format'
import { usePlayer } from '../state/player'
import { Artwork } from './Artwork'
import { Avatar } from './Avatar'
import { Equalizer } from './Equalizer'
import { RowsSkeleton } from './Skeleton'
import { pointRect, type AnchorRect } from './Popover'
import { TrackMenu } from './TrackMenu'

function Row({ track, current, playing, pending, addedBy, onMenu, onPlay }: { track: Track; current?: boolean; playing?: boolean; pending?: boolean; addedBy?: Person | null; onMenu: (e: MouseEvent) => void; onPlay?: () => void }) {
  return (
    <div
      onContextMenu={onMenu}
      onClick={onPlay}
      title={onPlay ? 'Play now' : undefined}
      className={`group flex items-center gap-3 rounded-md px-2 py-1.5 hover:bg-white/[0.06] ${onPlay ? 'cursor-pointer' : ''} ${pending ? 'opacity-60' : ''}`}
    >
      <div className="relative shrink-0">
        <Artwork src={track.artwork} className="size-11 rounded-[4px]" />
        {pending && (
          <span className="absolute inset-0 grid place-items-center rounded-[4px] bg-black/50">
            <span className="size-4 animate-spin rounded-full border-2 border-white/30 border-t-white" />
          </span>
        )}
        {current && (
          <span className="absolute inset-0 grid place-items-center rounded-[4px] bg-black/50">
            <Equalizer playing={playing} />
          </span>
        )}
      </div>
      <div className="min-w-0 flex-1">
        <div className={`truncate text-sm ${current ? 'text-accent' : 'text-fg'}`}>{track.name}</div>
        <div className="truncate text-[13px] text-white/60">{byline(track)}</div>
        {addedBy && (
          <div className="mt-0.5 flex items-center gap-1.5 text-[11px] text-white/45">
            <Avatar person={addedBy} className="size-3.5 text-[8px]" />
            <span className="truncate">{addedBy.name}</span>
          </div>
        )}
      </div>
      <span className="shrink-0 text-xs text-white/50 tabular">{formatTime(track.duration_ms)}</span>
    </div>
  )
}

function groupTitle(entry: QueueEntry, contextName: string | undefined) {
  if (entry.source === 'queue') return 'Next in queue'
  if (entry.source === 'autoplay') return 'Autoplay'
  return contextName ? `Next from ${contextName}` : 'Next up'
}

export function UpNext() {
  const { status, queue, isPlaying, refreshQueue } = usePlayer()
  useEffect(refreshQueue, [refreshQueue])
  const [jumping, setJumping] = useState<string | null>(null)
  const [menu, setMenu] = useState<{ track: Track; anchor: AnchorRect } | null>(null)
  const upcoming = (queue?.upcoming ?? []).filter((e): e is QueueEntry & { item: Track } => !!e.item)
  const groups: { title: string; entries: typeof upcoming }[] = []
  for (const entry of upcoming) {
    const title = groupTitle(entry, status?.context?.name)
    const last = groups[groups.length - 1]
    if (last?.title === title) last.entries.push(entry)
    else groups.push({ title, entries: [entry] })
  }
  const openMenu = (track: Track) => (e: MouseEvent) => {
    e.preventDefault()
    setMenu({ track, anchor: pointRect(e.clientX, e.clientY) })
  }

  return (
    <div className="scroll-thin h-full overflow-y-auto px-3 pb-6">
      {status?.track && (
        <section className="mb-4">
          <h3 className="px-2 pb-2 pt-1 text-sm font-semibold text-white/90">Now playing</h3>
          <Row track={status.track} current playing={isPlaying} onMenu={openMenu(status.track)} />
        </section>
      )}
      {groups.map((g, i) => (
        <section key={i} className="mb-4">
          <h3 className="truncate px-2 pb-2 text-sm font-semibold text-white/90">{g.title}</h3>
          {g.entries.map((e, j) => (
            <Row
              key={e.uid ?? `${e.item.uri}-${j}`}
              track={e.item}
              addedBy={e.added_by}
              onMenu={openMenu(e.item)}
              pending={jumping === (e.uid ?? `${upcoming.indexOf(e)}`)}
              onPlay={jumping ? undefined : () => {
                const key = e.uid ?? `${upcoming.indexOf(e)}`
                setJumping(key)
                api.jumpTo({ uid: e.uid, index: upcoming.indexOf(e) }).catch(() => {}).finally(() => { setJumping(null); refreshQueue() })
              }}
            />
          ))}
        </section>
      ))}
      {!queue && <RowsSkeleton count={6} />}
      {queue && !status?.track && !upcoming.length && <p className="px-2 py-8 text-center text-sm text-white/55">Nothing queued.</p>}
      {status?.track && !upcoming.length && queue && (
        <p className="px-2 py-4 text-sm text-white/55">Nothing else is queued. Add songs from any track menu.</p>
      )}
      {menu && <TrackMenu track={menu.track} anchor={menu.anchor} onClose={() => setMenu(null)} />}
    </div>
  )
}
