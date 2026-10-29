import { X } from 'lucide-react'
import { embed } from '../lib/embed'
import { useUI } from '../state/ui'
import { Lyrics } from './Lyrics'
import { UpNext } from './UpNext'

export function SidePanel() {
  const { panel, togglePanel } = useUI()
  if (!panel) return null
  const lyrics = panel === 'lyrics'
  return (
    <aside data-ui="side-panel" className={`hidden w-[340px] shrink-0 flex-col overflow-hidden rounded-lg lg:flex ${lyrics ? 'bg-glow' : 'bg-panel'} transition-colors`}>
      <header className="flex items-center justify-between px-5 pb-2 pt-4">
        <div className="flex gap-1 rounded-full bg-black/25 p-1 text-sm font-semibold">
          {(['queue', 'lyrics'] as const).map((p) => (
            <button
              key={p}
              type="button"
              onClick={() => panel !== p && togglePanel(p)}
              className={`rounded-full px-3 py-1 transition-colors ${panel === p ? 'bg-white/90 text-black' : 'text-white/70 hover:text-white'}`}
            >
              {p === 'queue' ? 'Up next' : 'Lyrics'}
            </button>
          ))}
        </div>
        {!embed && <button type="button" aria-label="Close panel" onClick={() => togglePanel(panel)} className="grid size-8 place-items-center rounded-full text-white/70 hover:bg-white/10 hover:text-white">
          <X className="size-5" />
        </button>}
      </header>
      <div className="min-h-0 flex-1">{lyrics ? <Lyrics /> : <UpNext />}</div>
    </aside>
  )
}
