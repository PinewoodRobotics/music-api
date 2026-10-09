import { Loader2, Pause, Play } from 'lucide-react'
import type { MouseEvent } from 'react'

type Props = { playing: boolean; pending: boolean; label: string; onClick: () => void; className?: string }

export function PlayFab({ playing, pending, label, onClick, className = '' }: Props) {
  const click = (e: MouseEvent) => {
    e.stopPropagation()
    onClick()
  }
  return (
    <button
      type="button"
      aria-label={playing ? 'Pause' : label}
      title={playing ? 'Pause' : label}
      onClick={click}
      disabled={pending}
      className={`grid size-12 place-items-center rounded-full bg-accent text-ink shadow-xl shadow-black/40 transition-all duration-200 hover:scale-105 ${className}`}
    >
      {pending ? (
        <Loader2 className="size-5 animate-spin" />
      ) : playing ? (
        <Pause className="size-5 fill-current" strokeWidth={0} />
      ) : (
        <Play className="size-5 translate-x-[1px] fill-current" strokeWidth={0} />
      )}
    </button>
  )
}
