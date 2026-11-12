import { useEffect, useState } from 'react'
import { Markdown } from '../components/Markdown'
import type { BanInfo } from '../lib/api'
import { formatMoment, fromNow } from '../lib/format'
import { useSession } from '../state/session'

export function Banned({ ban }: { ban: BanInfo }) {
  const { signOut, retry } = useSession()
  const [leaving, setLeaving] = useState(false)
  const [, tick] = useState(0)

  useEffect(() => {
    if (ban.until == null) return
    const ms = ban.until * 1000 - Date.now()
    const ended = ms <= 0 ? setTimeout(retry, 0) : ms < 2 ** 31 - 1 ? setTimeout(retry, ms + 1000) : undefined
    const minute = setInterval(() => tick((n) => n + 1), 60_000)
    return () => {
      clearTimeout(ended)
      clearInterval(minute)
    }
  }, [ban.until, retry])

  return (
    <div className="grid min-h-dvh place-items-center bg-black px-6 py-16">
      <main className="animate-rise w-full max-w-md">
        <p className="text-sm font-medium text-danger">{ban.until == null ? 'Banned permanently' : `Banned until ${formatMoment(ban.until)} (${fromNow(ban.until)})`}</p>
        <h1 className="mt-2 font-display text-4xl font-extrabold tracking-[-0.04em]">You've been banned</h1>
        {ban.reason && <Markdown className="mt-6 text-[17px] text-fg">{ban.reason}</Markdown>}
        <button
          type="button"
          disabled={leaving}
          onClick={() => {
            setLeaving(true)
            void signOut().finally(() => setLeaving(false))
          }}
          className="mt-10 text-sm text-faint underline-offset-4 transition-colors hover:text-dim hover:underline disabled:opacity-50"
        >
          Sign out
        </button>
      </main>
    </div>
  )
}
