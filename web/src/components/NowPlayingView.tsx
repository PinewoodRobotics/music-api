import { ChevronDown } from 'lucide-react'
import { useCallback, useEffect, useLayoutEffect, useRef, useState, type CSSProperties, type RefObject } from 'react'
import { useMediaQuery } from '../lib/device'
import { useSwipeDismiss } from '../lib/useSwipeDismiss'
import { usePlayer } from '../state/player'
import { useUI, type Panel } from '../state/ui'
import { Lyrics } from './Lyrics'
import { DeviceIndicator, GlassSeek, GlassVolume, ModePills, TrackMenuButton, Transport, TrackTitle, ViewToggle } from './nowplaying/Controls'
import { Mesh } from './nowplaying/Mesh'
import { UpNext } from './UpNext'

const IDLE_MS = 3000

function useIdle(enabled: boolean) {
  const [awake, setAwake] = useState(true)
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined)
  const held = useRef(false)
  const wake = useCallback(() => {
    setAwake(true)
    clearTimeout(timer.current)
    if (!enabled) return
    timer.current = setTimeout(() => {
      if (!held.current) setAwake(false)
    }, IDLE_MS)
  }, [enabled])
  useEffect(() => {
    wake()
    return () => clearTimeout(timer.current)
  }, [wake])
  const hold = (on: boolean) => {
    held.current = on
    if (!on) wake()
  }
  return { awake: awake || !enabled, wake, hold }
}

function useArtworkFlip(root: RefObject<HTMLDivElement | null>, key: string) {
  const last = useRef<{ key: string; rect: DOMRect } | null>(null)
  useLayoutEffect(() => {
    const el = root.current?.querySelector<HTMLElement>('[data-np-art]')
    if (!el) return
    const rect = el.getBoundingClientRect()
    const prev = last.current
    last.current = { key, rect }
    if (!prev || prev.key === key || !rect.width || window.matchMedia('(prefers-reduced-motion: reduce)').matches) return
    el.style.transformOrigin = 'top left'
    el.style.transition = 'none'
    el.style.transform = `translate(${prev.rect.left - rect.left}px, ${prev.rect.top - rect.top}px) scale(${prev.rect.width / rect.width})`
    requestAnimationFrame(() => {
      el.style.transition = 'transform 450ms cubic-bezier(0.2, 0.8, 0.2, 1)'
      el.style.transform = ''
    })
  })
}

export function NowPlayingView() {
  const { expanded } = useUI()
  return expanded ? <Sheet /> : null
}

function Sheet() {
  const { setExpanded, panel, togglePanel } = useUI()
  const { status } = usePlayer()
  const compact = useMediaQuery('(max-width: 767px)')
  const fine = useMediaQuery('(hover: hover) and (pointer: fine)')
  const { awake, wake, hold } = useIdle(fine)
  const close = useCallback(() => setExpanded(false), [setExpanded])
  const { ref, dismiss, handlers } = useSwipeDismiss(close)
  useArtworkFlip(ref, `${compact}:${panel ?? 'art'}`)

  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if (e.key === 'Escape') dismiss()
      wake()
    }
    window.addEventListener('keydown', key)
    return () => window.removeEventListener('keydown', key)
  }, [dismiss, wake])

  const fade = `transition-opacity duration-700 ${awake ? 'opacity-100' : 'pointer-events-none opacity-0'}`
  const art = status?.track?.artwork ?? null

  return (
    <div
      ref={ref}
      {...handlers}
      className={`animate-rise fixed inset-0 z-50 touch-none select-none overflow-hidden text-white will-change-transform ${awake ? '' : 'cursor-none'}`}
      onPointerMoveCapture={wake}
      onPointerDownCapture={wake}
      role="dialog"
      aria-modal="true"
      aria-label="Now Playing"
    >
      <Mesh art={art} />
      <div className="relative flex h-full flex-col pb-[max(env(safe-area-inset-bottom),14px)] pt-[env(safe-area-inset-top)]">
        {fine ? (
          <button
            type="button"
            onClick={dismiss}
            aria-label="Close (Esc)"
            title="Close (Esc)"
            className={`absolute left-4 top-[max(env(safe-area-inset-top),16px)] z-10 grid size-11 place-items-center rounded-full bg-white/10 text-white/85 hover:bg-white/20 ${fade}`}
          >
            <ChevronDown className="size-6" />
          </button>
        ) : (
          <button type="button" onClick={dismiss} aria-label="Close" className="mx-auto grid h-7 w-20 shrink-0 place-items-center">
            <span className="h-[5px] w-10 rounded-full bg-white/45" />
          </button>
        )}
        {compact ? (
          <PhoneLayout art={art} panel={panel} onToggle={togglePanel} />
        ) : (
          <WideLayout art={art} panel={panel} onToggle={togglePanel} fine={fine} fade={fade} hold={hold} />
        )}
      </div>
    </div>
  )
}

type LayoutProps = { art: string | null; panel: Panel | null; onToggle: (p: Panel) => void }

function Artwork({ art, className = '', style }: { art: string | null; className?: string; style?: CSSProperties }) {
  return art ? (
    <img data-np-art src={art} alt="" draggable={false} style={style} className={`bg-white/10 object-cover shadow-[0_24px_60px_-12px_rgba(0,0,0,0.55)] ${className}`} />
  ) : (
    <div data-np-art style={style} className={`bg-white/15 ${className}`} />
  )
}

function PanelBody({ panel }: { panel: Panel }) {
  return (
    <div data-no-swipe className="relative min-h-0 flex-1 animate-[fade-in_350ms_ease] touch-pan-y overflow-hidden">
      <div className="absolute inset-0">{panel === 'lyrics' ? <Lyrics size="immersive" /> : <UpNext immersive />}</div>
    </div>
  )
}

function PhoneLayout({ art, panel, onToggle }: LayoutProps) {
  return (
    <div className="flex min-h-0 flex-1 flex-col px-6">
      {panel ? (
        <>
          <div className="flex items-center gap-3.5 pb-3 pt-2">
            <Artwork art={art} className="size-16 shrink-0 rounded-md" />
            <TrackTitle size="sm" />
          </div>
          {panel === 'queue' && <ModePills className="mb-4" />}
          <PanelBody panel={panel} />
        </>
      ) : (
        <>
          <div className="grid min-h-0 flex-1 place-items-center py-4 [container-type:size]">
            <Artwork art={art} className="rounded-xl" style={{ width: 'min(100cqw, 100cqh)', height: 'min(100cqw, 100cqh)' }} />
          </div>
          <div className="pb-1">
            <TrackTitle size="md" />
          </div>
        </>
      )}
      <div className="pt-5">
        <GlassSeek />
      </div>
      <div className="my-2">
        <Transport size="lg" />
      </div>
      <GlassVolume />
      <div className="mt-4 flex items-center justify-between">
        <ViewToggle panel="lyrics" current={panel} onToggle={onToggle} />
        <DeviceIndicator />
        <ViewToggle panel="queue" current={panel} onToggle={onToggle} />
      </div>
    </div>
  )
}

function WideLayout({ art, panel, onToggle, fine, fade, hold }: LayoutProps & { fine: boolean; fade: string; hold: (on: boolean) => void }) {
  const column = panel ? 'min(40vw, 54vh)' : fine ? 'min(60vh, 56vw)' : 'min(52vh, 70vw)'
  return (
    <div className="relative flex min-h-0 flex-1 items-center justify-center gap-[6vw] px-[5vw] pb-4">
      <div className="flex shrink-0 flex-col transition-[width] duration-500" style={{ width: column }}>
        <Artwork art={art} className="aspect-square w-full rounded-xl" />
        <div
          className={fine ? fade : ''}
          onPointerEnter={(e) => e.pointerType === 'mouse' && hold(true)}
          onPointerLeave={(e) => e.pointerType === 'mouse' && hold(false)}
        >
          <div className="mt-6">
            <TrackTitle size={fine ? 'sm' : 'lg'} withMenu={!fine} />
          </div>
          {fine ? <DesktopStrip panel={panel} onToggle={onToggle} /> : <TabletControls />}
        </div>
      </div>
      {panel && (
        <div className="flex h-[min(84vh,920px)] min-w-0 max-w-[660px] flex-1 flex-col">
          {panel === 'queue' && <ModePills className="mb-5 max-w-xs" />}
          <PanelBody panel={panel} />
        </div>
      )}
      {!fine && (
        <>
          <div className="absolute bottom-2 left-[5vw]">
            <DeviceIndicator />
          </div>
          <div className="absolute bottom-0 right-[5vw] flex gap-3">
            <ViewToggle panel="lyrics" current={panel} onToggle={onToggle} />
            <ViewToggle panel="queue" current={panel} onToggle={onToggle} />
          </div>
        </>
      )}
    </div>
  )
}

function DesktopStrip({ panel, onToggle }: { panel: Panel | null; onToggle: (p: Panel) => void }) {
  return (
    <div className="mt-4">
      <GlassSeek timesAbove />
      <div className="mt-3 grid grid-cols-[1fr_auto_1fr] items-center">
        <div>
          <TrackMenuButton subtle />
        </div>
        <Transport size="md" />
        <div className="flex justify-end gap-1">
          <ViewToggle small panel="lyrics" current={panel} onToggle={onToggle} />
          <ViewToggle small panel="queue" current={panel} onToggle={onToggle} />
        </div>
      </div>
      <GlassVolume className="mt-4" />
    </div>
  )
}

function TabletControls() {
  return (
    <>
      <div className="pt-5">
        <GlassSeek />
      </div>
      <div className="my-2">
        <Transport size="lg" withModes />
      </div>
      <GlassVolume />
    </>
  )
}
