import type { ButtonHTMLAttributes, ReactNode } from 'react'

type Props = ButtonHTMLAttributes<HTMLButtonElement> & { label: string; active?: boolean; children: ReactNode; size?: 'sm' | 'md' }

export function IconButton({ label, active, children, className = '', size = 'md', ...rest }: Props) {
  const box = size === 'sm' ? 'size-8' : 'size-9'
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      aria-pressed={active}
      className={`relative grid ${box} shrink-0 place-items-center rounded-full transition-colors disabled:opacity-35 ${
        active ? 'text-accent' : 'text-dim hover:text-fg'
      } ${className}`}
      {...rest}
    >
      {children}
      {active && <span className="absolute bottom-0.5 size-1 rounded-full bg-accent" />}
    </button>
  )
}
