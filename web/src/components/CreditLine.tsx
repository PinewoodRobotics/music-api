import { Radio } from 'lucide-react'
import type { Credit } from '../lib/api'
import { Avatar } from './Avatar'

export function CreditLine({ credit, className = '' }: { credit: Credit | null | undefined; className?: string }) {
  if (!credit?.by?.name) return null
  const autoplay = credit.how === 'autoplay'
  return (
    <div className={`flex min-w-0 items-center gap-1.5 ${className}`}>
      {autoplay ? <Radio className="size-3.5 shrink-0" aria-hidden /> : <Avatar person={credit.by} className="size-3.5 text-[8px]" />}
      <span className="truncate">{autoplay ? 'Autoplay' : credit.by.name}</span>
    </div>
  )
}
