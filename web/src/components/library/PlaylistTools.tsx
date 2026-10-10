import { Check, Loader2, Plus, Search, X } from 'lucide-react'
import { useEffect, useState } from 'react'
import { api, type AppPlaylist, type Track } from '../../lib/api'
import { byline, formatTime } from '../../lib/format'
import { useSession } from '../../state/session'
import { Artwork } from '../Artwork'
import { Popover, type AnchorRect } from '../Popover'

export function PlaylistPicker({ anchor, exclude, onPick, onClose }: { anchor: AnchorRect; exclude?: string; onPick: (p: AppPlaylist) => void; onClose: () => void }) {
  const { playlists } = useSession()
  const options = (playlists ?? []).filter((p) => p.id !== exclude)
  return (
    <Popover anchor={anchor} onClose={onClose} align="start" className="w-64">
      <div className="px-3 pb-1 pt-2 text-xs font-semibold text-dim">Add to playlist</div>
      <div className="scroll-thin max-h-72 overflow-y-auto">
        {options.map((p) => (
          <button
            key={p.id}
            type="button"
            role="menuitem"
            onClick={() => {
              onClose()
              onPick(p)
            }}
            className="flex w-full items-center gap-3 rounded-[5px] px-2 py-1.5 text-left text-sm hover:bg-white/[0.08]"
          >
            <Artwork src={p.artwork} className="size-8 shrink-0" />
            <span className="min-w-0 flex-1 truncate">{p.name}</span>
          </button>
        ))}
        {options.length === 0 && <p className="px-3 py-2 text-xs text-dim">No other playlists.</p>}
      </div>
    </Popover>
  )
}

export function AddSongsPanel({ playlist, existing, onAdd, onClose }: { playlist: AppPlaylist; existing: Set<string>; onAdd: (track: Track) => void; onClose: () => void }) {
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<Track[] | null>(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    const q = query.trim()
    if (!q) return setResults(null)
    let live = true
    setLoading(true)
    const timer = setTimeout(() => {
      api
        .search(q)
        .then((r) => live && setResults(r.tracks?.items.filter(Boolean) ?? []))
        .catch(() => live && setResults([]))
        .finally(() => live && setLoading(false))
    }, 250)
    return () => {
      live = false
      clearTimeout(timer)
    }
  }, [query])

  useEffect(() => {
    const key = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', key)
    return () => window.removeEventListener('keydown', key)
  }, [onClose])

  return (
    <div
      role="dialog"
      aria-label={`Add songs to ${playlist.name}`}
      className="animate-rise fixed inset-x-0 bottom-0 top-[12%] z-[55] flex flex-col overflow-hidden rounded-t-2xl bg-raised shadow-2xl shadow-black/70 md:inset-x-auto md:bottom-[96px] md:right-2 md:top-2 md:w-[420px] md:rounded-lg"
    >
      <header className="flex items-center justify-between gap-3 px-5 pb-3 pt-4">
        <div className="min-w-0">
          <h2 className="font-display text-lg font-bold tracking-tight">Add songs</h2>
          <p className="truncate text-xs text-dim">to {playlist.name}</p>
        </div>
        <button type="button" onClick={onClose} aria-label="Close" className="grid size-10 place-items-center rounded-full text-dim hover:bg-white/10 hover:text-fg">
          <X className="size-5" />
        </button>
      </header>
      <label className="mx-4 flex h-11 items-center gap-2 rounded-full bg-white/[0.08] px-4 focus-within:ring-2 focus-within:ring-white/25">
        {loading ? <Loader2 className="size-4 animate-spin text-dim" /> : <Search className="size-4 text-dim" />}
        <input
          autoFocus
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search for songs"
          aria-label="Search for songs"
          enterKeyHint="search"
          className="min-w-0 flex-1 bg-transparent text-base outline-none placeholder:text-faint"
        />
      </label>
      <div className="scroll-thin mt-3 min-h-0 flex-1 overflow-y-auto overscroll-contain px-2 pb-[max(env(safe-area-inset-bottom),12px)]">
        {!results && <p className="px-4 py-10 text-center text-sm text-dim">Search Spotify and tap + to add a song.</p>}
        {results?.length === 0 && !loading && <p className="px-4 py-10 text-center text-sm text-dim">No songs found.</p>}
        {results?.map((t) => {
          const added = existing.has(t.uri)
          return (
            <div key={t.uri} className="flex items-center gap-3 rounded-md px-2 py-1.5 hover:bg-white/[0.05]">
              <Artwork src={t.artwork} className="size-10 shrink-0 rounded-[4px]" />
              <div className="min-w-0 flex-1">
                <div className="truncate text-sm">{t.name}</div>
                <div className="truncate text-xs text-dim">
                  {byline(t)} · {formatTime(t.duration_ms)}
                </div>
              </div>
              <button
                type="button"
                disabled={added}
                onClick={() => onAdd(t)}
                aria-label={added ? `${t.name} is in the playlist` : `Add ${t.name}`}
                className={`grid size-10 shrink-0 place-items-center rounded-full transition active:scale-90 ${added ? 'text-[#34c759]' : 'text-fg ring-1 ring-white/25 hover:bg-white/10'}`}
              >
                {added ? <Check className="size-5" /> : <Plus className="size-5" />}
              </button>
            </div>
          )
        })}
      </div>
    </div>
  )
}
