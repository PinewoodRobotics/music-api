import { Download, Library, Plus } from 'lucide-react'
import { useEffect, useMemo, useState, type ReactNode } from 'react'
import type { LibrarySort, SongSort } from '../lib/api'
import { filterLibrary, type LibraryView } from '../lib/library'
import { navigate, useLocation } from '../lib/router'
import { useStoredState } from '../lib/useStoredState'
import { EmptyPlaylists } from '../components/EmptyPlaylists'
import { LibraryCard, LibraryListRow } from '../components/library/LibraryItems'
import { LibraryToolbar } from '../components/library/LibraryToolbar'
import { SongsView } from '../components/library/SongsView'
import { CardGrid } from '../components/MediaCard'
import { CardsSkeleton } from '../components/Skeleton'
import { useSession } from '../state/session'
import { useUI } from '../state/ui'
import { ErrorState, Message } from './Message'

const VIEWS = ['all', 'playlists', 'albums', 'songs'] as const
const ITEM_SORTS = [
  { value: 'recent', label: 'Recently added' },
  { value: 'name', label: 'Name' },
  { value: 'creator', label: 'Added by' },
] as const satisfies readonly { value: LibrarySort; label: string }[]
const SONG_SORTS = [
  { value: 'recent', label: 'Recently added' },
  { value: 'title', label: 'Title' },
  { value: 'artist', label: 'Artist' },
  { value: 'album', label: 'Album' },
] as const satisfies readonly { value: SongSort; label: string }[]

function Action({ icon, label, onClick, primary }: { icon: ReactNode; label: string; onClick: () => void; primary?: boolean }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`inline-flex h-10 items-center gap-2 rounded-full px-4 text-sm font-semibold transition active:scale-95 [&>svg]:size-4 ${
        primary ? 'bg-fg text-canvas hover:scale-[1.03]' : 'bg-white/10 text-fg hover:bg-white/15 active:bg-white/20'
      }`}
    >
      {icon}
      {label}
    </button>
  )
}

function useDebounced(value: string, ms: number) {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), ms)
    return () => clearTimeout(timer)
  }, [value, ms])
  return debounced
}

export function LibraryPage() {
  const { query: params } = useLocation()
  const { library, libraryAvailable, playlistsError, retryPlaylists, me } = useSession()
  const { openDialog } = useUI()
  const views: LibraryView[] = libraryAvailable ? [...VIEWS] : ['all', 'playlists']
  const requested = params.get('view') as LibraryView | null
  const view: LibraryView = requested && views.includes(requested) ? requested : 'all'
  const [query, setQuery] = useState('')
  const debouncedQuery = useDebounced(query.trim(), 250)
  const [sort, setSort] = useStoredState<LibrarySort>('librarySort', 'recent', ['recent', 'name', 'creator'])
  const [songSort, setSongSort] = useStoredState<SongSort>('librarySongSort', 'recent', ['recent', 'title', 'artist', 'album'])
  const [mine, setMine] = useStoredState<'yes' | 'no'>('libraryMine', 'no', ['yes', 'no'])
  const [layout, setLayout] = useStoredState<'grid' | 'list'>('libraryLayout', 'grid', ['grid', 'list'])

  const items = useMemo(
    () => filterLibrary(library ?? [], { view, query, mine: mine === 'yes', sort, myId: me?.id }),
    [library, view, query, mine, sort, me?.id],
  )

  const setView = (next: LibraryView) => navigate(next === 'all' ? '/' : `/?view=${next}`, { replace: true })
  const songs = view === 'songs'

  const content = () => {
    if (songs) return <SongsView q={debouncedQuery} sort={songSort} />
    if (library === null && playlistsError != null)
      return <ErrorState title="Couldn't load the Library" error={playlistsError} onRetry={retryPlaylists} />
    if (library === null) return <CardsSkeleton count={8} />
    if (library.length === 0) return <EmptyPlaylists />
    if (items.length === 0)
      return (
        <Message
          icon={<Library className="size-10" />}
          title={query ? `Nothing matches “${query}”` : mine === 'yes' ? 'You haven’t added anything here yet' : 'Nothing here yet'}
          body={view === 'albums' ? 'Add albums from Search or with Import.' : 'Try another filter.'}
        />
      )
    if (layout === 'list')
      return (
        <div className="px-1">
          {items.map((item) => (
            <LibraryListRow key={`${item.kind}:${item.id}`} item={item} />
          ))}
        </div>
      )
    return (
      <CardGrid>
        {items.map((item) => (
          <LibraryCard key={`${item.kind}:${item.id}`} item={item} />
        ))}
      </CardGrid>
    )
  }

  return (
    <div className="px-3 pb-12 pt-2 max-sm:px-2">
      <div className="mb-4 flex flex-wrap items-end justify-between gap-3 px-3 max-sm:px-2">
        <h1 className="font-display text-[clamp(1.9rem,4vw,3rem)] font-extrabold tracking-tight">Library</h1>
        <div className="flex gap-2">
          <Action primary icon={<Plus />} label="New playlist" onClick={() => openDialog({ kind: 'new' })} />
          <Action icon={<Download />} label="Import" onClick={() => openDialog({ kind: 'import' })} />
        </div>
      </div>
      <div className="mb-4">
        {songs ? (
          <LibraryToolbar views={views} view={view} onView={setView} query={query} onQuery={setQuery} sort={songSort} sortOptions={[...SONG_SORTS]} onSort={setSongSort} />
        ) : (
          <LibraryToolbar
            views={views}
            view={view}
            onView={setView}
            query={query}
            onQuery={setQuery}
            sort={sort}
            sortOptions={[...ITEM_SORTS]}
            onSort={setSort}
            mine={mine === 'yes'}
            onMine={(on) => setMine(on ? 'yes' : 'no')}
            layout={layout}
            onLayout={setLayout}
          />
        )}
      </div>
      {content()}
    </div>
  )
}
