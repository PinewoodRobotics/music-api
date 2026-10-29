import { Library, Search } from 'lucide-react'
import type { ComponentType } from 'react'
import { filterLibrary, itemHref } from '../lib/library'
import { useLocation } from '../lib/router'
import { useStoredState } from '../lib/useStoredState'
import { focusSearch } from '../lib/searchFocus'
import { embed } from '../lib/embed'
import { useSession } from '../state/session'
import { Brand } from './Brand'
import { Link } from './Link'
import { PlaylistActions } from './PlaylistActions'
import { LibrarySidebarRow } from './PlaylistRow'

function NavItem({ href, label, icon: Icon, active }: { href: string; label: string; icon: ComponentType<{ className?: string; strokeWidth?: number }>; active: boolean }) {
  return (
    <Link
      href={href}
      onClick={(e) => {
        if (active && href === '/search' && focusSearch()) e.preventDefault()
      }}
      className={`flex items-center gap-4 rounded-md px-3 py-2 text-[15px] font-semibold transition-colors ${active ? 'text-fg' : 'text-dim hover:text-fg'}`}
    >
      <Icon className="size-6" strokeWidth={active ? 2.4 : 2} />
      {label}
    </Link>
  )
}

const SIDEBAR_VIEWS = [
  { value: 'all', label: 'All' },
  { value: 'playlists', label: 'Playlists' },
  { value: 'albums', label: 'Albums' },
] as const

export function Sidebar() {
  const { path } = useLocation()
  const { library, libraryAvailable, playlistsError, retryPlaylists, me } = useSession()
  const [view, setView] = useStoredState<'all' | 'playlists' | 'albums'>('sidebarView', 'all', ['all', 'playlists', 'albums'])
  const items = filterLibrary(library ?? [], { view, query: '', mine: false, sort: 'recent', myId: me?.id })
  return (
    <aside data-ui="sidebar" className="hidden w-[280px] shrink-0 flex-col gap-2 md:flex">
      <div className="rounded-lg bg-panel px-3 pb-3 pt-4">
        <div className="mb-4 px-3">
          <Link href="/" aria-label="Library" className="block rounded-md">
            <Brand />
          </Link>
        </div>
        <NavItem href="/search" label="Search" icon={Search} active={path === '/search'} />
      </div>
      <div className="flex min-h-0 flex-1 flex-col rounded-lg bg-panel">
        <Link href="/" className={`flex items-center gap-2 px-5 pb-2 pt-4 text-[15px] font-semibold hover:underline ${path === '/' ? 'text-fg' : 'text-fg/90'}`}>
          <Library className="size-5" />
          Library
        </Link>
        {libraryAvailable && (
          <div className="flex gap-1.5 px-4 pb-2">
            {SIDEBAR_VIEWS.map((v) => (
              <button
                key={v.value}
                type="button"
                aria-pressed={view === v.value}
                onClick={() => setView(v.value)}
                className={`h-7 rounded-full px-3 text-xs font-medium transition ${view === v.value ? 'bg-fg text-canvas' : 'bg-white/[0.08] text-fg hover:bg-white/[0.14]'}`}
              >
                {v.label}
              </button>
            ))}
          </div>
        )}
        <div className="scroll-thin min-h-0 flex-1 overflow-y-auto px-2 pb-2">
          {!embed && <PlaylistActions compact />}
          {!embed && items.length > 0 && <div className="mx-2 my-2 h-px bg-white/[0.06]" />}
          {items.map((item) => (
            <LibrarySidebarRow key={`${item.kind}:${item.id}`} item={item} active={path === itemHref(item)} />
          ))}
          {library === null && playlistsError != null && (
            <button type="button" onClick={retryPlaylists} className="w-full px-3 py-3 text-left text-sm text-dim hover:text-fg">
              Couldn't load the Library. <span className="underline">Try again</span>
            </button>
          )}
          {library === null && playlistsError == null && (
            <div className="space-y-2 p-1.5">
              {[0, 1, 2].map((i) => (
                <div key={i} className="flex items-center gap-3">
                  <div className="size-11 animate-pulse rounded-[6px] bg-white/[0.06]" />
                  <div className="h-3 w-28 animate-pulse rounded bg-white/[0.06]" />
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </aside>
  )
}
