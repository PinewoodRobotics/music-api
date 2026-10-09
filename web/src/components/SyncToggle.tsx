import { MonitorSpeaker } from 'lucide-react'
import { mediaSessionSupported, nowPlayingSync, useSyncState } from '../lib/nowPlayingSync'

const HINT = 'Control the lab speakers from your lock screen and media keys.'

export function SyncToggle() {
  const { state, error } = useSyncState()
  if (!mediaSessionSupported) return null
  const on = state !== 'off'
  const action =
    state === 'interrupted' ? 'Paused by the system. Tap to resume.' : state === 'starting' ? 'Tap to start on this device.' : null
  return (
    <div className="flex items-start gap-3 border-b border-white/[0.07] px-4 py-3">
      <MonitorSpeaker className="mt-0.5 size-4 shrink-0 text-dim" />
      <div className="min-w-0 flex-1">
        <div className="text-sm">Sync to Now Playing</div>
        {action ? (
          <button type="button" onClick={nowPlayingSync.enable} className="mt-0.5 text-left text-xs text-[#34c759] hover:underline">
            {error ? `${action} (${error})` : action}
          </button>
        ) : (
          <p className={`mt-0.5 text-xs leading-snug ${error ? 'text-danger' : 'text-dim'}`}>{error ?? HINT}</p>
        )}
      </div>
      <button
        type="button"
        role="switch"
        aria-checked={on}
        aria-label="Sync to Now Playing"
        onClick={on ? nowPlayingSync.disable : nowPlayingSync.enable}
        className={`relative mt-0.5 h-6 w-10 shrink-0 rounded-full transition-colors duration-200 ${on ? 'bg-[#34c759]' : 'bg-white/20'}`}
      >
        <span
          className={`absolute left-0 top-0.5 size-5 rounded-full bg-white shadow-md transition-transform duration-200 ${on ? 'translate-x-[18px]' : 'translate-x-0.5'}`}
        />
      </button>
    </div>
  )
}
