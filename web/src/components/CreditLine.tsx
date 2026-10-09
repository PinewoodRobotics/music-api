import type { Credit } from '../lib/api'
import { Avatar } from './Avatar'

export function CreditLine({ credit, className = '' }: { credit: Credit | null | undefined; className?: string }) {
  if (!credit?.by?.name) return null
  return (
    <div className={`flex min-w-0 items-center gap-1.5 ${className}`}>
      <Avatar person={credit.by} className="size-3.5 text-[8px]" />
      <span className="truncate">
        {credit.how === 'queued' ? 'Queued by' : 'Started by'} {credit.by.name}
      </span>
    </div>
  )
}
