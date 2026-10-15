import { useState } from 'react'
import { Slider } from '../../components/Slider'
import { api, type EffectsVolumeChange } from '../../lib/api'
import { useToast } from '../../state/toast'
import { ErrorState, PageSpinner } from '../Message'
import { ago, Card, Toggle, usePoll } from './kit'

export function SoundEffectsTab({ active }: { active: boolean }) {
  const { data, setData, error, reload } = usePoll(api.adminEffectsVolume, 15000, active)
  const toast = useToast()
  const [busy, setBusy] = useState(false)
  const [preview, setPreview] = useState<number | null>(null)

  if (!data) return error ? <ErrorState title="Couldn't load the sound effects volume" error={error} onRetry={() => void reload()} /> : <PageSpinner />

  const save = async (body: EffectsVolumeChange, done: string) => {
    setBusy(true)
    if (body.level !== undefined) setData({ ...data, level: body.level })
    try {
      setData(await api.saveEffectsVolume(body))
      toast.show(done)
    } catch (err) {
      toast.error(err)
    } finally {
      setBusy(false)
    }
  }

  const sameAsMedia = data.mode === 'follow'
  const level = Math.round(preview ?? data.level)
  const used = sameAsMedia ? data.media_volume : level

  return (
    <div className="space-y-4">
      <Card title="Volume">
        <div className="space-y-4">
          <div className="flex items-center justify-between gap-4">
            <div>
              <div className="text-sm font-semibold">Same as media</div>
              <div className="text-xs text-dim">
                {sameAsMedia ? `Sound effects follow the music volume slider (now ${data.media_volume}%).` : `Sound effects use their own volume. The music is at ${data.media_volume}%.`}
              </div>
            </div>
            <Toggle
              on={sameAsMedia}
              onChange={(on) => !busy && void save({ mode: on ? 'follow' : 'fixed' }, on ? 'Sound effects follow the music volume' : 'Sound effects use their own volume')}
              label="Same as media"
            />
          </div>
          {!sameAsMedia && (
            <div>
              <div className="mb-1.5 flex items-center justify-between text-xs font-medium text-dim">
                <span>Sound effects volume</span>
                <span className="tabular text-fg">{level}%</span>
              </div>
              <Slider
                label="Sound effects volume"
                value={data.level}
                max={100}
                step={5}
                thick
                valueText={`${level}%`}
                onPreview={setPreview}
                onCommit={(v) => void save({ level: Math.round(v) }, `Sound effects volume ${Math.round(v)}%`)}
              />
            </div>
          )}
          <p className="text-sm text-dim">
            An effect at 100 plays at {used}% of full volume; quieter effects scale down from there. Changes apply to the next effect played.
          </p>
          <div className="flex items-center justify-between gap-4 border-t border-white/[0.07] pt-4">
            <div>
              <div className="text-sm font-semibold">Play during quiet hours</div>
              <div className="text-xs text-dim">
                {data.play_during_quiet_hours ? 'Sound effects still play while quiet hours lock the speakers. Music stays off.' : 'Sound effects are blocked while quiet hours lock the speakers, like music.'}
              </div>
            </div>
            <Toggle
              on={data.play_during_quiet_hours}
              onChange={(on) => !busy && void save({ play_during_quiet_hours: on }, on ? 'Sound effects play during quiet hours' : 'Sound effects are blocked during quiet hours')}
              label="Play during quiet hours"
            />
          </div>
          {data.updated_at && (
            <p className="text-xs text-dim">
              Changed{data.updated_by ? ` by ${data.updated_by.name}` : ''} {ago(data.updated_at)}.
            </p>
          )}
        </div>
      </Card>
    </div>
  )
}
