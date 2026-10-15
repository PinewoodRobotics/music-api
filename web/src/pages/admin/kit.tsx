import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'

export type Tone = 'good' | 'warn' | 'bad' | 'neutral'

export const toneText: Record<Tone, string> = {
  good: 'text-[#34c759]',
  warn: 'text-[#ffb340]',
  bad: 'text-danger',
  neutral: 'text-dim',
}
export const toneBg: Record<Tone, string> = {
  good: 'bg-[#34c759]',
  warn: 'bg-[#ffb340]',
  bad: 'bg-danger',
  neutral: 'bg-white/40',
}
const toneSoft: Record<Tone, string> = {
  good: 'bg-[#34c759]/10 text-[#34c759]',
  warn: 'bg-[#ffb340]/10 text-[#ffb340]',
  bad: 'bg-danger/10 text-danger',
  neutral: 'bg-white/[0.06] text-dim',
}

export function Card({ title, aside, children, className = '' }: { title?: string; aside?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`rounded-lg bg-white/[0.04] p-5 max-sm:p-4 ${className}`}>
      {(title || aside) && (
        <div className="mb-3 flex items-center justify-between gap-3">
          <h2 className="font-display text-base font-bold tracking-tight">{title}</h2>
          {aside}
        </div>
      )}
      {children}
    </section>
  )
}

export function Banner({ tone, icon, title, children, action }: { tone: Tone; icon: ReactNode; title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className={`flex items-start gap-3 rounded-lg p-4 ${toneSoft[tone]}`}>
      <span className="mt-0.5 shrink-0 [&>svg]:size-5">{icon}</span>
      <div className="min-w-0 flex-1">
        <div className="text-sm font-semibold">{title}</div>
        {children && <div className="mt-0.5 text-sm leading-snug text-dim">{children}</div>}
      </div>
      {action}
    </div>
  )
}

export function Chip({ children, tone = 'neutral' }: { children: ReactNode; tone?: Tone }) {
  return <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${toneSoft[tone]}`}>{children}</span>
}

export function Dot({ tone, pulse = false }: { tone: Tone; pulse?: boolean }) {
  return <span className={`inline-block size-2 shrink-0 rounded-full ${toneBg[tone]} ${pulse ? 'animate-pulse' : ''}`} />
}

export function Toggle({ on, onChange, label }: { on: boolean; onChange: (v: boolean) => void; label: string }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      aria-label={label}
      onClick={() => onChange(!on)}
      className={`relative h-6 w-10 shrink-0 rounded-full transition-colors duration-200 ${on ? 'bg-[#34c759]' : 'bg-white/20'}`}
    >
      <span className={`absolute left-0 top-0.5 size-5 rounded-full bg-white shadow-md transition-transform duration-200 ${on ? 'translate-x-[18px]' : 'translate-x-0.5'}`} />
    </button>
  )
}

export function Bar({ percent, tone = 'good', label }: { percent: number; tone?: Tone; label?: string }) {
  const value = Math.min(100, Math.max(0, percent))
  return (
    <div role="progressbar" aria-label={label} aria-valuenow={Math.round(value)} aria-valuemin={0} aria-valuemax={100} className="h-1.5 overflow-hidden rounded-full bg-white/10">
      <div className={`h-full rounded-full transition-[width] duration-700 ${toneBg[tone]}`} style={{ width: `${value}%` }} />
    </div>
  )
}

export function Stat({ label, value, hint }: { label: string; value: ReactNode; hint?: ReactNode }) {
  return (
    <div className="min-w-0">
      <div className="text-xs font-medium text-dim">{label}</div>
      <div className="tabular mt-0.5 truncate text-sm text-fg">{value}</div>
      {hint && <div className="mt-0.5 truncate text-xs text-faint">{hint}</div>}
    </div>
  )
}

export function Sparkline({ values, tone = 'neutral', min, max, className = 'h-12 w-full' }: { values: (number | null)[]; tone?: Tone; min: number; max: number; className?: string }) {
  const w = 200
  const h = 48
  const pts = values.map((v, i) => (v == null ? null : [(i / Math.max(1, values.length - 1)) * w, h - 3 - ((Math.min(max, Math.max(min, v)) - min) / (max - min || 1)) * (h - 6)] as const))
  const segments: (readonly [number, number])[][] = [[]]
  for (const p of pts) {
    if (p) segments[segments.length - 1].push(p)
    else if (segments[segments.length - 1].length) segments.push([])
  }
  const lines = segments.filter((s) => s.length > 1)
  const color = { good: '#34c759', warn: '#ffb340', bad: '#ff6b6b', neutral: '#a3a3ad' }[tone]
  return (
    <svg viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" className={className} aria-hidden>
      {lines.map((s, i) => {
        const line = s.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(' ')
        return (
          <g key={i}>
            <polygon points={`${s[0][0]},${h} ${line} ${s[s.length - 1][0]},${h}`} fill={color} opacity={0.12} />
            <polyline points={line} fill="none" stroke={color} strokeWidth={1.75} strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" />
          </g>
        )
      })}
    </svg>
  )
}

export function bytes(n: number) {
  if (n >= 1024 ** 3) return `${(n / 1024 ** 3).toFixed(1)} GB`
  if (n >= 1024 ** 2) return `${Math.round(n / 1024 ** 2)} MB`
  return `${Math.round(n / 1024)} KB`
}

export function duration(seconds: number) {
  const s = Math.max(0, Math.floor(seconds))
  const d = Math.floor(s / 86400)
  const h = Math.floor((s % 86400) / 3600)
  const m = Math.floor((s % 3600) / 60)
  if (d) return `${d}d ${h}h`
  if (h) return `${h}h ${m}m`
  if (m) return `${m}m`
  return `${s}s`
}

export function ago(unixSeconds: number | null | undefined) {
  if (!unixSeconds) return ''
  const s = Date.now() / 1000 - unixSeconds
  if (s < 45) return 'just now'
  if (s < 3600) return `${Math.round(s / 60)} min ago`
  if (s < 86400) return `${Math.round(s / 3600)} hr ago`
  if (s < 86400 * 30) return `${Math.round(s / 86400)} d ago`
  return new Date(unixSeconds * 1000).toLocaleDateString([], { month: 'short', day: 'numeric', year: 'numeric' })
}

export function dateTime(unixSeconds: number) {
  return new Date(unixSeconds * 1000).toLocaleString([], { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })
}

export function usePoll<T>(fetcher: () => Promise<T>, intervalMs: number | null, enabled = true) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [failures, setFailures] = useState(0)
  const fetchRef = useRef(fetcher)
  fetchRef.current = fetcher

  const reload = useCallback(async () => {
    try {
      const next = await fetchRef.current()
      setData(next)
      setError(null)
      setFailures(0)
      return next
    } catch (err) {
      setError(err)
      setFailures((n) => n + 1)
      return null
    }
  }, [])

  useEffect(() => {
    if (!enabled) return
    let live = true
    let timer: ReturnType<typeof setTimeout> | undefined
    const tick = async () => {
      if (!document.hidden) await reload()
      if (live && intervalMs) timer = setTimeout(tick, intervalMs)
    }
    void tick()
    const visible = () => {
      if (!document.hidden && live && intervalMs) {
        clearTimeout(timer)
        void tick()
      }
    }
    document.addEventListener('visibilitychange', visible)
    return () => {
      live = false
      clearTimeout(timer)
      document.removeEventListener('visibilitychange', visible)
    }
  }, [intervalMs, enabled, reload])

  return { data, setData, error, failures, reload }
}
