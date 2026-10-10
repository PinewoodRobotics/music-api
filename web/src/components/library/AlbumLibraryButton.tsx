import { Check, Loader2, Plus } from 'lucide-react'
import { useState } from 'react'
import { useLibraryActions } from '../../lib/library'

type Props = { uri: string; name: string; compact?: boolean }

export function AlbumLibraryButton({ uri, name, compact = false }: Props) {
  const { albumInLibrary, addAlbum, removeAlbum } = useLibraryActions()
  const [busy, setBusy] = useState(false)
  const saved = albumInLibrary(uri)
  const label = saved ? (saved.can_edit ? 'Remove from Library' : 'In Library') : 'Add to Library'

  const toggle = async () => {
    if (busy || (saved && !saved.can_edit)) return
    setBusy(true)
    if (saved) await removeAlbum(saved)
    else await addAlbum({ uri }, name)
    setBusy(false)
  }

  const icon = busy ? <Loader2 className="size-4 animate-spin" /> : saved ? <Check className="size-4" /> : <Plus className="size-4" />
  if (compact)
    return (
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation()
          void toggle()
        }}
        aria-label={label}
        title={label}
        disabled={busy}
        className={`grid size-9 shrink-0 place-items-center rounded-full transition active:scale-90 ${
          saved ? 'bg-[#34c759] text-black' : 'bg-black/50 text-white backdrop-blur hover:bg-black/70'
        }`}
      >
        {icon}
      </button>
    )
  return (
    <button
      type="button"
      onClick={() => void toggle()}
      disabled={busy || (!!saved && !saved.can_edit)}
      title={label}
      className={`inline-flex h-9 shrink-0 items-center gap-2 rounded-full px-4 text-sm font-semibold ring-1 transition active:scale-95 disabled:cursor-default ${
        saved ? 'text-[#34c759] ring-[#34c759]/50 hover:bg-[#34c759]/10' : 'text-fg ring-white/25 hover:bg-white/10'
      }`}
    >
      {icon}
      {saved ? 'In Library' : 'Add to Library'}
    </button>
  )
}
