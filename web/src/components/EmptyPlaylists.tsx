import { Download, ListMusic, Plus } from 'lucide-react'
import { useUI } from '../state/ui'
import { Button } from './Modal'

export function EmptyPlaylists() {
  const { openDialog } = useUI()
  return (
    <div className="mx-3 flex flex-col items-center rounded-xl border border-dashed border-white/[0.12] px-6 py-12 text-center max-sm:mx-2">
      <div className="mb-4 grid size-14 place-items-center rounded-xl bg-white/[0.06] text-dim">
        <ListMusic className="size-7" />
      </div>
      <h3 className="font-display text-xl font-bold tracking-tight">No playlists yet</h3>
      <p className="mt-1.5 max-w-xs text-sm text-dim">Create one for the lab, or import one from Spotify or Apple Music.</p>
      <div className="mt-6 flex flex-wrap justify-center gap-2">
        <Button onClick={() => openDialog({ kind: 'new' })}>
          <Plus className="size-4" />
          New playlist
        </Button>
        <Button variant="ghost" className="ring-1 ring-white/20" onClick={() => openDialog({ kind: 'import' })}>
          <Download className="size-4" />
          Import
        </Button>
      </div>
    </div>
  )
}
