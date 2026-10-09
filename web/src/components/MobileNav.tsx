import { Home, Library, Search } from 'lucide-react'
import { useLocation } from '../lib/router'
import { Link } from './Link'

const tabs = [
  { href: '/', label: 'Home', icon: Home, match: (p: string) => p === '/' },
  { href: '/search', label: 'Search', icon: Search, match: (p: string) => p === '/search' },
  { href: '/library', label: 'Playlists', icon: Library, match: (p: string) => p === '/library' || p.startsWith('/playlist/') },
]

export function MobileNav() {
  const { path } = useLocation()
  return (
    <nav className="grid grid-cols-3 bg-gradient-to-t from-black via-black/95 to-black/80 pb-[env(safe-area-inset-bottom)] md:hidden">
      {tabs.map(({ href, label, icon: Icon, match }) => {
        const active = match(path)
        return (
          <Link key={href} href={href} className={`flex flex-col items-center gap-1 py-2.5 text-[11px] ${active ? 'text-fg' : 'text-dim'}`}>
            <Icon className="size-6" strokeWidth={active ? 2.4 : 1.8} />
            {label}
          </Link>
        )
      })}
    </nav>
  )
}
