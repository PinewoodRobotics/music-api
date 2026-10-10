import { ArrowDownUp, Check, LayoutGrid, List, Search, UserRound, X } from 'lucide-react'
import { useState, type ReactNode } from 'react'
import type { LibraryView } from '../../lib/library'
import { MenuItem, Popover, type AnchorRect } from '../Popover'

export type SortOption<T extends string> = { value: T; label: string }

type Props<T extends string> = {
  views: LibraryView[]
  view: LibraryView
  onView: (view: LibraryView) => void
  query: string
  onQuery: (query: string) => void
  sort: T
  sortOptions: SortOption<T>[]
  onSort: (sort: T) => void
  mine?: boolean
  onMine?: (mine: boolean) => void
  layout?: 'grid' | 'list'
  onLayout?: (layout: 'grid' | 'list') => void
}

const VIEW_LABELS: Record<LibraryView, string> = { all: 'All', playlists: 'Playlists', albums: 'Albums', songs: 'Songs' }

export function Chip({ active, onClick, children }: { active: boolean; onClick: () => void; children: ReactNode }) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={`inline-flex h-8 shrink-0 items-center gap-1.5 rounded-full px-3.5 text-sm font-medium transition active:scale-95 ${
        active ? 'bg-fg text-canvas' : 'bg-white/[0.08] text-fg hover:bg-white/[0.14]'
      }`}
    >
      {children}
    </button>
  )
}

export function LibraryToolbar<T extends string>(props: Props<T>) {
  const { views, view, onView, query, onQuery, sort, sortOptions, onSort, mine, onMine, layout, onLayout } = props
  const [sortMenu, setSortMenu] = useState<AnchorRect | null>(null)
  const sortLabel = sortOptions.find((o) => o.value === sort)?.label
  return (
    <div className="flex flex-wrap items-center gap-2 px-3 max-sm:px-2">
      <div className="no-scrollbar -mx-1 flex min-w-0 gap-2 overflow-x-auto px-1">
        {views.map((v) => (
          <Chip key={v} active={view === v} onClick={() => onView(v)}>
            {VIEW_LABELS[v]}
          </Chip>
        ))}
        {onMine && (
          <Chip active={!!mine} onClick={() => onMine(!mine)}>
            <UserRound className="size-3.5" />
            Mine
          </Chip>
        )}
      </div>
      <div className="ml-auto flex items-center gap-1.5 max-md:w-full">
        <label className="flex h-9 min-w-0 items-center gap-2 rounded-full bg-white/[0.08] px-3 focus-within:ring-2 focus-within:ring-white/25 max-md:flex-1 md:w-56">
          <Search className="size-4 shrink-0 text-dim" />
          <input
            value={query}
            onChange={(e) => onQuery(e.target.value)}
            placeholder={view === 'songs' ? 'Search songs' : 'Search in Library'}
            aria-label={view === 'songs' ? 'Search songs' : 'Search in Library'}
            className="w-0 min-w-0 flex-1 bg-transparent text-base text-fg outline-none placeholder:text-faint md:text-sm"
          />
          {query && (
            <button type="button" aria-label="Clear" onClick={() => onQuery('')} className="text-dim hover:text-fg">
              <X className="size-4" />
            </button>
          )}
        </label>
        <button
          type="button"
          onClick={(e) => setSortMenu(e.currentTarget.getBoundingClientRect())}
          className="inline-flex h-9 shrink-0 items-center gap-1.5 rounded-full px-3 text-sm text-dim hover:bg-white/[0.08] hover:text-fg"
          aria-label={`Sort: ${sortLabel}`}
        >
          <ArrowDownUp className="size-4" />
          <span className="max-sm:hidden">{sortLabel}</span>
        </button>
        {onLayout && (
          <div className="flex shrink-0 rounded-full bg-white/[0.06] p-0.5 max-md:hidden">
            {(['grid', 'list'] as const).map((l) => (
              <button
                key={l}
                type="button"
                aria-label={l === 'grid' ? 'Grid view' : 'List view'}
                aria-pressed={layout === l}
                onClick={() => onLayout(l)}
                className={`grid size-8 place-items-center rounded-full transition ${layout === l ? 'bg-white/15 text-fg' : 'text-dim hover:text-fg'}`}
              >
                {l === 'grid' ? <LayoutGrid className="size-4" /> : <List className="size-4" />}
              </button>
            ))}
          </div>
        )}
      </div>
      {sortMenu && (
        <Popover anchor={sortMenu} align="end" onClose={() => setSortMenu(null)}>
          {sortOptions.map((o) => (
            <MenuItem
              key={o.value}
              trailing={o.value === sort ? <Check /> : undefined}
              onSelect={() => {
                onSort(o.value)
                setSortMenu(null)
              }}
            >
              {o.label}
            </MenuItem>
          ))}
        </Popover>
      )}
    </div>
  )
}
