import { Search } from 'lucide-react'
import type { ComponentType } from 'react'
import { useLocation } from '../lib/router'
import { useSession } from '../state/session'
import { Brand } from './Brand'
import { Link } from './Link'
import { PlaylistActions } from './PlaylistActions'
import { PlaylistRow } from './PlaylistRow'

function NavItem({ href, label, icon: Icon, active }: { href: string; label: string; icon: ComponentType<{ className?: string; strokeWidth?: number }>; active: boolean }) {
  return (
    <Link
      href={href}
      className={`flex items-center gap-4 rounded-md px-3 py-2 text-[15px] font-semibold transition-colors ${active ? 'text-fg' : 'text-dim hover:text-fg'}`}
    >
      <Icon className="size-6" strokeWidth={active ? 2.4 : 2} />
      {label}
    </Link>
  )
}

export function Sidebar() {
  const { path } = useLocation()
  const { playlists, playlistsError, retryPlaylists } = useSession()
  return (
    <aside className="hidden w-[280px] shrink-0 flex-col gap-2 md:flex">
      <div className="rounded-lg bg-panel px-3 pb-3 pt-4">
        <div className="mb-4 px-3">
          <Link href="/" aria-label="Playlists" className="block rounded-md">
            <Brand />
          </Link>
        </div>
        <NavItem href="/search" label="Search" icon={Search} active={path === '/search'} />
      </div>
      <div className="flex min-h-0 flex-1 flex-col rounded-lg bg-panel">
        <Link href="/" className={`px-5 pb-2 pt-4 text-[15px] font-semibold hover:underline ${path === '/' ? 'text-fg' : 'text-fg/90'}`}>
          Playlists
        </Link>
        <div className="scroll-thin min-h-0 flex-1 overflow-y-auto px-2 pb-2">
          <PlaylistActions compact />
          {playlists && playlists.length > 0 && <div className="mx-2 my-2 h-px bg-white/[0.06]" />}
          {playlists?.map((p) => <PlaylistRow key={p.id} playlist={p} active={path === `/playlist/${p.id}`} />)}
          {playlists === null && playlistsError != null && (
            <button type="button" onClick={retryPlaylists} className="w-full px-3 py-3 text-left text-sm text-dim hover:text-fg">
              Couldn't load playlists. <span className="underline">Try again</span>
            </button>
          )}
          {playlists === null && playlistsError == null && (
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
