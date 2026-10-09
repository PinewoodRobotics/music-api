import { Check, Copy, Eye, EyeOff, Loader2, RefreshCw } from 'lucide-react'
import { useEffect, useState } from 'react'
import { api, errorMessage, type PersonalToken } from '../lib/api'
import { useToast } from '../state/toast'
import { Button, Modal } from './Modal'

function useCopy() {
  const [copied, setCopied] = useState<string | null>(null)
  const toast = useToast()
  const copy = async (key: string, text: string) => {
    try {
      await navigator.clipboard.writeText(text)
      setCopied(key)
      setTimeout(() => setCopied((k) => (k === key ? null : k)), 1500)
    } catch {
      toast.show("Couldn't copy. Select the text and copy it manually.")
    }
  }
  return { copied, copy }
}

function CopyButton({ id, text, copied, onCopy, label = 'Copy' }: { id: string; text: string; copied: string | null; onCopy: (id: string, text: string) => void; label?: string }) {
  const done = copied === id
  return (
    <button
      type="button"
      onClick={() => onCopy(id, text)}
      className="inline-flex h-8 shrink-0 items-center gap-1.5 rounded-full bg-white/10 px-3 text-xs font-semibold transition-colors hover:bg-white/20"
    >
      {done ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
      {done ? 'Copied' : label}
    </button>
  )
}

function Snippet({ title, shown, full, id, copied, onCopy }: { title: string; shown: string; full: string; id: string; copied: string | null; onCopy: (id: string, text: string) => void }) {
  return (
    <div className="rounded-lg bg-black/30 p-3">
      <div className="mb-2 flex items-center justify-between gap-3">
        <span className="text-xs font-medium text-dim">{title}</span>
        <CopyButton id={id} text={full} copied={copied} onCopy={onCopy} />
      </div>
      <p className="break-all font-mono text-[12px] leading-relaxed text-fg/90">{shown}</p>
    </div>
  )
}

export function ApiTokenDialog({ onClose }: { onClose: () => void }) {
  const [token, setToken] = useState<PersonalToken | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [visible, setVisible] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const [regenerating, setRegenerating] = useState(false)
  const { copied, copy } = useCopy()
  const toast = useToast()

  useEffect(() => {
    let live = true
    api
      .personalToken()
      .then((t) => live && setToken(t))
      .catch((err) => live && setError(errorMessage(err)))
    return () => {
      live = false
    }
  }, [])

  const regenerate = async () => {
    setRegenerating(true)
    try {
      setToken(await api.regenerateToken())
      setConfirming(false)
      setVisible(true)
      toast.show('New token created. The old one no longer works.')
    } catch (err) {
      toast.error(err)
    } finally {
      setRegenerating(false)
    }
  }

  const body = () => {
    if (error) return <p className="text-sm text-danger">{error}</p>
    if (!token)
      return (
        <div className="grid place-items-center py-10">
          <Loader2 className="size-6 animate-spin text-faint" />
        </div>
      )
    const origin = new URL(token.docs, location.origin).origin
    const masked = `${token.token.slice(0, 5)}${'•'.repeat(Math.max(8, token.token.length - 5))}`
    const display = visible ? token.token : masked
    const prompt = (t: string) =>
      `Control the Pinewood Robotics lab speakers with the Robotics Music API. Read ${token.docs} first. My token: ${t}`
    const curl = (t: string) => `curl -H "Authorization: Bearer ${t}" ${origin}/api/status`

    return (
      <div className="space-y-4">
        <p className="text-sm leading-relaxed text-dim">
          Acts as you: same permissions, and anything you queue or create is credited to you.
        </p>
        <div className="flex items-center gap-2 rounded-lg bg-white/[0.07] p-2 pl-3">
          <code className="min-w-0 flex-1 truncate font-mono text-[13px]">{display}</code>
          <button
            type="button"
            onClick={() => setVisible((v) => !v)}
            className="inline-flex h-8 shrink-0 items-center gap-1.5 rounded-full px-3 text-xs font-semibold text-dim hover:bg-white/10 hover:text-fg"
          >
            {visible ? <EyeOff className="size-3.5" /> : <Eye className="size-3.5" />}
            {visible ? 'Hide' : 'Show'}
          </button>
          <CopyButton id="token" text={token.token} copied={copied} onCopy={copy} />
        </div>
        <Snippet title="Use it with an AI agent" id="prompt" shown={prompt(display)} full={prompt(token.token)} copied={copied} onCopy={copy} />
        <Snippet title="Try it with curl" id="curl" shown={curl(display)} full={curl(token.token)} copied={copied} onCopy={copy} />
        <p className="text-xs text-faint">
          Full reference:{' '}
          <a href={token.docs} target="_blank" rel="noreferrer" className="text-dim underline hover:text-fg">
            {token.docs.replace(/^https?:\/\//, '')}
          </a>
        </p>
        <div className="border-t border-white/[0.07] pt-4">
          {confirming ? (
            <div className="flex flex-wrap items-center justify-between gap-3">
              <p className="text-sm text-dim">Your current token stops working immediately.</p>
              <div className="flex gap-2">
                <Button variant="ghost" onClick={() => setConfirming(false)} disabled={regenerating}>
                  Cancel
                </Button>
                <Button variant="danger" onClick={regenerate} disabled={regenerating}>
                  {regenerating && <Loader2 className="size-4 animate-spin" />}
                  Regenerate
                </Button>
              </div>
            </div>
          ) : (
            <button type="button" onClick={() => setConfirming(true)} className="inline-flex items-center gap-2 text-xs font-medium text-dim hover:text-fg">
              <RefreshCw className="size-3.5" />
              Regenerate token
            </button>
          )}
        </div>
      </div>
    )
  }

  return (
    <Modal title="Your API token" onClose={onClose} wide>
      {body()}
    </Modal>
  )
}
