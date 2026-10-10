import { History, X } from 'lucide-react'
import { useEffect, useState } from 'react'
import { activity, useActivity } from '../../lib/activity'
import type { ActivityEntry } from '../../lib/api'
import { useMediaQuery } from '../../lib/device'
import { useSwipeDismiss } from '../../lib/useSwipeDismiss'
import { useSession } from '../../state/session'
import { Avatar } from '../Avatar'
import { Modal } from '../Modal'
import { RowsSkeleton } from '../Skeleton'
import { describeActivity, OriginIcon } from './ActivitySentence'

const MAX_ROWS = 300
const JUST_NOW_MS = 10 * 60 * 1000

function useNow(intervalMs: number) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), intervalMs)
    return () => clearInterval(timer)
  }, [intervalMs])
  return now
}

function relative(at: number, now: number) {
  const s = Math.max(0, Math.round((now - at) / 1000))
  if (s < 60) return 'just now'
  const m = Math.round(s / 60)
  if (m < 60) return `${m} min ago`
  return `${Math.round(m / 60)} hr ago`
}

function groupLabel(at: number, now: number) {
  if (now - at < JUST_NOW_MS) return 'Just now'
  const date = new Date(at)
  const hour = date.toLocaleTimeString([], { hour: 'numeric' })
  return date.toDateString() === new Date(now).toDateString() ? hour : `Yesterday, ${hour}`
}

function Row({ entry, mine, now }: { entry: ActivityEntry; mine: boolean; now: number }) {
  const [exact, setExact] = useState(false)
  const absolute = new Date(entry.at).toLocaleString([], { weekday: 'short', hour: 'numeric', minute: '2-digit' })
  return (
    <li>
      <button
        type="button"
        onClick={() => setExact((v) => !v)}
        className="flex w-full items-center gap-3 rounded-lg px-2 py-2.5 text-left hover:bg-white/[0.05] active:bg-white/[0.08]"
      >
        <Avatar person={entry.by} className="size-8 text-xs" />
        <p className="min-w-0 flex-1 text-sm leading-snug text-dim">
          <span className="font-semibold text-fg">{mine ? 'You' : entry.by.name}</span> {describeActivity(entry)}
        </p>
        <OriginIcon origin={entry.origin} />
        <time title={absolute} dateTime={new Date(entry.at).toISOString()} className="shrink-0 text-xs text-faint tabular">
          {exact ? absolute : relative(entry.at, now)}
        </time>
      </button>
    </li>
  )
}

function ActivityList() {
  const { entries, ready } = useActivity()
  const { me } = useSession()
  const now = useNow(30_000)
  const [failed, setFailed] = useState<string | null>(null)

  useEffect(() => {
    activity.load().catch((err) => setFailed(err instanceof Error ? err.message : String(err)))
  }, [])

  if (!ready) return failed ? <p className="p-6 text-sm text-danger">{failed}</p> : <RowsSkeleton count={8} />
  const recent = entries.filter((e) => now - e.at < 24 * 60 * 60 * 1000).reverse().slice(0, MAX_ROWS)
  if (!recent.length)
    return (
      <div className="grid place-items-center px-6 py-16 text-center text-sm text-dim">
        <History className="mb-3 size-8 text-faint" />
        Nothing has happened in the last 24 hours.
      </div>
    )

  const groups: { label: string; items: ActivityEntry[] }[] = []
  for (const entry of recent) {
    const label = groupLabel(entry.at, now)
    const last = groups[groups.length - 1]
    if (last?.label === label) last.items.push(entry)
    else groups.push({ label, items: [entry] })
  }

  return (
    <div className="space-y-4">
      {groups.map((g) => (
        <section key={g.label}>
          <h3 className="sticky top-0 z-10 bg-inherit px-2 pb-1 pt-2 text-xs font-semibold text-faint">{g.label}</h3>
          <ul>
            {g.items.map((e) => (
              <Row key={e.id} entry={e} mine={!!me && e.by?.id === me.id} now={now} />
            ))}
          </ul>
        </section>
      ))}
    </div>
  )
}

export function ActivityPanel({ onClose }: { onClose: () => void }) {
  const phone = useMediaQuery('(max-width: 767px)')
  if (!phone)
    return (
      <Modal title="Activity" onClose={onClose} wide>
        <div className="scroll-thin -mx-2 max-h-[65vh] overflow-y-auto overscroll-contain bg-raised">
          <ActivityList />
        </div>
      </Modal>
    )
  return <ActivitySheet onClose={onClose} />
}

function ActivitySheet({ onClose }: { onClose: () => void }) {
  const { ref, backdropRef, dismiss } = useSwipeDismiss(onClose)
  return (
    <>
      <div ref={backdropRef} className="fixed inset-0 z-[59] bg-black opacity-55" aria-hidden onClick={dismiss} />
      <div
        ref={ref}
        role="dialog"
        aria-modal="true"
        aria-label="Activity"
        className="animate-rise fixed inset-x-0 bottom-0 top-[max(env(safe-area-inset-top),12px)] z-[60] flex touch-none flex-col overflow-hidden overscroll-none rounded-t-2xl bg-raised will-change-transform"
      >
        <button type="button" onClick={dismiss} aria-label="Close" className="mx-auto grid h-7 w-20 shrink-0 place-items-center">
          <span className="h-[5px] w-10 rounded-full bg-white/30" />
        </button>
        <header className="flex items-center justify-between px-5 pb-2">
          <h2 className="font-display text-xl font-bold tracking-tight">Activity</h2>
          <button type="button" onClick={dismiss} aria-label="Close" className="grid size-10 place-items-center rounded-full text-dim active:bg-white/10">
            <X className="size-5" />
          </button>
        </header>
        <div data-swipe-ok className="min-h-0 flex-1 touch-pan-y overflow-y-auto overscroll-contain bg-raised px-3 pb-[max(env(safe-area-inset-bottom),16px)]">
          <ActivityList />
        </div>
      </div>
    </>
  )
}
