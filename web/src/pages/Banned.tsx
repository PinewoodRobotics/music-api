import { Ban, Clock, Infinity as Forever, LogOut } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Markdown } from '../components/Markdown'
import { Button } from '../components/Modal'
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
    <div className="relative grid min-h-dvh place-items-center overflow-hidden bg-black px-6 py-16">
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(ellipse_80%_55%_at_50%_-10%,rgb(255_107_107/.16),transparent_70%)]" />
      <main className="animate-rise relative flex w-full max-w-md flex-col items-center text-center">
        <span className="grid size-16 place-items-center rounded-[28%] bg-danger/15 text-danger">
          <Ban className="size-8" strokeWidth={2.25} />
        </span>
        <h1 className="mt-8 font-display text-4xl font-extrabold tracking-[-0.04em]">You've been banned</h1>
        <p className="mt-3 text-[15px] leading-relaxed text-dim">An admin has blocked you from Robotics Music. You can't pick songs, use your API token or control the speakers from Slack.</p>

        <section className="mt-8 w-full rounded-xl bg-white/[0.05] p-5 text-left ring-1 ring-white/[0.06]">
          <h2 className="text-xs font-medium uppercase tracking-wider text-faint">Reason</h2>
          <Markdown className="mt-2 text-[15px]">{ban.reason || 'No reason given.'}</Markdown>
          <div className="mt-5 flex items-start gap-2.5 border-t border-white/[0.07] pt-4 text-sm">
            {ban.until == null ? (
              <>
                <Forever className="mt-0.5 size-4 shrink-0 text-danger" />
                <span className="text-fg">This ban is permanent</span>
              </>
            ) : (
              <>
                <Clock className="mt-0.5 size-4 shrink-0 text-dim" />
                <span>
                  <span className="text-fg">Ends {formatMoment(ban.until)}</span>
                  <span className="text-dim">, {fromNow(ban.until)}</span>
                </span>
              </>
            )}
          </div>
        </section>

        <p className="mt-6 text-xs text-faint">If you think this is a mistake, talk to one of the lab admins.</p>
        <Button
          variant="ghost"
          className="mt-4 bg-white/[0.06]"
          disabled={leaving}
          onClick={() => {
            setLeaving(true)
            void signOut().finally(() => setLeaving(false))
          }}
        >
          <LogOut className="size-4" />
          Sign out
        </Button>
      </main>
    </div>
  )
}
