import { Download, Plus } from 'lucide-react'
import { useUI } from '../state/ui'

export function PlaylistActions({ compact = false }: { compact?: boolean }) {
  const { openDialog } = useUI()
  const tile = compact ? 'size-10' : 'size-11'
  const items = [
    { label: 'New playlist', icon: Plus, onClick: () => openDialog({ kind: 'new' }) },
    { label: 'Import', icon: Download, onClick: () => openDialog({ kind: 'import' }) },
  ]
  return (
    <div className="space-y-0.5">
      {items.map(({ label, icon: Icon, onClick }) => (
        <button
          key={label}
          type="button"
          onClick={onClick}
          className="group flex w-full items-center gap-3 rounded-md p-1.5 text-left text-sm text-dim transition-colors hover:bg-white/[0.06] hover:text-fg"
        >
          <span className={`grid ${tile} shrink-0 place-items-center rounded-[6px] bg-white/[0.07] transition-colors group-hover:bg-white/[0.12]`}>
            <Icon className="size-5" />
          </span>
          <span className="font-medium">{label}</span>
        </button>
      ))}
    </div>
  )
}
