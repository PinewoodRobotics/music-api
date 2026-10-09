import type { ButtonHTMLAttributes, ReactNode } from 'react'

type Props = ButtonHTMLAttributes<HTMLButtonElement> & { label: string; active?: boolean; children: ReactNode; size?: 'sm' | 'md' | 'lg' | 'xl' }

export function IconButton({ label, active, children, className = '', size = 'md', ...rest }: Props) {
  const box = { sm: 'size-8', md: 'size-9', lg: 'size-11', xl: 'size-12' }[size]
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      aria-pressed={active}
      className={`relative grid ${box} shrink-0 place-items-center rounded-full transition disabled:opacity-35 active:scale-90 ${
        active ? 'text-accent' : 'text-dim hover:text-fg'
      } ${className}`}
      {...rest}
    >
      {children}
      {active && <span className="absolute bottom-0.5 size-1 rounded-full bg-accent" />}
    </button>
  )
}
