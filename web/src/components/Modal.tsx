import { X } from 'lucide-react'
import { useEffect, type ButtonHTMLAttributes, type ReactNode } from 'react'
import { createPortal } from 'react-dom'

type Props = { title: string; onClose: () => void; children: ReactNode; dismissable?: boolean; wide?: boolean | 'xl' }

export function Modal({ title, onClose, children, dismissable = true, wide = false }: Props) {
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && dismissable) {
        e.stopPropagation()
        onClose()
      }
    }
    window.addEventListener('keydown', key, true)
    return () => window.removeEventListener('keydown', key, true)
  }, [onClose, dismissable])

  return createPortal(
    <div
      className="fixed inset-0 z-[60] grid place-items-center bg-black/70 p-4 backdrop-blur-sm"
      onPointerDown={(e) => e.target === e.currentTarget && dismissable && onClose()}
    >
      <div role="dialog" aria-modal="true" aria-label={title} className={`animate-pop w-full ${wide === 'xl' ? 'max-w-3xl' : wide ? 'max-w-lg' : 'max-w-md'} max-h-[calc(100dvh-2rem)] overflow-y-auto rounded-xl bg-raised p-6 shadow-2xl shadow-black/60`}>
        <div className="mb-5 flex items-center justify-between gap-4">
          <h2 className="font-display text-xl font-bold tracking-tight">{title}</h2>
          <button
            type="button"
            aria-label="Close"
            onClick={onClose}
            disabled={!dismissable}
            className="grid size-8 place-items-center rounded-full text-dim hover:bg-white/10 hover:text-fg disabled:opacity-30"
          >
            <X className="size-5" />
          </button>
        </div>
        {children}
      </div>
    </div>,
    document.body,
  )
}

export const fieldClass =
  'w-full rounded-md border border-transparent bg-white/[0.07] px-3 py-2.5 text-base text-fg placeholder:text-faint outline-none transition-colors focus:border-white/25 focus:bg-white/[0.1]'

export function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-xs font-medium text-dim">{label}</span>
      {children}
    </label>
  )
}

export function Button({
  children,
  variant = 'primary',
  className = '',
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: 'primary' | 'ghost' | 'danger' }) {
  const look = {
    primary: 'bg-fg text-canvas hover:scale-[1.03]',
    ghost: 'text-fg hover:bg-white/10',
    danger: 'bg-danger text-black hover:scale-[1.03]',
  }[variant]
  return (
    <button
      type="button"
      className={`inline-flex h-10 items-center justify-center gap-2 rounded-full px-5 text-sm font-semibold transition disabled:pointer-events-none disabled:opacity-50 ${look} ${className}`}
      {...rest}
    >
      {children}
    </button>
  )
}
