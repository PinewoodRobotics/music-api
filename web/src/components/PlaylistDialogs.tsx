import { Loader2 } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { api, type AppPlaylist } from '../lib/api'
import { decodeEntities } from '../lib/format'
import { navigate } from '../lib/router'
import { useSession } from '../state/session'
import { useToast } from '../state/toast'
import { useUI } from '../state/ui'
import { ActivityPanel } from './activity/ActivityPanel'
import { ApiTokenDialog } from './ApiTokenDialog'
import { ImportDialog } from './ImportDialog'
import { Button, Field, fieldClass, Modal } from './Modal'

export function Dialogs() {
  const { dialog, closeDialog } = useUI()
  if (!dialog) return null
  switch (dialog.kind) {
    case 'new':
      return <PlaylistForm onClose={closeDialog} />
    case 'edit':
      return <PlaylistForm onClose={closeDialog} playlist={dialog.playlist} />
    case 'import':
      return <ImportDialog onClose={closeDialog} initialUrl={dialog.url} asPlaylist={dialog.asPlaylist} />
    case 'activity':
      return <ActivityPanel onClose={closeDialog} />
    case 'api':
      return <ApiTokenDialog onClose={closeDialog} />
    case 'delete':
      return <DeleteDialog onClose={closeDialog} playlist={dialog.playlist} />
  }
}

function PlaylistForm({ onClose, playlist }: { onClose: () => void; playlist?: AppPlaylist }) {
  const [name, setName] = useState(() => decodeEntities(playlist?.name ?? ''))
  const [description, setDescription] = useState(() => decodeEntities(playlist?.description ?? ''))
  const [busy, setBusy] = useState(false)
  const { upsertPlaylist } = useSession()
  const toast = useToast()

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    if (!name.trim()) return
    setBusy(true)
    try {
      const body = { name: name.trim(), description: description.trim() }
      const saved = playlist ? await api.updatePlaylist(playlist.id, body) : await api.createPlaylist(body)
      upsertPlaylist(saved)
      onClose()
      if (playlist) toast.show('Playlist saved')
      else {
        toast.show(`Created ${saved.name}`)
        navigate(`/playlist/${saved.id}`)
      }
    } catch (err) {
      toast.error(err)
      setBusy(false)
    }
  }

  return (
    <Modal title={playlist ? 'Edit details' : 'New playlist'} onClose={onClose}>
      <form onSubmit={submit} className="space-y-4">
        <Field label="Name">
          <input autoFocus required maxLength={100} value={name} onChange={(e) => setName(e.target.value)} placeholder="Build night" className={fieldClass} />
        </Field>
        <Field label="Description">
          <textarea
            rows={3}
            maxLength={300}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="Optional"
            className={`${fieldClass} resize-none`}
          />
        </Field>
        <div className="flex justify-end gap-2 pt-2">
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" disabled={busy || !name.trim()}>
            {busy && <Loader2 className="size-4 animate-spin" />}
            {playlist ? 'Save' : 'Create'}
          </Button>
        </div>
      </form>
    </Modal>
  )
}

function DeleteDialog({ onClose, playlist }: { onClose: () => void; playlist: AppPlaylist }) {
  const [busy, setBusy] = useState(false)
  const { dropPlaylist } = useSession()
  const toast = useToast()

  const confirm = async () => {
    setBusy(true)
    try {
      await api.deletePlaylist(playlist.id)
      dropPlaylist(playlist.id)
      onClose()
      toast.show(`Deleted ${playlist.name}`)
      if (location.pathname === `/playlist/${playlist.id}`) navigate('/', { replace: true })
    } catch (err) {
      toast.error(err)
      setBusy(false)
    }
  }

  return (
    <Modal title="Delete playlist?" onClose={onClose} dismissable={!busy}>
      <p className="text-sm leading-relaxed text-dim">
        This deletes <span className="font-semibold text-fg">{playlist.name}</span> for everyone in the lab.
      </p>
      <div className="mt-6 flex justify-end gap-2">
        <Button variant="ghost" onClick={onClose} disabled={busy}>
          Cancel
        </Button>
        <Button variant="danger" onClick={confirm} disabled={busy}>
          {busy && <Loader2 className="size-4 animate-spin" />}
          Delete
        </Button>
      </div>
    </Modal>
  )
}
