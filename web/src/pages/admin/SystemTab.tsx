import { AlertTriangle, CheckCircle2, CircleHelp, Zap } from 'lucide-react'
import { api, type PowerFlags, type SystemInfo } from '../../lib/api'
import { PageSpinner, ErrorState } from '../Message'
import { ServiceDot } from './ServicesTab'
import { ago, Banner, Bar, bytes, Card, Chip, duration, Sparkline, Stat, usePoll, type Tone } from './kit'

const FLAGS: { key: keyof PowerFlags; label: string }[] = [
  { key: 'under_voltage', label: 'Under-voltage' },
  { key: 'freq_capped', label: 'Frequency capped' },
  { key: 'throttled', label: 'Throttled' },
  { key: 'soft_temp_limit', label: 'Soft temp limit' },
]

function PowerCard({ power }: { power: SystemInfo['power'] }) {
  const { now, since_boot: past } = power
  const events = power.events ?? 0
  const nowBad = now.under_voltage === true
  const nowWarn = now.freq_capped === true || now.throttled === true || now.soft_temp_limit === true
  const pastAny = FLAGS.some((f) => past[f.key] === true) || events > 0
  const unknown = !power.source || FLAGS.every((f) => now[f.key] == null && past[f.key] == null)

  let tone: Tone = 'good'
  let title = 'No under-voltage'
  let body = 'The power supply has kept up since boot. No throttling or frequency capping seen.'
  let icon = <CheckCircle2 />
  if (nowBad) {
    tone = 'bad'
    title = 'Under-voltage right now'
    body = 'The Pi is not getting enough power and is likely slowing itself down. Try a better supply (5V, 2.5A or more) and a shorter, thicker cable.'
    icon = <Zap />
  } else if (nowWarn) {
    tone = 'warn'
    title = now.throttled ? 'Throttled right now' : now.freq_capped ? 'Frequency capped right now' : 'Soft temperature limit active'
    body = 'The CPU is running slower than normal to stay within power or heat limits.'
    icon = <AlertTriangle />
  } else if (pastAny) {
    tone = 'warn'
    title = 'Under-voltage has happened since boot'
    body = `Fine right now, but the power supply dipped${events ? ` ${events} time${events === 1 ? '' : 's'}` : ''}${power.last_event_at ? `, most recently ${ago(power.last_event_at)}` : ''}. Worth checking the supply and cable.`
    icon = <AlertTriangle />
  } else if (unknown) {
    tone = 'neutral'
    title = 'Power status unavailable'
    body = 'This board does not report throttling flags.'
    icon = <CircleHelp />
  }

  return (
    <Banner tone={tone} icon={icon} title={title}>
      <p>{body}</p>
      {!unknown && (
        <div className="mt-3 flex flex-wrap gap-1.5">
          {FLAGS.map(({ key, label }) => {
            const state = now[key] ? 'now' : past[key] ? 'since boot' : null
            return (
              <Chip key={key} tone={now[key] ? 'bad' : past[key] ? 'warn' : 'neutral'}>
                {label}: {state ?? (now[key] == null && past[key] == null ? 'n/a' : 'ok')}
              </Chip>
            )
          })}
          {events > 0 && <Chip tone="warn">{events} kernel warning{events === 1 ? '' : 's'}</Chip>}
        </div>
      )}
    </Banner>
  )
}

const tempTone = (t: number | null): Tone => (t == null ? 'neutral' : t >= 80 ? 'bad' : t >= 70 ? 'warn' : 'good')
const loadTone = (v: number, cores: number): Tone => (v >= cores * 1.5 ? 'bad' : v >= cores ? 'warn' : 'good')
const pctTone = (p: number): Tone => (p >= 90 ? 'bad' : p >= 75 ? 'warn' : 'good')

function signalTone(dbm: number | null): Tone {
  if (dbm == null) return 'neutral'
  return dbm >= -67 ? 'good' : dbm >= -75 ? 'warn' : 'bad'
}

export function SystemTab({ active }: { active: boolean }) {
  const { data, error, reload } = usePoll(api.adminSystem, 2000, active)
  if (!data) return error ? <ErrorState title="Couldn't load system info" error={error} onRetry={() => void reload()} /> : <PageSpinner />
  const { cpu, memory, disk, network: net, history } = data
  const temp = data.temp_c
  const ttone = tempTone(temp)
  const cpuValues = history.map((h) => h.cpu)
  const tempValues = history.map((h) => h.temp)
  const temps = tempValues.filter((v): v is number => v != null)
  const tmin = Math.floor(Math.min(40, ...temps) / 5) * 5
  const tmax = Math.ceil(Math.max(85, ...temps) / 5) * 5

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span className="font-display text-lg font-bold tracking-tight">{data.hostname}</span>
        <span className="text-sm text-dim">{data.model ?? 'Unknown board'}</span>
        <span className="tabular text-sm text-faint">up {duration(data.uptime_s)}</span>
      </div>

      <PowerCard power={data.power} />

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="CPU" aside={<span className="tabular text-xs text-dim">{cpu.freq_mhz ? `${Math.round(cpu.freq_mhz)}${cpu.max_mhz ? ` / ${Math.round(cpu.max_mhz)}` : ''} MHz` : ''}</span>}>
          <div className="flex items-end gap-4">
            <div className="tabular shrink-0 font-display text-4xl font-bold leading-none tracking-tight">
              {Math.round(cpu.percent)}
              <span className="text-xl text-dim">%</span>
            </div>
            <Sparkline values={cpuValues} min={0} max={100} tone={pctTone(cpu.percent)} />
          </div>
          <div className="mt-4 grid grid-cols-4 gap-3">
            {cpu.cores.map((c, i) => (
              <div key={i}>
                <div className="tabular mb-1 flex justify-between text-xs text-dim">
                  <span>Core {i}</span>
                  <span>{Math.round(c)}%</span>
                </div>
                <Bar percent={c} tone={pctTone(c)} label={`Core ${i}`} />
              </div>
            ))}
          </div>
          <div className="mt-4 grid grid-cols-3 gap-3 border-t border-white/[0.07] pt-4">
            {(['1 min', '5 min', '15 min'] as const).map((label, i) => (
              <Stat key={label} label={`Load ${label}`} value={<span className={data.load[i] >= cpu.count ? 'text-[#ffb340]' : ''}>{data.load[i].toFixed(2)}</span>} hint={loadTone(data.load[i], cpu.count) === 'good' ? undefined : `${cpu.count} cores`} />
            ))}
          </div>
        </Card>

        <Card title="Temperature">
          <div className="flex items-end gap-4">
            <div className={`tabular shrink-0 whitespace-nowrap font-display text-4xl font-bold leading-none tracking-tight ${ttone === 'good' || ttone === 'neutral' ? '' : ttone === 'warn' ? 'text-[#ffb340]' : 'text-danger'}`}>
              {temp == null ? 'n/a' : temp.toFixed(1)}
              {temp != null && <span className="ml-1 text-xl text-dim">°C</span>}
            </div>
            <Sparkline values={tempValues} min={tmin} max={tmax} tone={ttone} />
          </div>
          <p className="mt-4 text-sm text-dim">
            {ttone === 'bad' ? 'Running hot. The Pi will throttle itself above 80 °C.' : ttone === 'warn' ? 'Getting warm. Check airflow if this stays up.' : 'Comfortable. Warns above 70 °C.'}
          </p>
        </Card>

        <Card title="Memory and storage">
          <div className="space-y-4">
            <div>
              <div className="tabular mb-1.5 flex justify-between text-sm">
                <span className="text-dim">Memory</span>
                <span>
                  {bytes(memory.used)} of {bytes(memory.total)}
                </span>
              </div>
              <Bar percent={memory.percent} tone={pctTone(memory.percent)} label="Memory" />
              {memory.swap_total > 0 && <div className="tabular mt-1.5 text-xs text-faint">Swap {bytes(memory.swap_used)} of {bytes(memory.swap_total)}</div>}
            </div>
            <div>
              <div className="tabular mb-1.5 flex justify-between text-sm">
                <span className="text-dim">Disk {disk.path}</span>
                <span>
                  {bytes(disk.used)} of {bytes(disk.total)}
                </span>
              </div>
              <Bar percent={disk.percent} tone={pctTone(disk.percent)} label="Disk" />
              <div className="tabular mt-1.5 text-xs text-faint">{bytes(disk.free)} free</div>
            </div>
          </div>
        </Card>

        <Card title="Network" aside={net.interface && <span className="text-xs text-dim">{net.interface}</span>}>
          {net.ssid || net.ip ? (
            <>
              <div className="flex items-baseline justify-between gap-3">
                <span className="truncate text-lg font-semibold">{net.ssid ?? 'Wired'}</span>
                {net.signal_dbm != null && <span className="tabular shrink-0 text-sm text-dim">{net.signal_dbm} dBm</span>}
              </div>
              {net.quality != null && (
                <div className="mt-2">
                  <Bar percent={net.quality} tone={signalTone(net.signal_dbm)} label="Signal quality" />
                  <div className="tabular mt-1 text-xs text-faint">Signal quality {Math.round(net.quality)}%</div>
                </div>
              )}
              <div className="mt-4 grid grid-cols-2 gap-3">
                <Stat label="IP address" value={net.ip ?? 'n/a'} />
                <Stat label="Bitrate" value={net.bitrate_mbps != null ? `${Math.round(net.bitrate_mbps)} Mbit/s` : 'n/a'} hint={net.freq_mhz ? `${(net.freq_mhz / 1000).toFixed(1)} GHz` : undefined} />
                {net.bssid && <Stat label="Access point" value={<span className="font-mono text-xs">{net.bssid}</span>} />}
              </div>
            </>
          ) : (
            <p className="text-sm text-dim">No network details available.</p>
          )}
        </Card>

        <Card title="Services">
          <ul className="space-y-2.5">
            {data.services.map((s) => (
              <li key={s.name} className="flex items-center gap-2.5 text-sm">
                <ServiceDot state={s.state} />
                <span className="min-w-0 flex-1 truncate">{s.name}</span>
                <span className="text-xs text-faint">{s.state}</span>
              </li>
            ))}
          </ul>
        </Card>

        <Card title="Versions">
          <dl className="grid grid-cols-[auto_1fr] gap-x-5 gap-y-2 text-sm">
            {(
              [
                ['App', data.versions.commit_short ? `${data.versions.commit_short}${data.versions.subject ? ` - ${data.versions.subject}` : ''}` : null],
                ['Built', data.versions.built_at ? ago(data.versions.built_at) : null],
                ['Soloist', data.versions.soloist],
                ['shairport-sync', data.versions.shairport_sync],
                ['Python', data.versions.python],
                ['Kernel', data.versions.kernel],
                ['OS', data.versions.os],
              ] as const
            )
              .filter(([, v]) => v)
              .map(([k, v]) => (
                <div key={k} className="contents">
                  <dt className="text-dim">{k}</dt>
                  <dd className="min-w-0 break-words text-fg">{v}</dd>
                </div>
              ))}
          </dl>
        </Card>
      </div>
    </div>
  )
}
