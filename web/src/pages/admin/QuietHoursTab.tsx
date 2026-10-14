import { Lock, Moon, RotateCcw, Sun, Unlock, Undo2 } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Button, Field, fieldClass, Modal } from '../../components/Modal'
import { api, type QuietAdmin, type QuietSettings } from '../../lib/api'
import { clockLabel, timeLabel } from '../../lib/playback'
import { useToast } from '../../state/toast'
import { ErrorState, PageSpinner } from '../Message'
import { ago, Banner, Card, duration, usePoll } from './kit'

function useNow(active: boolean) {
  const [now, setNow] = useState(() => Date.now() / 1000)
  useEffect(() => {
    if (!active) return
    const timer = setInterval(() => setNow(Date.now() / 1000), 1000)
    return () => clearInterval(timer)
  }, [active])
  return now
}

function PhaseCard({ data, busy, onAction }: { data: QuietAdmin; busy: boolean; onAction: (a: 'unlock' | 'lock' | 'clear') => void }) {
  const { status } = data
  const now = useNow(status.phase !== 'locked')
  const override = status.override
  const until = status.until ? clockLabel(status.until) : null
  const btn = 'h-9 px-4'
  const inWindow = !!status.starts_at && !!status.until_ts && status.starts_at <= now && now < status.until_ts

  let banner
  if (!status.enabled) {
    banner = <Banner tone="neutral" icon={<Sun />} title="Quiet hours are off">Speakers can play at any time.</Banner>
  } else if (status.phase === 'locked') {
    banner = (
      <Banner tone="bad" icon={<Lock />} title={`Locked until ${until ?? 'morning'}`}>
        Playback is off. Search, playlists, the library and the queue still work.
      </Banner>
    )
  } else if (status.phase === 'grace') {
    const left = status.locks_at ? Math.max(0, status.locks_at - now) : null
    banner = (
      <Banner tone="warn" icon={<Moon />} title="Winding down">
        {status.locks_at
          ? `Playback locks at ${timeLabel(status.locks_at)} (in ${duration(left ?? 0)}) unless something plays.`
          : `Playback locks ${Math.round((status.grace_s ?? 300) / 60)} min after the music stops.`}{' '}
        Quiet hours until {until}.
      </Banner>
    )
  } else {
    banner = (
      <Banner tone="good" icon={<Sun />} title="Open">
        {override?.kind === 'unlocked'
          ? `Unlocked for tonight, until ${timeLabel(override.until_ts)}.`
          : status.starts_at
            ? `Quiet hours start at ${timeLabel(status.starts_at)} (${status.window}).`
            : `Quiet hours ${status.window ?? ''}.`}
      </Banner>
    )
  }

  return (
    <div>
      {banner}
      {override && (
        <p className="mt-3 text-sm text-dim">
          {override.kind === 'unlocked' ? 'Unlocked' : 'Locked'} by hand{override.by ? ` by ${override.by.name}` : ''} until {timeLabel(override.until_ts)}.
        </p>
      )}
      {status.enabled && (
        <div className="mt-4 flex flex-wrap gap-2">
          {status.phase === 'locked' && (
            <Button className={btn} disabled={busy} onClick={() => onAction('unlock')}>
              <Unlock className="size-4" />
              Unlock until {until ?? 'morning'}
            </Button>
          )}
          {status.phase === 'grace' && (
            <Button variant="ghost" className={`${btn} bg-white/10`} disabled={busy} onClick={() => onAction('lock')}>
              <Lock className="size-4" />
              Lock now
            </Button>
          )}
          {(status.phase === 'grace' || (status.phase === 'open' && !override)) && (
            <Button variant="ghost" className={`${btn} bg-white/10`} disabled={busy} onClick={() => onAction('unlock')}>
              <Unlock className="size-4" />
              {status.phase === 'grace' ? `Keep unlocked until ${until ?? 'morning'}` : 'Skip tonight'}
            </Button>
          )}
          {status.phase === 'open' && override?.kind === 'unlocked' && inWindow && (
            <Button variant="ghost" className={`${btn} bg-white/10`} disabled={busy} onClick={() => onAction('lock')}>
              <Lock className="size-4" />
              Lock now
            </Button>
          )}
          {override && (
            <Button variant="ghost" className={`${btn} bg-white/10`} disabled={busy} onClick={() => onAction('clear')}>
              <Undo2 className="size-4" />
              Clear override
            </Button>
          )}
        </div>
      )}
    </div>
  )
}

function Toggle({ on, onChange, label }: { on: boolean; onChange: (v: boolean) => void; label: string }) {
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

function SettingsForm({ settings, onSave, onReset, busy }: { settings: QuietSettings; onSave: (body: Partial<Pick<QuietSettings, 'enabled' | 'start' | 'end' | 'grace_min'>>) => void; onReset: () => void; busy: boolean }) {
  const [enabled, setEnabled] = useState(settings.enabled)
  const [start, setStart] = useState(settings.start)
  const [end, setEnd] = useState(settings.end)
  const [grace, setGrace] = useState(String(settings.grace_min))

  const graceN = Number(grace)
  const valid = !!start && !!end && start !== end && Number.isInteger(graceN) && graceN >= 0 && graceN <= 240
  const dirty = enabled !== settings.enabled || start !== settings.start || end !== settings.end || graceN !== settings.grace_min

  return (
    <Card title="Schedule">
      <form
        className="space-y-4"
        onSubmit={(e) => {
          e.preventDefault()
          if (valid && dirty) onSave({ enabled, start, end, grace_min: graceN })
        }}
      >
        <div className="flex items-center justify-between gap-4">
          <div>
            <div className="text-sm font-semibold">Quiet hours</div>
            <div className="text-xs text-dim">Turn playback off overnight.</div>
          </div>
          <Toggle on={enabled} onChange={setEnabled} label="Quiet hours enabled" />
        </div>
        <div className="grid grid-cols-2 gap-3 max-sm:grid-cols-1">
          <Field label="Starts">
            <input type="time" required value={start} onChange={(e) => setStart(e.target.value)} className={fieldClass} />
          </Field>
          <Field label="Ends">
            <input type="time" required value={end} onChange={(e) => setEnd(e.target.value)} className={fieldClass} />
          </Field>
        </div>
        <Field label="Grace period (minutes of silence before locking)">
          <input type="number" inputMode="numeric" min={0} max={240} value={grace} onChange={(e) => setGrace(e.target.value)} className={`${fieldClass} sm:max-w-40`} />
        </Field>
        {start && end && start !== end && (
          <p className="text-sm text-dim">
            Quiet from {clockLabel(start)} to {clockLabel(end)}.
          </p>
        )}
        <div className="flex flex-wrap items-center gap-3 pt-1">
          <Button type="submit" disabled={busy || !valid || !dirty}>
            Save
          </Button>
          <span className="text-xs text-dim">
            {settings.source === 'env' ? (
              <>Using the server default{settings.env_window ? ` (QUIET_HOURS=${settings.env_window})` : ''}.</>
            ) : (
              <>
                Changed{settings.updated_by ? ` by ${settings.updated_by.name}` : ''}
                {settings.updated_at ? ` ${ago(settings.updated_at)}` : ''}.
              </>
            )}
          </span>
          {settings.source === 'admin' && (
            <button type="button" onClick={onReset} disabled={busy} className="ml-auto inline-flex items-center gap-1.5 text-xs font-semibold text-dim hover:text-fg disabled:opacity-50">
              <RotateCcw className="size-3.5" />
              Reset to default
            </button>
          )}
        </div>
      </form>
    </Card>
  )
}

export function QuietHoursTab({ active }: { active: boolean }) {
  const { data, setData, error, reload } = usePoll(api.adminQuietHours, 15000, active)
  const toast = useToast()
  const [busy, setBusy] = useState(false)
  const [confirmLock, setConfirmLock] = useState(false)

  if (!data) return error ? <ErrorState title="Couldn't load quiet hours" error={error} onRetry={() => void reload()} /> : <PageSpinner />

  const run = async (job: () => Promise<QuietAdmin>, done: string) => {
    setBusy(true)
    try {
      setData(await job())
      toast.show(done)
      setConfirmLock(false)
    } catch (err) {
      toast.error(err)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-4">
      <PhaseCard
        data={data}
        busy={busy}
        onAction={(a) => (a === 'lock' ? setConfirmLock(true) : void run(() => api.quietOverride(a), a === 'unlock' ? 'Speakers unlocked' : 'Override cleared'))}
      />
      <SettingsForm
        key={JSON.stringify(data.settings)}
        settings={data.settings}
        busy={busy}
        onSave={(body) => void run(() => api.saveQuietHours(body), 'Quiet hours saved')}
        onReset={() => void run(() => api.saveQuietHours({ reset: true }), 'Back to the server default')}
      />
      {confirmLock && (
        <Modal title="Lock the speakers now?" onClose={() => !busy && setConfirmLock(false)} dismissable={!busy}>
          <p className="text-sm leading-relaxed text-dim">
            Playback stops right away and stays off until {data.status.until ? clockLabel(data.status.until) : 'quiet hours end'}. Anything playing is paused.
          </p>
          <div className="mt-6 flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setConfirmLock(false)} disabled={busy}>
              Cancel
            </Button>
            <Button onClick={() => void run(() => api.quietOverride('lock'), 'Speakers locked')} disabled={busy}>
              <Lock className="size-4" />
              Lock now
            </Button>
          </div>
        </Modal>
      )}
    </div>
  )
}
