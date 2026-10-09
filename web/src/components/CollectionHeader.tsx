import { Loader2 } from 'lucide-react'
import type { ReactNode } from 'react'
import { usePalette } from '../lib/color'
import { decodeEntities } from '../lib/format'
import { Artwork } from './Artwork'

type Props = {
  artwork: string | null | undefined
  kind: string
  title: string
  description?: string
  meta?: ReactNode
  round?: boolean
  children?: ReactNode
}

export function CollectionHeader({ artwork, kind, title, description, meta, round, children }: Props) {
  const palette = usePalette(artwork)
  const titleSize =
    title.length > 40 ? 'text-[clamp(1.75rem,3.6vw,3rem)]' : title.length > 18 ? 'text-[clamp(2rem,5vw,4.25rem)]' : 'text-[clamp(2.5rem,7vw,6rem)]'
  return (
    <div className="relative" style={{ ['--page-glow' as string]: palette.glow }}>
      <div className="pointer-events-none absolute inset-x-0 -top-16 h-[calc(100%+22rem)] bg-[linear-gradient(to_bottom,var(--page-glow),transparent)] opacity-90 transition-[background] duration-700" />
      <div className="relative flex items-end gap-6 px-6 pb-6 pt-6 max-sm:flex-col max-sm:items-start max-sm:gap-4 max-sm:px-4">
        <Artwork
          src={artwork}
          round={round}
          className="size-[clamp(160px,20vw,232px)] shrink-0 shadow-[0_16px_48px_rgba(0,0,0,0.55)] max-sm:mx-auto max-sm:size-[min(60vw,240px)]"
        />
        <div className="min-w-0 flex-1">
          <div className="text-sm font-medium text-white/80 max-sm:hidden">{kind}</div>
          <h1 className={`mt-1 line-clamp-2 break-words pb-[0.08em] font-display font-extrabold leading-[0.98] tracking-[-0.04em] max-sm:text-[1.75rem] ${titleSize}`}>
            {title}
          </h1>
          {description && <p className="mt-3 line-clamp-2 max-w-2xl text-sm text-white/70">{decodeEntities(description)}</p>}
          {meta && <div className="mt-3 flex flex-wrap items-center gap-x-1.5 gap-y-1 text-sm text-white/85">{meta}</div>}
        </div>
      </div>
      {children && <div className="relative flex items-center gap-5 px-6 pb-4 max-sm:px-4">{children}</div>}
    </div>
  )
}

export function BigPlayButton({ playing, onClick, label, pending }: { playing: boolean; onClick: () => void; label: string; pending?: boolean }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      title={label}
      aria-busy={pending}
      disabled={pending}
      className="grid size-14 place-items-center rounded-full bg-accent text-ink shadow-lg shadow-black/30 transition-transform hover:scale-105 active:scale-95"
    >
      {pending ? (
        <Loader2 className="size-6 animate-spin" />
      ) : playing ? (
        <svg viewBox="0 0 24 24" className="size-6 fill-current">
          <rect x="6" y="5" width="4" height="14" rx="1" />
          <rect x="14" y="5" width="4" height="14" rx="1" />
        </svg>
      ) : (
        <svg viewBox="0 0 24 24" className="size-6 translate-x-[1px] fill-current">
          <path d="M7 4.5v15a1 1 0 0 0 1.5.86l12.5-7.5a1 1 0 0 0 0-1.72L8.5 3.64A1 1 0 0 0 7 4.5Z" />
        </svg>
      )}
    </button>
  )
}

export const Dot = () => <span className="text-white/50">•</span>
