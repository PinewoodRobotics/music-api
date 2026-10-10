import { CircleAlert } from 'lucide-react'
import { useToastList } from '../state/toast'

export function Toasts() {
  const { toasts, dismiss } = useToastList()
  return (
    <div className="pointer-events-none fixed inset-x-0 bottom-[calc(150px+env(safe-area-inset-bottom))] z-[80] flex flex-col items-center gap-2 px-4 md:bottom-28" aria-live="polite">
      {toasts.map((t) => (
        <div
          key={t.id}
          role="status"
          onClick={() => dismiss(t.id)}
          className={`animate-toast pointer-events-auto flex max-w-md cursor-pointer items-center gap-2.5 rounded-lg py-3 pl-4 text-left text-sm font-medium shadow-2xl shadow-black/50 ${
            t.action ? 'pr-2' : 'pr-4'
          } ${t.tone === 'error' ? 'bg-[#3a1d1f] text-[#ffd9d9]' : 'bg-fg text-canvas'}`}
        >
          {t.tone === 'error' && <CircleAlert className="size-4 shrink-0" />}
          <span className="min-w-0 flex-1">{t.message}</span>
          {t.action && (
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation()
                dismiss(t.id)
                t.action?.run()
              }}
              className="shrink-0 rounded-md px-2.5 py-1 font-semibold text-[#1d6fe0] hover:bg-black/5 active:bg-black/10"
            >
              {t.action.label}
            </button>
          )}
        </div>
      ))}
    </div>
  )
}
