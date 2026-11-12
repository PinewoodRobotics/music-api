import { Plus, Search, UserMinus } from 'lucide-react'
import { useMemo, useState } from 'react'
import { Avatar } from '../../components/Avatar'
import { Button, Field, fieldClass, Modal } from '../../components/Modal'
import { api, type AdminEntry, type AdminList } from '../../lib/api'
import { useToast } from '../../state/toast'
import { ErrorState, PageSpinner } from '../Message'
import { BansCard } from './BansCard'
import { ago, Card, Chip, usePoll } from './kit'

const label = (a: AdminEntry) => a.name ?? a.email ?? a.id ?? a.key

function AddModal({ list, onClose, onAdded }: { list: AdminList; onClose: () => void; onAdded: (l: AdminList) => void }) {
  const toast = useToast()
  const [q, setQ] = useState('')
  const [manual, setManual] = useState('')
  const [busy, setBusy] = useState(false)
  const people = useMemo(() => {
    const needle = q.trim().toLowerCase()
    return list.known.filter((u) => !u.admin && (!needle || `${u.name} ${u.email ?? ''} ${u.id}`.toLowerCase().includes(needle)))
  }, [list.known, q])

  const add = async (who: { id: string } | { email: string }) => {
    setBusy(true)
    try {
      onAdded(await api.addAdmin(who))
      toast.show('Admin added')
      onClose()
    } catch (err) {
      toast.error(err)
    } finally {
      setBusy(false)
    }
  }

  const value = manual.trim()
  return (
    <Modal title="Add admin" onClose={onClose} dismissable={!busy}>
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
              disabled={busy}
              onClick={() => void add({ id: u.id })}
              className="flex w-full items-center gap-3 rounded-md px-2 py-2 text-left hover:bg-white/[0.08] disabled:opacity-50"
            >
              <Avatar person={u} className="size-8 text-sm" />
              <span className="min-w-0 flex-1">
                <span className="block truncate text-sm font-semibold">{u.name}</span>
                <span className="block truncate text-xs text-dim">{u.email ?? u.id}</span>
              </span>
              <Plus className="size-4 shrink-0 text-dim" />
            </button>
          </li>
        ))}
        {people.length === 0 && <li className="px-2 py-3 text-sm text-dim">{q ? 'No one matches.' : 'Everyone who has signed in is already an admin.'}</li>}
      </ul>
      <form
        className="mt-4 border-t border-white/[0.07] pt-4"
        onSubmit={(e) => {
          e.preventDefault()
          if (value) void add(value.includes('@') ? { email: value } : { id: value })
        }}
      >
        <Field label="Or a Slack user ID or email">
          <div className="flex gap-2">
            <input value={manual} onChange={(e) => setManual(e.target.value)} placeholder="U0123ABCD or name@example.com" className={fieldClass} />
            <Button type="submit" disabled={busy || !value}>
              Add
            </Button>
          </div>
        </Field>
      </form>
    </Modal>
  )
}

export function AdminsTab({ active }: { active: boolean }) {
  const { data, setData, error, reload } = usePoll(api.adminList, null, active)
  const toast = useToast()
  const [adding, setAdding] = useState(false)
  const [removing, setRemoving] = useState<AdminEntry | null>(null)
  const [busy, setBusy] = useState(false)

  if (!data) return error ? <ErrorState title="Couldn't load admins" error={error} onRetry={() => void reload()} /> : <PageSpinner />

  const remove = async (a: AdminEntry) => {
    setBusy(true)
    try {
      setData(await api.removeAdmin(a.key))
      toast.show(`${label(a)} is no longer an admin`)
      setRemoving(null)
    } catch (err) {
      toast.error(err)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-4">
      <Card
        title="Admins"
        aside={
          <Button className="h-8 px-3.5 text-xs" onClick={() => setAdding(true)}>
            <Plus className="size-4" />
            Add admin
          </Button>
        }
      >
        <ul className="divide-y divide-white/[0.07]">
          {data.admins.map((a) => (
            <li key={a.key} className="flex items-center gap-3 py-3">
              <Avatar person={{ name: label(a), avatar: a.avatar }} className="size-9 text-sm" />
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                  <span className="truncate text-sm font-semibold">{label(a)}</span>
                  {a.you && <Chip>You</Chip>}
                  {a.source === 'config' && <Chip>Server config</Chip>}
                </div>
                <div className="truncate text-xs text-faint">
                  {a.email && a.name ? `${a.email}` : (a.id ?? '')}
                  {a.source === 'admin' && a.added_by ? `${a.email || a.id ? ', ' : ''}added by ${a.added_by.name}${a.added ? ` ${ago(a.added)}` : ''}` : ''}
                </div>
              </div>
              {a.source !== 'config' && (
                <button
                  type="button"
                  aria-label={`Remove ${label(a)}`}
                  onClick={() => setRemoving(a)}
                  className="grid size-8 shrink-0 place-items-center rounded-full text-dim transition hover:bg-white/10 hover:text-danger"
                >
                  <UserMinus className="size-4" />
                </button>
              )}
            </li>
          ))}
        </ul>
        <p className="mt-3 text-xs text-faint">Admins can manage quiet hours, other admins, updates and services.</p>
      </Card>
      <BansCard known={data.known} active={active} />
      {adding && <AddModal list={data} onClose={() => setAdding(false)} onAdded={setData} />}
      {removing && (
        <Modal title={`Remove ${label(removing)}?`} onClose={() => !busy && setRemoving(null)} dismissable={!busy}>
          <p className="text-sm leading-relaxed text-dim">
            {removing.you ? 'You will lose access to this page.' : 'They will lose access to this page.'} You can add them back at any time.
          </p>
          <div className="mt-6 flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setRemoving(null)} disabled={busy}>
              Cancel
            </Button>
            <Button variant="danger" onClick={() => void remove(removing)} disabled={busy}>
              Remove
            </Button>
          </div>
        </Modal>
      )}
    </div>
  )
}
