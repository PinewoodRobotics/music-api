import type { MouseEvent, ReactNode } from 'react'
import { createPortal } from 'react-dom'

export type BarAction = { label: string; icon: ReactNode; onClick: (e: MouseEvent<HTMLButtonElement>) => void; danger?: boolean }

export function SelectionBar({ count, noun, actions, onDone }: { count: number; noun: string; actions: BarAction[]; onDone: () => void }) {
  return createPortal(
    <div
      data-selection-bar
      className="animate-toast fixed inset-x-2 bottom-[calc(env(safe-area-inset-bottom)+8.75rem)] z-[56] mx-auto flex max-w-xl items-center gap-1 rounded-2xl border border-white/[0.08] bg-[#2a2a31]/95 p-1.5 shadow-2xl shadow-black/60 backdrop-blur md:bottom-[104px]"
    >
      <span className="min-w-0 flex-1 truncate px-2 text-sm font-semibold">
        {count ? `${count} ${noun}${count === 1 ? '' : 's'}` : `Select ${noun}s`}
      </span>
      {actions.map((a) => (
        <button
          key={a.label}
          type="button"
          disabled={!count}
          onClick={a.onClick}
          aria-label={a.label}
          title={a.label}
          className={`grid size-11 shrink-0 place-items-center rounded-full transition active:scale-90 disabled:opacity-35 [&>svg]:size-5 ${a.danger ? 'text-danger' : 'text-fg'} hover:bg-white/10`}
        >
          {a.icon}
        </button>
      ))}
      <button type="button" onClick={onDone} className="h-11 shrink-0 rounded-full bg-fg px-4 text-sm font-semibold text-canvas active:scale-95">
        Done
      </button>
    </div>,
    document.body,
  )
}
