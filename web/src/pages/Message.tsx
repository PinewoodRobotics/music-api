import { Loader2 } from 'lucide-react'
import type { ReactNode } from 'react'

export function Message({ title, body, action, icon }: { title: string; body?: string; action?: ReactNode; icon?: ReactNode }) {
  return (
    <div className="mx-auto flex max-w-sm flex-col items-center px-6 py-16 text-center">
      {icon && <div className="mb-4 text-faint">{icon}</div>}
      <h2 className="font-display text-xl font-bold tracking-tight">{title}</h2>
      {body && <p className="mt-2 text-sm leading-relaxed text-dim">{body}</p>}
      {action && <div className="mt-6">{action}</div>}
    </div>
  )
}

export function PageSpinner() {
  return (
    <div className="grid place-items-center py-24">
      <Loader2 className="size-7 animate-spin text-faint" />
    </div>
  )
}
