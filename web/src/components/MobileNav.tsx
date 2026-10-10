import { Library, Search } from 'lucide-react'
import { useLocation } from '../lib/router'
import { focusSearch } from '../lib/searchFocus'
import { Link } from './Link'

const tabs = [
  { href: '/', label: 'Library', icon: Library, match: (p: string) => p === '/' || p === '/library' || p.startsWith('/playlist/') },
  { href: '/search', label: 'Search', icon: Search, match: (p: string) => !(p === '/' || p === '/library' || p.startsWith('/playlist/') || p.startsWith('/album/')) },
]

export function MobileNav() {
  const { path } = useLocation()
  return (
    <nav className="grid grid-cols-2 bg-black pb-[env(safe-area-inset-bottom)] md:hidden">
      {tabs.map(({ href, label, icon: Icon, match }) => {
        const active = match(path)
        return (
          <Link
            key={href}
            href={href}
            onClick={(e) => {
              if (href === '/search' && path === '/search' && focusSearch()) e.preventDefault()
            }}
            className={`flex min-h-14 flex-col items-center justify-center gap-1 pb-1 pt-2 text-[11px] font-medium transition-colors active:opacity-60 ${active ? 'text-fg' : 'text-dim'}`}
          >
            <Icon className="size-6" strokeWidth={active ? 2.4 : 1.8} />
            {label}
          </Link>
        )
      })}
    </nav>
  )
}
