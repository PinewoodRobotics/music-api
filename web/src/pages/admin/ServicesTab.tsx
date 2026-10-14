import { RefreshCw, RotateCw, ScrollText, SquareTerminal } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { Button, Modal } from '../../components/Modal'
import { api, type ServiceInfo, type ServiceLogs, type ServiceState } from '../../lib/api'
import { useSession } from '../../state/session'
import { useToast } from '../../state/toast'
import { useUI } from '../../state/ui'
import { ErrorState, PageSpinner } from '../Message'
import { ago, Card, Dot, usePoll, type Tone } from './kit'

const stateTone: Record<ServiceState, Tone> = { active: 'good', activating: 'warn', deactivating: 'warn', inactive: 'neutral', failed: 'bad', unknown: 'neutral' }

export function ServiceDot({ state }: { state: ServiceState }) {
  return <Dot tone={stateTone[state]} pulse={state === 'activating' || state === 'deactivating'} />
}

const WARNINGS: Record<string, string> = {
  soloist: 'The music will stop for a few seconds while it comes back.',
  airplay: 'Anyone streaming over AirPlay will be disconnected.',
  'music-api': 'This page and the API are unavailable for a few seconds. The music keeps playing.',
  'music-display': 'The display goes blank for a few seconds.',
  cloudflared: 'The public tunnel drops for a few seconds, so this page may disconnect.',
}

function LogsModal({ service, onClose }: { service: ServiceInfo; onClose: () => void }) {
  const [logs, setLogs] = useState<ServiceLogs | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [loading, setLoading] = useState(true)
  const box = useRef<HTMLPreElement>(null)

  const load = () => {
    setLoading(true)
    api
      .serviceLogs(service.name, 200)
      .then((l) => {
        setLogs(l)
        setError(null)
      })
      .catch(setError)
      .finally(() => setLoading(false))
  }
  useEffect(load, [service.name])
  useEffect(() => {
    box.current?.scrollTo(0, box.current.scrollHeight)
  }, [logs])

  return (
    <Modal title={`${service.name} logs`} onClose={onClose} wide="xl">
      <div className="mb-3 flex items-center justify-between gap-3">
        <span className="truncate font-mono text-xs text-dim">{service.unit}</span>
        <Button variant="ghost" className="h-8 bg-white/10 px-3" onClick={load} disabled={loading}>
          <RefreshCw className={`size-3.5 ${loading ? 'animate-spin' : ''}`} />
          Refresh
        </Button>
      </div>
      {error != null ? (
        <p className="text-sm text-danger">{error instanceof Error ? error.message : 'Could not load logs.'}</p>
      ) : logs?.error ? (
        <p className="text-sm text-danger">{logs.error}</p>
      ) : (
        <pre ref={box} className="scroll-thin h-[55dvh] overflow-auto rounded-md bg-black/50 p-3 font-mono text-[11px] leading-relaxed text-dim">
          {logs ? (logs.lines.length ? logs.lines.join('\n') : 'No log lines.') : 'Loading...'}
        </pre>
      )}
    </Modal>
  )
}

function ServiceRow({ service, onRestart, onLogs }: { service: ServiceInfo; onRestart: () => void; onLogs: () => void }) {
  return (
    <li className="flex flex-wrap items-center gap-x-3 gap-y-2 py-3">
      <ServiceDot state={service.state} />
      <div className="min-w-0 flex-1 basis-40">
        <div className="flex items-baseline gap-2">
          <span className="truncate text-sm font-semibold">{service.name}</span>
          <span className="shrink-0 text-xs text-dim">{service.sub ?? service.state}</span>
        </div>
        <div className="truncate text-xs text-faint">
          {service.scope} unit {service.unit}
          {service.since ? `, since ${ago(service.since)}` : ''}
          {service.enabled ? `, ${service.enabled}` : ''}
        </div>
      </div>
      <div className="flex gap-2">
        <button
          type="button"
          onClick={onLogs}
          className="inline-flex h-8 items-center gap-1.5 rounded-full bg-white/10 px-3 text-xs font-semibold transition hover:bg-white/15 active:scale-95"
        >
          <ScrollText className="size-3.5" />
          Logs
        </button>
        {service.restartable && (
          <button
            type="button"
            onClick={onRestart}
            className="inline-flex h-8 items-center gap-1.5 rounded-full bg-white/10 px-3 text-xs font-semibold transition hover:bg-white/15 active:scale-95"
          >
            <RotateCw className="size-3.5" />
            Restart
          </button>
        )}
      </div>
    </li>
  )
}

export function ServicesTab({ active }: { active: boolean }) {
  const { data, error, reload } = usePoll(api.adminSystem, 5000, active)
  const { me } = useSession()
  const { openDialog } = useUI()
  const toast = useToast()
  const [confirm, setConfirm] = useState<ServiceInfo | null>(null)
  const [logsFor, setLogsFor] = useState<ServiceInfo | null>(null)
  const [busy, setBusy] = useState(false)

  if (!data) return error ? <ErrorState title="Couldn't load services" error={error} onRetry={() => void reload()} /> : <PageSpinner />

  const restart = async (service: ServiceInfo) => {
    setBusy(true)
    try {
      const res = await api.restartService(service.name)
      toast.show(`${service.name} restarted (${res.state})`)
      setConfirm(null)
      void reload()
    } catch (err) {
      toast.error(err)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-4">
      <Card title="Services">
        <ul className="divide-y divide-white/[0.07]">
          {data.services.map((s) => (
            <ServiceRow key={s.name} service={s} onRestart={() => setConfirm(s)} onLogs={() => setLogsFor(s)} />
          ))}
        </ul>
      </Card>
      {me?.kind === 'slack' && (
        <Card title="API access">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="text-sm text-dim">Your personal API token for scripts and the HTTP API.</p>
            <button
              type="button"
              onClick={() => openDialog({ kind: 'api' })}
              className="inline-flex h-8 items-center gap-1.5 rounded-full bg-white/10 px-3 text-xs font-semibold transition hover:bg-white/15 active:scale-95"
            >
              <SquareTerminal className="size-3.5" />
              API token
            </button>
          </div>
        </Card>
      )}
      {confirm && (
        <Modal title={`Restart ${confirm.name}?`} onClose={() => !busy && setConfirm(null)} dismissable={!busy}>
          <p className="text-sm leading-relaxed text-dim">{WARNINGS[confirm.name] ?? 'The service will be unavailable for a few seconds.'}</p>
          <div className="mt-6 flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setConfirm(null)} disabled={busy}>
              Cancel
            </Button>
            <Button onClick={() => void restart(confirm)} disabled={busy}>
              <RotateCw className={`size-4 ${busy ? 'animate-spin' : ''}`} />
              Restart
            </Button>
          </div>
        </Modal>
      )}
      {logsFor && <LogsModal service={logsFor} onClose={() => setLogsFor(null)} />}
    </div>
  )
}
