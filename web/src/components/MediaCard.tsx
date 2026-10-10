import { Loader2, Pause, Play } from 'lucide-react'
import type { HTMLAttributes, MouseEvent, ReactNode } from 'react'
import { navigate } from '../lib/router'
import { Artwork } from './Artwork'

type Props = {
  title: string
  subtitle?: ReactNode
  artwork: string | null | undefined
  round?: boolean
  href?: string
  onPlay?: () => void
  playing?: boolean
  pending?: boolean
  corner?: ReactNode
  selectable?: { props: HTMLAttributes<HTMLDivElement> & { 'data-row-index': number }; selected: boolean }
}

export function MediaCard({ title, subtitle, artwork, round, href, onPlay, playing, pending, corner, selectable }: Props) {
  const open = () => (href ? navigate(href) : onPlay?.())
  const play = (e: MouseEvent) => {
    e.stopPropagation()
    onPlay?.()
  }
  return (
    <div
      role="link"
      tabIndex={0}
      onClick={open}
      onKeyDown={(e) => !selectable && e.key === 'Enter' && open()}
      {...selectable?.props}
      className={`group cursor-pointer rounded-lg p-3 transition max-sm:p-2 ${
        selectable?.selected
          ? 'bg-white/[0.12] ring-1 ring-white/20'
          : 'hover:bg-white/[0.06] focus-visible:bg-white/[0.06] active:scale-[0.98] active:bg-white/[0.06]'
      }`}
    >
      <div className="relative mb-3">
        {corner && (
          <div className="absolute right-2 top-2 z-10 opacity-0 transition-opacity group-hover:opacity-100 group-focus-within:opacity-100 [@media(hover:none)]:opacity-100">
            {corner}
          </div>
        )}
        <Artwork src={artwork} round={round} className="aspect-square w-full shadow-[0_8px_24px_rgba(0,0,0,0.5)]" />
        {onPlay && (
          <button
            type="button"
            aria-label={playing ? `Pause ${title}` : `Play ${title}`}
            onClick={play}
            className={`absolute bottom-2 right-2 grid size-12 place-items-center rounded-full bg-accent text-ink shadow-xl shadow-black/40 transition-all duration-200 hover:scale-105 [@media(hover:none)]:hidden ${
              playing || pending ? 'translate-y-0 opacity-100' : 'translate-y-2 opacity-0 group-hover:translate-y-0 group-hover:opacity-100 group-focus-visible:translate-y-0 group-focus-visible:opacity-100'
            }`}
          >
            {pending ? <Loader2 className="size-5 animate-spin" /> : playing ? <Pause className="size-5 fill-current" strokeWidth={0} /> : <Play className="size-5 translate-x-[1px] fill-current" strokeWidth={0} />}
          </button>
        )}
      </div>
      <div className={`truncate text-[15px] font-semibold ${round ? 'text-center' : ''}`}>{title}</div>
      {subtitle && <div className={`mt-1 line-clamp-2 text-[13px] leading-snug text-dim ${round ? 'text-center' : ''}`}>{subtitle}</div>}
    </div>
  )
}

export function CardGrid({ children }: { children: ReactNode }) {
  return <div className="grid grid-cols-[repeat(auto-fill,minmax(168px,1fr))] max-sm:grid-cols-2">{children}</div>
}

export function Section({ title, children, action }: { title: string; children: ReactNode; action?: ReactNode }) {
  return (
    <section className="mt-8">
      <div className="mb-2 flex items-end justify-between gap-4 px-3 max-sm:px-2">
        <h2 className="font-display text-2xl font-bold tracking-tight">{title}</h2>
        {action}
      </div>
      {children}
    </section>
  )
}
