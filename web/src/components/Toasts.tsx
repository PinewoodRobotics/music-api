import { CircleAlert } from 'lucide-react'
import { useToastList } from '../state/toast'

export function Toasts() {
  const { toasts, dismiss } = useToastList()
  return (
    <div className="pointer-events-none fixed inset-x-0 bottom-[calc(150px+env(safe-area-inset-bottom))] z-[80] flex flex-col items-center gap-2 px-4 md:bottom-28" aria-live="polite">
      {toasts.map((t) => (
        <button
          key={t.id}
          type="button"
          onClick={() => dismiss(t.id)}
          className={`animate-toast pointer-events-auto flex max-w-md items-center gap-2.5 rounded-lg px-4 py-3 text-left text-sm font-medium shadow-2xl shadow-black/50 ${
            t.tone === 'error' ? 'bg-[#3a1d1f] text-[#ffd9d9]' : 'bg-fg text-canvas'
          }`}
        >
          {t.tone === 'error' && <CircleAlert className="size-4 shrink-0" />}
          {t.message}
        </button>
      ))}
    </div>
  )
}
