import { AlertTriangle, ArrowRight, CheckCircle2, CloudDownload, GitCommitHorizontal, History, Info, Loader2, MinusCircle, RefreshCw, Undo2, XCircle } from 'lucide-react'
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { Button, Field, fieldClass, Modal } from '../../components/Modal'
import { api, type UpdateAuto, type UpdateHistoryEntry, type UpdateInfo, type UpdateRun } from '../../lib/api'
import { clockLabel } from '../../lib/playback'
import { useToast } from '../../state/toast'
import { ErrorState, PageSpinner } from '../Message'
import { ago, Banner, Card, Chip, dateTime, duration, Toggle, usePoll, type Tone } from './kit'

const short = (sha: string | null | undefined) => sha?.slice(0, 7) ?? null

function RunLog({ run, restarting }: { run: UpdateRun; restarting: boolean }) {
  const box = useRef<HTMLDivElement>(null)
  useEffect(() => {
    box.current?.scrollTo(0, box.current.scrollHeight)
  }, [run.log.length, restarting])
  const color = { info: 'text-dim', warn: 'text-[#ffb340]', error: 'text-danger' }
  return (
    <div ref={box} className="scroll-thin mt-3 max-h-64 overflow-auto rounded-md bg-black/50 p-3 font-mono text-[11px] leading-relaxed">
      {run.log.map((l, i) => (
        <div key={i} className={`flex gap-3 ${color[l.level]}`}>
          <span className="shrink-0 text-faint">{new Date(l.t * 1000).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit', second: '2-digit' })}</span>
          <span className="min-w-0 break-words">{l.msg}</span>
        </div>
      ))}
      {restarting && <div className="text-dim">Restarting the server...</div>}
    </div>
  )
}

function RunCard({ run, restarting }: { run: UpdateRun; restarting: boolean }) {
  const running = run.state === 'running'
  const revert = run.action === 'revert'
  const elapsed = (run.finished_at ?? Date.now() / 1000) - run.started_at
  return (
    <Card title={revert ? 'Rollback' : run.auto ? 'Automatic update' : 'Update'}>
      {running ? (
        <Banner tone="neutral" icon={<Loader2 className="animate-spin" />} title={restarting ? 'Restarting the server...' : revert ? 'Rolling back' : 'Updating'}>
          {restarting ? 'The page reconnects on its own. The music keeps playing.' : `${duration(elapsed)} elapsed. Keep this page open or come back later.`}
        </Banner>
      ) : run.state === 'succeeded' ? (
        <Banner tone="good" icon={<CheckCircle2 />} title={revert ? 'Rollback finished' : 'Update finished'}>
          {run.result ?? `Now running ${short(run.to) ?? 'the latest version'}.`}
        </Banner>
      ) : revert ? (
        <Banner tone="bad" icon={<XCircle />} title="Rollback failed">
          {run.result ?? 'See the log below.'}
        </Banner>
      ) : run.state === 'rolled_back' ? (
        <Banner tone="warn" icon={<Undo2 />} title="Update rolled back">
          {run.result ?? 'Something went wrong, so the previous version was restored.'}
        </Banner>
      ) : (
        <Banner tone="bad" icon={<XCircle />} title="Update failed">
          {run.result ?? 'See the log below.'}
        </Banner>
      )}
      <RunLog run={run} restarting={restarting} />
    </Card>
  )
}

function AutoUpdateCard({ auto, busy, onSave }: { auto: UpdateAuto; busy: boolean; onSave: (body: { auto: boolean; time: string }) => void }) {
  const [enabled, setEnabled] = useState(auto.enabled)
  const [time, setTime] = useState(auto.time)
  const dirty = enabled !== auto.enabled || time !== auto.time

  return (
    <Card title="Automatic updates">
      <form
        className="space-y-4"
        onSubmit={(e) => {
          e.preventDefault()
          if (time && dirty) onSave({ auto: enabled, time })
        }}
      >
        <div className="flex items-center justify-between gap-4">
          <div>
            <div className="text-sm font-semibold">Update every night</div>
            <div className="text-xs text-dim">Only when nothing is playing or quiet hours have the speakers locked. Otherwise it tries again the next night.</div>
          </div>
          <Toggle on={enabled} onChange={setEnabled} label="Automatic updates enabled" />
        </div>
        <Field label="Time">
          <input type="time" required value={time} onChange={(e) => setTime(e.target.value)} disabled={!enabled} className={`${fieldClass} disabled:opacity-50 sm:max-w-40`} />
        </Field>
        {enabled && time && <p className="text-sm text-dim">Checks for a new version between {clockLabel(time)} and an hour later.</p>}
        <div className="flex flex-wrap items-center gap-3 pt-1">
          <Button type="submit" disabled={busy || !time || !dirty}>
            Save
          </Button>
          {auto.updated_at ? (
            <span className="text-xs text-dim">
              Changed{auto.updated_by ? ` by ${auto.updated_by.name}` : ''} {ago(auto.updated_at)}.
            </span>
          ) : null}
        </div>
      </form>
    </Card>
  )
}

const OUTCOMES: Record<UpdateHistoryEntry['outcome'], { label: string; tone: Tone; icon: ReactNode }> = {
  updated: { label: 'Updated', tone: 'good', icon: <CheckCircle2 /> },
  reverted: { label: 'Rolled back by hand', tone: 'neutral', icon: <History /> },
  rolled_back: { label: 'Rolled back', tone: 'warn', icon: <Undo2 /> },
  failed: { label: 'Failed', tone: 'bad', icon: <XCircle /> },
  skipped: { label: 'Skipped', tone: 'neutral', icon: <MinusCircle /> },
}

const toneIcon: Record<Tone, string> = { good: 'text-[#34c759]', warn: 'text-[#ffb340]', bad: 'text-danger', neutral: 'text-faint' }

function HistoryCard({ history }: { history: UpdateHistoryEntry[] }) {
  return (
    <Card title="History">
      {history.length === 0 ? (
        <p className="text-sm text-dim">No updates yet.</p>
      ) : (
        <ul className="divide-y divide-white/[0.07]">
          {history.map((h) => {
            const o = OUTCOMES[h.outcome] ?? OUTCOMES.failed
            const from = short(h.from)
            const to = short(h.to)
            return (
              <li key={`${h.id}-${h.at}`} className="flex items-start gap-3 py-2.5">
                <span className={`mt-0.5 shrink-0 [&>svg]:size-4 ${toneIcon[o.tone]}`}>{o.icon}</span>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                    <Chip tone={o.tone}>{o.label}</Chip>
                    {(from || to) && (
                      <span className="inline-flex items-center gap-1 font-mono text-xs text-dim">
                        {from ?? 'unknown'}
                        <ArrowRight className="size-3" />
                        {to ?? 'unknown'}
                      </span>
                    )}
                  </div>
                  {h.result && <div className="mt-1 text-sm leading-snug">{h.result}</div>}
                  <div className="mt-0.5 text-xs text-faint">
                    {h.auto ? 'Automatic' : h.by?.name ? `By ${h.by.name}` : 'By hand'}
                    {h.at ? `, ${dateTime(h.at)}` : ''}
                    {h.count && h.count > 1 ? ` (${h.count} nights in a row)` : ''}
                  </div>
                </div>
              </li>
            )
          })}
        </ul>
      )}
    </Card>
  )
}

function PreviousCard({ data, disabled, onRevert }: { data: UpdateInfo; disabled: boolean; onRevert: () => void }) {
  const prev = data.previous
  return (
    <Card title="Previous version">
      <div className="flex flex-wrap items-center gap-4">
        <div className="min-w-0 flex-1">
          {prev ? (
            <>
              <div className="font-mono text-sm font-semibold">{prev.short ?? 'Unknown commit'}</div>
              {prev.subject && <div className="mt-0.5 text-sm leading-snug text-dim">{prev.subject}</div>}
              {prev.built_at ? <div className="mt-0.5 text-xs text-faint">Built {dateTime(prev.built_at)}</div> : null}
            </>
          ) : (
            <p className="text-sm text-dim">There's no previous version on the Pi yet. One is kept after each update.</p>
          )}
        </div>
        <Button variant="ghost" className="h-9 bg-white/10 px-4" disabled={!prev || disabled} onClick={onRevert}>
          <Undo2 className="size-4" />
          Roll back to previous version
        </Button>
      </div>
    </Card>
  )
}

export function UpdatesTab({ active }: { active: boolean }) {
  const [fast, setFast] = useState(false)
  const { data, setData, error, failures, reload } = usePoll(api.adminUpdate, fast ? 1500 : null, active)
  const toast = useToast()
  const [busy, setBusy] = useState<'check' | 'update' | 'revert' | 'settings' | null>(null)
  const [confirm, setConfirm] = useState(false)
  const [confirmRevert, setConfirmRevert] = useState(false)

  const running = data?.run?.state === 'running'
  useEffect(() => setFast(running), [running])

  if (!data) return error ? <ErrorState title="Couldn't load updates" error={error} onRetry={() => void reload()} /> : <PageSpinner />

  const check = async () => {
    setBusy('check')
    try {
      setData(await api.checkUpdate())
    } catch (err) {
      toast.error(err)
    } finally {
      setBusy(null)
    }
  }

  const start = async () => {
    setBusy('update')
    try {
      setData(await api.startUpdate())
      setConfirm(false)
    } catch (err) {
      toast.error(err)
    } finally {
      setBusy(null)
    }
  }

  const revert = async () => {
    setBusy('revert')
    try {
      setData(await api.revertUpdate())
      setConfirmRevert(false)
    } catch (err) {
      toast.error(err)
    } finally {
      setBusy(null)
    }
  }

  const saveAuto = async (body: { auto: boolean; time: string }) => {
    setBusy('settings')
    try {
      setData(await api.saveAutoUpdate(body))
      toast.show('Automatic updates saved')
    } catch (err) {
      toast.error(err)
    } finally {
      setBusy(null)
    }
  }

  const { deployed, latest, build } = data
  const building = !!latest && !!build && build.commit !== latest.commit && data.behind > 0
  const canUpdate = data.configured && data.behind > 0 && !!build?.ready && !running && !building
  const restarting = running && failures > 0
  const upToDate = data.configured && data.behind === 0 && !running
  const changes = data.changes

  return (
    <div className="space-y-4">
      {!data.configured && (
        <Banner tone="warn" icon={<AlertTriangle />} title="Updates are not set up yet">
          {data.setup_hint ?? 'The update remote on the Pi needs a deploy key.'}
        </Banner>
      )}

      <Card
        title="Version"
        aside={
          <Button variant="ghost" className="h-8 bg-white/10 px-3.5 text-xs" onClick={() => void check()} disabled={busy !== null || running}>
            <RefreshCw className={`size-3.5 ${busy === 'check' ? 'animate-spin' : ''}`} />
            Check for updates
          </Button>
        }
      >
        <div className="grid gap-4 sm:grid-cols-2">
          <VersionBlock label="Deployed" short={deployed?.short} subject={deployed?.subject} date={deployed?.date ?? deployed?.built_at} />
          <VersionBlock label="Latest on GitHub" short={latest?.short} subject={latest?.subject} date={latest?.date} />
        </div>
        {data.fetch_error ? (
          <p className="mt-4 text-sm text-danger">Couldn't reach GitHub: {data.fetch_error}</p>
        ) : (
          data.fetched_at && <p className="mt-4 text-xs text-faint">Checked {ago(data.fetched_at)}</p>
        )}
        <div className="mt-4 flex flex-wrap items-center gap-3 border-t border-white/[0.07] pt-4">
          {upToDate ? (
            <Chip tone="good">Up to date</Chip>
          ) : data.behind > 0 ? (
            <Chip tone="warn">{data.behind} update{data.behind === 1 ? '' : 's'} available</Chip>
          ) : null}
          {building && (
            <span className="inline-flex items-center gap-2 text-sm text-dim">
              <Loader2 className="size-4 animate-spin" />
              GitHub is still building the latest version...
            </span>
          )}
          <Button className="ml-auto h-9" disabled={!canUpdate || busy !== null} onClick={() => setConfirm(true)}>
            <CloudDownload className="size-4" />
            Update
          </Button>
        </div>
      </Card>

      {data.run && <RunCard run={data.run} restarting={restarting} />}

      {data.behind > 0 && (
        <>
          <Card title="What's new">
            <ul className="divide-y divide-white/[0.07]">
              {data.commits.map((c) => (
                <li key={c.commit} className="flex items-start gap-3 py-2.5">
                  <GitCommitHorizontal className="mt-0.5 size-4 shrink-0 text-faint" />
                  <div className="min-w-0 flex-1">
                    <div className="text-sm leading-snug">{c.subject}</div>
                    <div className="mt-0.5 text-xs text-faint">
                      <span className="font-mono">{c.short}</span> - {c.author}, {ago(c.date)}
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          </Card>

          <Card title="What will happen">
            {changes.restarts.length > 0 ? (
              <div className="flex flex-wrap items-center gap-1.5">
                <span className="mr-1 text-sm text-dim">Restarts</span>
                {changes.restarts.map((r) => (
                  <Chip key={r}>{r}</Chip>
                ))}
              </div>
            ) : (
              <p className="text-sm text-dim">No services need a restart.</p>
            )}
            <p className="mt-3 flex items-start gap-2 text-sm text-dim">
              <Info className="mt-0.5 size-4 shrink-0" />
              The music keeps playing. Soloist and AirPlay are not restarted.
            </p>
            {changes.notes.length > 0 && (
              <div className="mt-4 space-y-2">
                {changes.notes.map((n) => (
                  <Banner key={n} tone="warn" icon={<AlertTriangle />} title={n} />
                ))}
              </div>
            )}
          </Card>
        </>
      )}

      <AutoUpdateCard key={JSON.stringify(data.auto)} auto={data.auto} busy={busy !== null} onSave={(body) => void saveAuto(body)} />

      <PreviousCard data={data} disabled={busy !== null || running} onRevert={() => setConfirmRevert(true)} />

      <HistoryCard history={data.history} />

      {confirm && (
        <Modal title="Update the music server?" onClose={() => busy === null && setConfirm(false)} dismissable={busy === null}>
          <p className="text-sm leading-relaxed text-dim">
            This installs {latest?.short ?? 'the latest version'}
            {data.behind ? ` (${data.behind} change${data.behind === 1 ? '' : 's'})` : ''} and restarts {changes.restarts.length ? changes.restarts.join(', ') : 'the server'}. The music keeps playing. If something goes wrong, the previous version is restored.
          </p>
          <div className="mt-6 flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setConfirm(false)} disabled={busy !== null}>
              Cancel
            </Button>
            <Button onClick={() => void start()} disabled={busy !== null}>
              <CloudDownload className="size-4" />
              Update
            </Button>
          </div>
        </Modal>
      )}

      {confirmRevert && (
        <Modal title="Roll back to the previous version?" onClose={() => busy === null && setConfirmRevert(false)} dismissable={busy === null}>
          <p className="text-sm leading-relaxed text-dim">
            This puts {data.previous?.short ?? 'the previous version'} back in place of {deployed?.short ?? 'the current version'} and restarts what changed between them. The music keeps playing. If the previous version fails its health check, the current one is put back.
          </p>
          <div className="mt-6 flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setConfirmRevert(false)} disabled={busy !== null}>
              Cancel
            </Button>
            <Button onClick={() => void revert()} disabled={busy !== null}>
              <Undo2 className="size-4" />
              Roll back
            </Button>
          </div>
        </Modal>
      )}
    </div>
  )
}

function VersionBlock({ label, short, subject, date }: { label: string; short?: string; subject?: string | null; date?: number | null }) {
  return (
    <div className="min-w-0">
      <div className="text-xs font-medium text-dim">{label}</div>
      {short ? (
        <>
          <div className="mt-1 font-mono text-lg font-semibold">{short}</div>
          {subject && <div className="mt-0.5 text-sm leading-snug text-dim">{subject}</div>}
          {date ? <div className="mt-0.5 text-xs text-faint">{dateTime(date)}</div> : null}
        </>
      ) : (
        <div className="mt-1 text-sm text-faint">Unknown</div>
      )}
    </div>
  )
}

