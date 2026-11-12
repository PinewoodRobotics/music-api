import { Ban, Search, Undo2 } from 'lucide-react'
import { useMemo, useState } from 'react'
import { Avatar } from '../../components/Avatar'
import { Button, Field, fieldClass, Modal } from '../../components/Modal'
import { api, type BanEntry, type BanList, type KnownUser } from '../../lib/api'
import { useToast } from '../../state/toast'
import { ago, Card, usePoll } from './kit'

const label = (b: BanEntry) => b.name ?? b.email ?? b.id ?? b.key

function BanModal({ known, bans, onClose, onBanned }: { known: KnownUser[]; bans: BanEntry[]; onClose: () => void; onBanned: (l: BanList) => void }) {
  const toast = useToast()
  const [q, setQ] = useState('')
  const [manual, setManual] = useState('')
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
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

  const ban = async (who: { id: string } | { email: string }) => {
    setBusy(true)
    try {
      onBanned(await api.ban({ ...who, reason: reason.trim() || undefined }))
      toast.show('Banned')
      onClose()
    } catch (err) {
      toast.error(err)
    } finally {
      setBusy(false)
    }
  }

  const value = manual.trim()
  return (
    <Modal title="Ban someone" onClose={onClose} dismissable={!busy}>
      <Field label="Reason (optional)">
        <input value={reason} onChange={(e) => setReason(e.target.value)} maxLength={200} placeholder="Why they're banned" className={fieldClass} />
      </Field>
      <div className="mt-4">
        <Field label="Search people who have signed in">
          <div className="relative">
            <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-faint" />
            <input autoFocus value={q} onChange={(e) => setQ(e.target.value)} placeholder="Name or email" className={`${fieldClass} pl-9`} />
          </div>
        </Field>
      </div>
      <ul className="scroll-thin mt-2 max-h-56 overflow-y-auto">
        {people.map((u) => (
          <li key={u.id}>
            <button
              type="button"
              disabled={busy}
              onClick={() => void ban({ id: u.id })}
              className="flex w-full items-center gap-3 rounded-md px-2 py-2 text-left hover:bg-white/[0.08] disabled:opacity-50"
            >
              <Avatar person={u} className="size-8 text-sm" />
              <span className="min-w-0 flex-1">
                <span className="block truncate text-sm font-semibold">{u.name}</span>
                <span className="block truncate text-xs text-dim">{u.email ?? u.id}</span>
              </span>
              <Ban className="size-4 shrink-0 text-dim" />
            </button>
          </li>
        ))}
        {people.length === 0 && <li className="px-2 py-3 text-sm text-dim">No one matches.</li>}
      </ul>
      <form
        className="mt-4 border-t border-white/[0.07] pt-4"
        onSubmit={(e) => {
          e.preventDefault()
          if (value) void ban(value.includes('@') ? { email: value } : { id: value })
        }}
      >
        <Field label="Or a Slack user ID or email">
          <div className="flex gap-2">
            <input value={manual} onChange={(e) => setManual(e.target.value)} placeholder="U0123ABCD or name@example.com" className={fieldClass} />
            <Button type="submit" variant="danger" disabled={busy || !value}>
              Ban
            </Button>
          </div>
        </Field>
      </form>
    </Modal>
  )
}

export function BansCard({ known, active }: { known: KnownUser[]; active: boolean }) {
  const { data, setData } = usePoll(api.banList, null, active)
  const toast = useToast()
  const [banning, setBanning] = useState(false)
  const [busyKey, setBusyKey] = useState<string | null>(null)

  const unban = async (b: BanEntry) => {
    setBusyKey(b.key)
    try {
      setData(await api.unban(b.key))
      toast.show(`${label(b)} is no longer banned`)
    } catch (err) {
      toast.error(err)
    } finally {
      setBusyKey(null)
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
            <li key={b.key} className="flex items-center gap-3 py-3">
              <Avatar person={{ name: label(b), avatar: avatars.get(b.key) ?? null }} className="size-9 text-sm" />
              <div className="min-w-0 flex-1">
                <div className="truncate text-sm font-semibold">{label(b)}</div>
                <div className="truncate text-xs text-faint">
                  {[b.name ? (b.email ?? b.id) : null, b.reason, b.banned_by ? `banned by ${b.banned_by.name}${b.banned ? ` ${ago(b.banned)}` : ''}` : null]
                    .filter(Boolean)
                    .join(', ')}
                </div>
              </div>
              <Button variant="ghost" className="h-8 px-3 text-xs" disabled={busyKey === b.key} onClick={() => void unban(b)}>
                <Undo2 className="size-4" />
                Unban
              </Button>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-sm text-dim">{data ? 'No one is banned.' : 'Loading…'}</p>
      )}
      <p className="mt-3 text-xs text-faint">Banned people can't sign in, use the web app or their API token, or control music from Slack.</p>
      {banning && data && <BanModal known={known} bans={data.bans} onClose={() => setBanning(false)} onBanned={setData} />}
    </Card>
  )
}
