import { Ban, CalendarClock, ChevronDown, ChevronLeft, ChevronRight, Search, Undo2 } from 'lucide-react'
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { Avatar } from '../../components/Avatar'
import { Markdown } from '../../components/Markdown'
import { Button, Field, fieldClass, Modal } from '../../components/Modal'
import { api, type BanEntry, type BanList, type KnownUser } from '../../lib/api'
import { formatMoment, fromNow } from '../../lib/format'
import { useToast } from '../../state/toast'
import { ago, Card, Chip, usePoll } from './kit'

const label = (b: BanEntry) => b.name ?? b.email ?? b.id ?? b.key

type Target = { who: { id: string } | { email: string }; name: string; sub: string | null; avatar: string | null }

type Duration = { kind: 'for'; seconds: number } | { kind: 'forever' } | { kind: 'date' }

const PRESETS: { label: string; duration: Duration }[] = [
  { label: '1 hour', duration: { kind: 'for', seconds: 3600 } },
  { label: '1 day', duration: { kind: 'for', seconds: 86400 } },
  { label: '1 week', duration: { kind: 'for', seconds: 7 * 86400 } },
  { label: '30 days', duration: { kind: 'for', seconds: 30 * 86400 } },
  { label: 'Permanent', duration: { kind: 'forever' } },
]

const MAX_REASON = 2000

function localInput(ms: number) {
  const d = new Date(ms)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}

function sameDuration(a: Duration, b: Duration) {
  return a.kind === b.kind && (a.kind !== 'for' || (b.kind === 'for' && a.seconds === b.seconds))
}

function PickStep({ known, bans, onPick }: { known: KnownUser[]; bans: BanEntry[]; onPick: (t: Target) => void }) {
  const [q, setQ] = useState('')
  const [manual, setManual] = useState('')
  const banned = useMemo(() => new Set(bans.map((b) => b.key)), [bans])
  const people = useMemo(() => {
    const needle = q.trim().toLowerCase()
    return known.filter(
      (u) =>
        !u.admin &&
        !banned.has(u.id.toLowerCase()) &&
        !(u.email && banned.has(u.email.toLowerCase())) &&
        (!needle || `${u.name} ${u.email ?? ''} ${u.id}`.toLowerCase().includes(needle)),
    )
  }, [known, banned, q])

  const value = manual.trim()
  return (
    <>
      <Field label="Search people who have signed in">
        <div className="relative">
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-faint" />
          <input autoFocus value={q} onChange={(e) => setQ(e.target.value)} placeholder="Name or email" className={`${fieldClass} pl-9`} />
        </div>
      </Field>
      <ul className="scroll-thin mt-2 max-h-56 overflow-y-auto">
        {people.map((u) => (
          <li key={u.id}>
            <button
              type="button"
              onClick={() => onPick({ who: { id: u.id }, name: u.name, sub: u.email ?? u.id, avatar: u.avatar })}
              className="flex w-full items-center gap-3 rounded-md px-2 py-2 text-left hover:bg-white/[0.08]"
            >
              <Avatar person={u} className="size-8 text-sm" />
              <span className="min-w-0 flex-1">
                <span className="block truncate text-sm font-semibold">{u.name}</span>
                <span className="block truncate text-xs text-dim">{u.email ?? u.id}</span>
              </span>
              <ChevronRight className="size-4 shrink-0 text-dim" />
            </button>
          </li>
        ))}
        {people.length === 0 && <li className="px-2 py-3 text-sm text-dim">No one matches.</li>}
      </ul>
      <form
        className="mt-4 border-t border-white/[0.07] pt-4"
        onSubmit={(e) => {
          e.preventDefault()
          if (!value) return
          const isEmail = value.includes('@')
          const match = known.find((u) => (isEmail ? u.email?.toLowerCase() === value.toLowerCase() : u.id === value))
          onPick({ who: isEmail ? { email: value } : { id: value }, name: match?.name ?? value, sub: match ? value : null, avatar: match?.avatar ?? null })
        }}
      >
        <Field label="Or a Slack user ID or email">
          <div className="flex gap-2">
            <input value={manual} onChange={(e) => setManual(e.target.value)} placeholder="U0123ABCD or name@example.com" className={fieldClass} />
            <Button type="submit" variant="ghost" className="bg-white/[0.07]" disabled={!value}>
              Next
            </Button>
          </div>
        </Field>
      </form>
    </>
  )
}

function ConfirmStep({ target, busy, onBack, onConfirm }: { target: Target; busy: boolean; onBack: () => void; onConfirm: (reason: string, until: number | null) => void }) {
  const [reason, setReason] = useState('')
  const [preview, setPreview] = useState(false)
  const [duration, setDuration] = useState<Duration>({ kind: 'for', seconds: 86400 })
  const [date, setDate] = useState(() => localInput(Math.ceil((Date.now() + 86400_000) / 3600_000) * 3600_000))

  const [now, setNow] = useState(() => Date.now() / 1000)
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now() / 1000), 15_000)
    return () => clearInterval(id)
  }, [])
  const until = duration.kind === 'forever' ? null : duration.kind === 'for' ? Math.round(now + duration.seconds) : Math.round(new Date(date).getTime() / 1000)
  const badDate = duration.kind === 'date' && (until == null || !Number.isFinite(until) || until <= now)
  const text = reason.trim()
  const ready = !!text && !badDate && !busy

  const chip = (active: boolean) =>
    `inline-flex h-8 items-center gap-1.5 rounded-full px-3.5 text-xs font-semibold transition ${active ? 'bg-fg text-canvas' : 'bg-white/[0.07] text-dim hover:bg-white/[0.12] hover:text-fg'}`

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault()
        if (ready) onConfirm(text, until)
      }}
    >
      <div className="flex items-center gap-3 rounded-lg bg-white/[0.05] p-3">
        <Avatar person={{ name: target.name, avatar: target.avatar }} className="size-10 text-base" />
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-semibold">{target.name}</div>
          {target.sub && <div className="truncate text-xs text-dim">{target.sub}</div>}
        </div>
        <Button variant="ghost" className="h-8 px-3 text-xs" onClick={onBack} disabled={busy}>
          <ChevronLeft className="size-4" />
          Change
        </Button>
      </div>

      <div className="mt-5">
        <div className="mb-1.5 flex items-center justify-between gap-3">
          <label htmlFor="ban-reason" className="text-xs font-medium text-dim">
            Reason
          </label>
          <div role="tablist" aria-label="Reason editor" className="flex rounded-full bg-white/[0.06] p-0.5 text-xs font-medium">
            {(['Write', 'Preview'] as const).map((tab) => {
              const on = (tab === 'Preview') === preview
              return (
                <button
                  key={tab}
                  type="button"
                  role="tab"
                  aria-selected={on}
                  onClick={() => setPreview(tab === 'Preview')}
                  className={`rounded-full px-3 py-1 transition ${on ? 'bg-white/[0.14] text-fg' : 'text-dim hover:text-fg'}`}
                >
                  {tab}
                </button>
              )
            })}
          </div>
        </div>
        {preview ? (
          <div className="scroll-thin max-h-60 min-h-[8.5rem] overflow-y-auto rounded-md bg-white/[0.04] px-3 py-2.5">
            {text ? <Markdown>{reason}</Markdown> : <p className="text-sm text-faint">Nothing to preview yet.</p>}
          </div>
        ) : (
          <textarea
            id="ban-reason"
            autoFocus
            rows={5}
            value={reason}
            maxLength={MAX_REASON}
            onChange={(e) => setReason(e.target.value)}
            placeholder="Why they're banned. They'll see this. Markdown works."
            className={`${fieldClass} scroll-thin min-h-[8.5rem] resize-y text-sm leading-relaxed`}
          />
        )}
        <div className="mt-1 flex justify-between text-[11px] text-faint">
          <span>Shown to them when they open the app.</span>
          {reason.length > MAX_REASON - 300 && <span className="tabular">{MAX_REASON - reason.length} left</span>}
        </div>
      </div>

      <div className="mt-5">
        <span className="mb-1.5 block text-xs font-medium text-dim">How long</span>
        <div className="flex flex-wrap gap-1.5">
          {PRESETS.map((p) => (
            <button key={p.label} type="button" aria-pressed={sameDuration(duration, p.duration)} onClick={() => setDuration(p.duration)} className={chip(sameDuration(duration, p.duration))}>
              {p.label}
            </button>
          ))}
          <button type="button" aria-pressed={duration.kind === 'date'} onClick={() => setDuration({ kind: 'date' })} className={chip(duration.kind === 'date')}>
            <CalendarClock className="size-3.5" />
            Until date...
          </button>
        </div>
        {duration.kind === 'date' && (
          <input
            type="datetime-local"
            aria-label="Ban ends at"
            value={date}
            min={localInput(now * 1000)}
            onChange={(e) => setDate(e.target.value)}
            className={`${fieldClass} mt-2 [color-scheme:dark]`}
          />
        )}
        <p className={`mt-2 text-sm ${badDate ? 'text-danger' : 'text-dim'}`}>
          {badDate ? (
            'Pick a time in the future.'
          ) : until == null ? (
            <>
              <span className="text-fg">Permanent.</span> They stay banned until an admin unbans them.
            </>
          ) : (
            <>
              <span className="text-fg">Ends {formatMoment(until)}</span>, {fromNow(until)}
            </>
          )}
        </p>
      </div>

      <div className="mt-6 flex justify-end gap-2">
        <Button variant="ghost" onClick={onBack} disabled={busy}>
          Back
        </Button>
        <Button type="submit" variant="danger" disabled={!ready} className="min-w-0">
          <Ban className="size-4 shrink-0" />
          <span className="truncate">Ban {target.name}</span>
        </Button>
      </div>
    </form>
  )
}

function BanModal({ known, bans, onClose, onBanned }: { known: KnownUser[]; bans: BanEntry[]; onClose: () => void; onBanned: (l: BanList) => void }) {
  const toast = useToast()
  const [target, setTarget] = useState<Target | null>(null)
  const [busy, setBusy] = useState(false)

  const ban = async (t: Target, reason: string, until: number | null) => {
    setBusy(true)
    try {
      onBanned(await api.ban({ ...t.who, reason, until }))
      toast.show(`${t.name} is banned`)
      onClose()
    } catch (err) {
      toast.error(err)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal title="Ban someone" onClose={onClose} dismissable={!busy}>
      {target ? (
        <ConfirmStep target={target} busy={busy} onBack={() => setTarget(null)} onConfirm={(reason, until) => void ban(target, reason, until)} />
      ) : (
        <PickStep known={known} bans={bans} onPick={setTarget} />
      )}
    </Modal>
  )
}

function Reason({ text }: { text: string }) {
  const ref = useRef<HTMLDivElement>(null)
  const [open, setOpen] = useState(false)
  const [overflows, setOverflows] = useState(false)

  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    const check = () => setOverflows(el.scrollHeight > el.clientHeight + 1)
    check()
    const ro = new ResizeObserver(check)
    ro.observe(el)
    return () => ro.disconnect()
  }, [text])

  const clamped = !open
  return (
    <div className="mt-2">
      <div
        ref={ref}
        className={`${clamped ? 'max-h-[4.6rem] overflow-hidden' : ''} ${clamped && overflows ? '[mask-image:linear-gradient(to_bottom,black_55%,transparent)]' : ''}`}
      >
        <Markdown>{text}</Markdown>
      </div>
      {(overflows || open) && (
        <button type="button" onClick={() => setOpen((v) => !v)} className="mt-1 inline-flex items-center gap-1 text-xs font-medium text-dim hover:text-fg">
          {open ? 'Show less' : 'Show more'}
          <ChevronDown className={`size-3.5 transition-transform ${open ? 'rotate-180' : ''}`} />
        </button>
      )}
    </div>
  )
}

export function BansCard({ known, active }: { known: KnownUser[]; active: boolean }) {
  const { data, setData } = usePoll(api.banList, null, active)
  const toast = useToast()
  const [banning, setBanning] = useState(false)
  const [unbanning, setUnbanning] = useState<BanEntry | null>(null)
  const [busy, setBusy] = useState(false)

  const unban = async (b: BanEntry) => {
    setBusy(true)
    try {
      setData(await api.unban(b.key))
      toast.show(`${label(b)} is no longer banned`)
      setUnbanning(null)
    } catch (err) {
      toast.error(err)
    } finally {
      setBusy(false)
    }
  }

  const avatars = new Map(known.flatMap((u) => [[u.id.toLowerCase(), u.avatar] as const, ...(u.email ? [[u.email.toLowerCase(), u.avatar] as const] : [])]))

  return (
    <Card
      title="Banned"
      aside={
        <Button variant="danger" className="h-8 px-3.5 text-xs" onClick={() => setBanning(true)}>
          <Ban className="size-4" />
          Ban someone
        </Button>
      }
    >
      {data && data.bans.length > 0 ? (
        <ul className="divide-y divide-white/[0.07]">
          {data.bans.map((b) => (
            <li key={b.key} className="flex items-start gap-3 py-3.5">
              <Avatar person={{ name: label(b), avatar: avatars.get(b.key) ?? null }} className="mt-0.5 size-9 text-sm" />
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                  <span className="truncate text-sm font-semibold">{label(b)}</span>
                  {b.until == null ? (
                    <Chip tone="bad">Permanent</Chip>
                  ) : (
                    <span title={`Ends ${formatMoment(b.until)}`}>
                      <Chip tone="warn">Ends {fromNow(b.until)}</Chip>
                    </span>
                  )}
                </div>
                <div className="truncate text-xs text-faint">
                  {[b.name ? (b.email ?? b.id) : null, b.banned_by ? `banned by ${b.banned_by.name}${b.banned ? ` ${ago(b.banned)}` : ''}` : b.banned ? `banned ${ago(b.banned)}` : null]
                    .filter(Boolean)
                    .join(', ')}
                </div>
                {b.reason && <Reason text={b.reason} />}
              </div>
              <Button variant="ghost" className="h-8 shrink-0 px-3 text-xs" onClick={() => setUnbanning(b)}>
                <Undo2 className="size-4" />
                Unban
              </Button>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-sm text-dim">{data ? 'No one is banned.' : 'Loading…'}</p>
      )}
      <p className="mt-3 text-xs text-faint">Banned people see the reason when they open the app, and can't use the web app, their API token, or control music from Slack.</p>
      {banning && data && <BanModal known={known} bans={data.bans} onClose={() => setBanning(false)} onBanned={setData} />}
      {unbanning && (
        <Modal title={`Unban ${label(unbanning)}?`} onClose={() => !busy && setUnbanning(null)} dismissable={!busy}>
          <p className="text-sm leading-relaxed text-dim">They'll be able to use the web app, their API token and the Slack bot again right away. You can ban them again at any time.</p>
          <div className="mt-6 flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setUnbanning(null)} disabled={busy}>
              Cancel
            </Button>
            <Button onClick={() => void unban(unbanning)} disabled={busy}>
              <Undo2 className="size-4" />
              Unban
            </Button>
          </div>
        </Modal>
      )}
    </Card>
  )
}
