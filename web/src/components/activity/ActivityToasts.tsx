import { useEffect, useRef, useState, type PointerEvent } from 'react'
import { activity } from '../../lib/activity'
import type { ActivityEntry } from '../../lib/api'
import { useSession } from '../../state/session'
import { Avatar } from '../Avatar'
import { describeActivity, OriginIcon } from './ActivitySentence'

const LIFETIME_MS = 10_000
const GROUP_WINDOW_MS = 10_000
const MAX_TOASTS = 3
const GROUPED = new Set(['next', 'previous', 'queue_add', 'playlist_add', 'seek', 'volume', 'jump', 'play_item'])
const SUMMED = new Set(['queue_add', 'playlist_add'])

type Toast = { key: number; personId: string; action: string; entries: ActivityEntry[]; updatedAt: number }

const personOf = (entry: ActivityEntry) => entry.by?.id ?? entry.by?.name ?? 'unknown'

function mergeEntry(toasts: Toast[], entry: ActivityEntry, isUpdate: boolean, volumeShownAt: Map<string, number>): Toast[] {
  const now = Date.now()
  const holder = toasts.find((t) => t.entries.some((e) => e.id === entry.id))
  if (holder) {
    return toasts.map((t) => (t === holder ? { ...t, entries: t.entries.map((e) => (e.id === entry.id ? entry : e)), updatedAt: now } : t))
  }
  if (isUpdate) return toasts
  const person = personOf(entry)
  const group = GROUPED.has(entry.action)
    ? toasts.find((t) => t.personId === person && t.action === entry.action && now - t.updatedAt < GROUP_WINDOW_MS)
    : undefined
  if (group) return toasts.map((t) => (t === group ? { ...t, entries: [...t.entries, entry], updatedAt: now } : t))
  if (entry.action === 'volume' && now - (volumeShownAt.get(person) ?? 0) < GROUP_WINDOW_MS) return toasts
  if (entry.action === 'volume') volumeShownAt.set(person, now)
  return [...toasts, { key: entry.id, personId: person, action: entry.action, entries: [entry], updatedAt: now }].slice(-MAX_TOASTS)
}

export function ActivityToasts() {
  const { me } = useSession()
  const [toasts, setToasts] = useState<Toast[]>([])
  const volumeShownAt = useRef(new Map<string, number>())
  const myId = me?.id

  useEffect(
    () =>
      activity.onToast((entry, isUpdate) => {
        if (!entry.by || (myId && entry.by.id === myId)) return
        setToasts((list) => mergeEntry(list, entry, isUpdate, volumeShownAt.current))
      }),
    [myId],
  )

  const dismiss = (key: number) => setToasts((list) => list.filter((t) => t.key !== key))

  return (
    <div
      aria-live="polite"
      className="pointer-events-none fixed inset-x-2 top-[calc(env(safe-area-inset-top)+3.75rem)] z-[45] flex flex-col gap-2 md:inset-x-auto md:bottom-[104px] md:left-4 md:top-auto md:w-[360px] md:flex-col-reverse"
    >
      {[...toasts].reverse().map((toast) => (
        <ToastCard key={toast.key} toast={toast} onDismiss={() => dismiss(toast.key)} />
      ))}
    </div>
  )
}

function ToastCard({ toast, onDismiss }: { toast: Toast; onDismiss: () => void }) {
  const [hovered, setHovered] = useState(false)
  const remaining = useRef(LIFETIME_MS)
  const startedAt = useRef(0)
  const drag = useRef<{ x: number; y: number; dx: number; dy: number } | null>(null)
  const card = useRef<HTMLDivElement>(null)
  const dismissRef = useRef(onDismiss)
  dismissRef.current = onDismiss

  useEffect(() => {
    remaining.current = LIFETIME_MS
  }, [toast.updatedAt])

  useEffect(() => {
    if (hovered) return
    startedAt.current = Date.now()
    const timer = setTimeout(() => dismissRef.current(), remaining.current)
    return () => {
      clearTimeout(timer)
      remaining.current = Math.max(1000, remaining.current - (Date.now() - startedAt.current))
    }
  }, [hovered, toast.updatedAt])

  const latest = toast.entries[toast.entries.length - 1]
  const total = SUMMED.has(toast.action)
    ? toast.entries.reduce((sum, e) => sum + (typeof e.detail?.count === 'number' ? e.detail.count : 1), 0)
    : undefined

  const down = (e: PointerEvent) => {
    drag.current = { x: e.clientX, y: e.clientY, dx: 0, dy: 0 }
  }
  const move = (e: PointerEvent) => {
    const d = drag.current
    if (!d || !card.current) return
    d.dx = e.clientX - d.x
    d.dy = e.clientY - d.y
    card.current.style.transition = 'none'
    card.current.style.transform = `translate(${d.dx}px, ${Math.min(0, d.dy)}px)`
    card.current.style.opacity = String(1 - Math.min(0.8, Math.abs(d.dx) / 240))
  }
  const up = () => {
    const d = drag.current
    drag.current = null
    if (!d || !card.current) return
    const moved = Math.abs(d.dx) > 6 || Math.abs(d.dy) > 6
    if (Math.abs(d.dx) > 80 || d.dy < -40 || !moved) return onDismiss()
    card.current.style.transition = 'transform 250ms ease, opacity 250ms ease'
    card.current.style.transform = ''
    card.current.style.opacity = ''
  }

  return (
    <div
      ref={card}
      role="status"
      onPointerEnter={(e) => e.pointerType === 'mouse' && setHovered(true)}
      onPointerLeave={(e) => {
        if (e.pointerType === 'mouse') setHovered(false)
        if (drag.current) up()
      }}
      onPointerDown={down}
      onPointerMove={move}
      onPointerUp={up}
      className="animate-toast pointer-events-auto flex cursor-pointer touch-pan-y select-none items-center gap-3 rounded-xl border border-white/[0.08] bg-[#26262c]/95 px-3.5 py-3 text-sm shadow-2xl shadow-black/50 backdrop-blur"
    >
      <Avatar person={latest.by} className="size-8 text-xs" />
      <p className="min-w-0 flex-1 leading-snug text-dim">
        <span className="font-semibold text-fg">{latest.by.name}</span> {describeActivity(latest, toast.entries.length, total)}
      </p>
      <OriginIcon origin={latest.origin} />
    </div>
  )
}
