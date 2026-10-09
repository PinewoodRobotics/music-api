import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'

export type AnchorRect = { left: number; right: number; top: number; bottom: number }

export const pointRect = (x: number, y: number): AnchorRect => ({ left: x, right: x, top: y, bottom: y })

type Props = { anchor: AnchorRect; onClose: () => void; children: ReactNode; align?: 'start' | 'end'; className?: string }

export function Popover({ anchor, onClose, children, align = 'start', className = '' }: Props) {
  const ref = useRef<HTMLDivElement>(null)
  const [pos, setPos] = useState<{ left: number; top: number } | null>(null)

  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    const { width, height } = el.getBoundingClientRect()
    const vw = window.innerWidth
    const vh = window.innerHeight
    const left = Math.min(Math.max(8, align === 'end' ? anchor.right - width : anchor.left), vw - width - 8)
    const below = anchor.bottom + 6
    const top = below + height > vh - 8 ? Math.max(8, anchor.top - height - 6) : below
    setPos({ left, top })
  }, [anchor, align, children])

  useEffect(() => {
    const down = (e: PointerEvent) => {
      if (!ref.current?.contains(e.target as Node)) onClose()
    }
    const key = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.stopPropagation()
        onClose()
      }
    }
    const scroll = (e: Event) => {
      if (!ref.current?.contains(e.target as Node)) onClose()
    }
    document.addEventListener('pointerdown', down, true)
    window.addEventListener('keydown', key, true)
    window.addEventListener('resize', onClose)
    window.addEventListener('scroll', scroll, true)
    return () => {
      document.removeEventListener('pointerdown', down, true)
      window.removeEventListener('keydown', key, true)
      window.removeEventListener('resize', onClose)
      window.removeEventListener('scroll', scroll, true)
    }
  }, [onClose])

  return createPortal(
    <div
      ref={ref}
      role="menu"
      className={`animate-pop fixed z-[70] min-w-52 max-w-[calc(100vw-16px)] rounded-lg border border-white/[0.06] bg-[#26262c] p-1 shadow-2xl shadow-black/60 ${className}`}
      style={pos ? { left: pos.left, top: pos.top } : { left: -9999, top: -9999 }}
    >
      {children}
    </div>,
    document.body,
  )
}

type ItemProps = { icon?: ReactNode; children: ReactNode; onSelect: () => void; danger?: boolean; trailing?: ReactNode; disabled?: boolean }

export function MenuItem({ icon, children, onSelect, danger, trailing, disabled }: ItemProps) {
  return (
    <button
      type="button"
      role="menuitem"
      disabled={disabled}
      onClick={onSelect}
      className={`flex w-full items-center gap-3 rounded-[5px] px-3 py-2 text-left text-sm transition-colors hover:bg-white/[0.08] disabled:opacity-40 ${
        danger ? 'text-danger' : 'text-fg'
      }`}
    >
      {icon && <span className="grid size-4 shrink-0 place-items-center text-dim [&>svg]:size-4">{icon}</span>}
      <span className="min-w-0 flex-1 truncate">{children}</span>
      {trailing && <span className="text-dim [&>svg]:size-4">{trailing}</span>}
    </button>
  )
}

export const MenuDivider = () => <div className="mx-2 my-1 h-px bg-white/[0.07]" />
