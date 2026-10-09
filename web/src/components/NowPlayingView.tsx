import { ChevronDown, ListMusic, MicVocal } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { byline, idFromUri } from '../lib/format'
import { navigate } from '../lib/router'
import { usePlayer } from '../state/player'
import { useUI, type Panel } from '../state/ui'
import { Artwork } from './Artwork'
import { IconButton } from './IconButton'
import { Lyrics } from './Lyrics'
import { SeekBar, Transport, VolumeControl } from './PlayerControls'
import { UpNext } from './UpNext'

const IDLE_MS = 3000

function useIdle() {
  const [awake, setAwake] = useState(true)
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined)
  const held = useRef(false)
  const wake = useCallback(() => {
    setAwake(true)
    clearTimeout(timer.current)
    timer.current = setTimeout(() => {
      if (!held.current) setAwake(false)
    }, IDLE_MS)
  }, [])
  useEffect(() => {
    wake()
    return () => clearTimeout(timer.current)
  }, [wake])
  const hold = (on: boolean) => {
    held.current = on
    if (!on) wake()
  }
  return { awake, wake, hold }
}

function contextPath(uri: string | undefined) {
  if (!uri) return null
  const [, type] = uri.split(':')
  return type === 'playlist' || type === 'album' || type === 'artist' ? `/${type}/${idFromUri(uri)}` : null
}

export function NowPlayingView() {
  const { expanded, setExpanded, panel, togglePanel } = useUI()
  const { status } = usePlayer()
  const { awake, wake, hold } = useIdle()
  const track = status?.track

  useEffect(() => {
    if (!expanded) return
    wake()
    const key = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setExpanded(false)
      wake()
    }
    window.addEventListener('keydown', key)
    return () => window.removeEventListener('keydown', key)
  }, [expanded, setExpanded, wake])

  if (!expanded) return null

  const fade = `transition-opacity duration-700 ${awake ? 'opacity-100' : 'pointer-events-none opacity-0'}`
  const context = status?.context
  const ctxPath = contextPath(context?.uri)

  const openContext = () => {
    if (!ctxPath) return
    setExpanded(false)
    navigate(ctxPath)
  }

  return (
    <div
      className={`animate-rise fixed inset-0 z-50 overflow-hidden bg-black text-white ${awake ? '' : 'cursor-none'}`}
      onPointerMove={wake}
      onPointerDown={wake}
      role="dialog"
      aria-modal="true"
      aria-label="Now Playing"
    >
      <Backdrop art={track?.artwork} />
      <div className="relative flex h-full flex-col pb-[max(env(safe-area-inset-bottom),1rem)] pt-[max(env(safe-area-inset-top),0.75rem)]">
        <header className={`flex items-center gap-3 px-4 sm:px-6 ${fade}`}>
          <IconButton label="Close (Esc)" onClick={() => setExpanded(false)} className="!text-white/80 hover:!text-white">
            <ChevronDown className="size-6" />
          </IconButton>
          <div className="min-w-0 flex-1 text-center">
            {context?.name && (
              <>
                <div className="text-[11px] text-white/60">Playing from</div>
                <button
                  type="button"
                  onClick={openContext}
                  disabled={!ctxPath}
                  className="max-w-full truncate text-sm font-semibold enabled:hover:underline"
                >
                  {context.name}
                </button>
              </>
            )}
          </div>
          <div className="size-9" />
        </header>

        <main className="flex min-h-0 flex-1 gap-10 px-6 py-4 lg:px-12">
          <section className={`min-h-0 flex-1 flex-col items-center justify-center ${panel ? 'hidden lg:flex' : 'flex'}`}>
            <Stage panelOpen={!!panel} />
          </section>
          {panel && (
            <aside className="flex min-h-0 w-full flex-col lg:w-[min(46%,600px)]">
              {track && (
                <div className="mb-3 flex items-center gap-3 lg:hidden">
                  <Artwork src={track.artwork} className="size-12 shrink-0" />
                  <div className="min-w-0">
                    <div className="truncate font-semibold">{track.name}</div>
                    <div className="truncate text-sm text-white/65">{byline(track)}</div>
                  </div>
                </div>
              )}
              <div className={`min-h-0 flex-1 ${panel === 'queue' ? 'rounded-xl bg-black/25 pt-3 backdrop-blur-sm' : ''}`}>
                {panel === 'lyrics' ? <Lyrics size="lg" /> : <UpNext />}
              </div>
            </aside>
          )}
        </main>

        <footer
          className={`mx-auto w-full max-w-5xl px-6 ${fade}`}
          onPointerEnter={(e) => e.pointerType === 'mouse' && hold(true)}
          onPointerLeave={(e) => e.pointerType === 'mouse' && hold(false)}
        >
          <SeekBar large />
          <div className="mt-2 grid grid-cols-[1fr_auto_1fr] items-center gap-2 max-sm:grid-cols-1">
            <div className="max-sm:hidden" />
            <Transport size="lg" />
            <div className="flex items-center justify-end gap-1 max-sm:mt-1">
              <PanelToggle panel="lyrics" current={panel} onToggle={togglePanel} />
              <PanelToggle panel="queue" current={panel} onToggle={togglePanel} />
              <VolumeControl className="ml-2 w-32 max-sm:ml-4 max-sm:w-auto max-sm:flex-1" />
            </div>
          </div>
        </footer>
      </div>
    </div>
  )
}

function PanelToggle({ panel, current, onToggle }: { panel: Panel; current: Panel | null; onToggle: (p: Panel) => void }) {
  const Icon = panel === 'lyrics' ? MicVocal : ListMusic
  return (
    <IconButton label={panel === 'lyrics' ? 'Lyrics' : 'Up next'} active={current === panel} onClick={() => onToggle(panel)} className={current === panel ? '' : '!text-white/70 hover:!text-white'}>
      <Icon className="size-5" />
    </IconButton>
  )
}

function Stage({ panelOpen }: { panelOpen: boolean }) {
  const { status } = usePlayer()
  const track = status?.track
  const size = panelOpen ? 'min(52vh, 34vw)' : 'min(54vh, 82vw, 560px)'
  if (!track)
    return (
      <div className="text-center">
        <Artwork src={null} className="mx-auto size-56" />
        <p className="mt-6 text-lg text-white/70">Nothing playing</p>
      </div>
    )
  return (
    <div style={{ width: size }} className="transition-[width] duration-500">
      <img
        key={track.artwork ?? 'none'}
        src={track.artwork ?? undefined}
        alt=""
        className="aspect-square w-full rounded-lg bg-white/10 object-cover shadow-[0_30px_80px_-20px_rgba(0,0,0,0.8)]"
      />
      <div className="mt-6 min-w-0">
        <h1 className="truncate font-display text-[clamp(1.4rem,2.6vw,2.1rem)] font-bold leading-tight tracking-tight">{track.name}</h1>
        <p className="mt-1 truncate text-[clamp(1rem,1.6vw,1.25rem)] text-white/65">{byline(track)}</p>
      </div>
    </div>
  )
}

function Backdrop({ art }: { art: string | null | undefined }) {
  return (
    <div className="absolute inset-0" aria-hidden>
      <div className="absolute inset-0 bg-ambient" />
      {art && (
        <img
          key={art}
          src={art}
          alt=""
          className="animate-[fade-in_1.2s_ease] absolute left-1/2 top-1/2 size-[140vmax] -translate-x-1/2 -translate-y-1/2 object-cover opacity-70 blur-[100px] saturate-[1.6]"
        />
      )}
      <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_30%_40%,transparent,rgba(0,0,0,0.55))]" />
      <div className="absolute inset-0 bg-gradient-to-b from-black/25 via-black/30 to-black/70" />
    </div>
  )
}
