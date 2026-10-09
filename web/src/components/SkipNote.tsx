import { SkipForward } from 'lucide-react'
import type { Credit } from '../lib/api'
import { useSkipNote } from '../lib/skipNote'
import { Avatar } from './Avatar'
import { CreditLine } from './CreditLine'

export function SkipNote({ className = '' }: { className?: string }) {
  const note = useSkipNote()
  if (!note) return null
  return (
    <div
      role="status"
      aria-label={`Skipped by ${note.person.name}`}
      className={`flex min-w-0 items-center gap-1.5 transition-opacity duration-300 ${note.visible ? 'animate-[fade-in_300ms_ease] opacity-100' : 'opacity-0'} ${className}`}
    >
      <SkipForward className="size-3.5 shrink-0 fill-current" aria-hidden />
      <Avatar person={note.person} className="size-3.5 text-[8px]" />
      <span className="truncate">{note.person.name}</span>
    </div>
  )
}

export function CreditOrSkip({ credit, className = '' }: { credit: Credit | null | undefined; className?: string }) {
  const note = useSkipNote()
  return note ? <SkipNote className={className} /> : <CreditLine credit={credit} className={className} />
}
