import { Activity, Moon, Server, ShieldCheck, Users, CloudDownload } from 'lucide-react'
import type { ComponentType } from 'react'
import { Link } from '../../components/Link'
import { navigate } from '../../lib/router'
import { useSession } from '../../state/session'
import { Message } from '../Message'
import { AdminsTab } from './AdminsTab'
import { QuietHoursTab } from './QuietHoursTab'
import { ServicesTab } from './ServicesTab'
import { SystemTab } from './SystemTab'
import { UpdatesTab } from './UpdatesTab'

const TABS = [
  { id: 'system', label: 'System', icon: Activity },
  { id: 'quiet-hours', label: 'Quiet hours', icon: Moon },
  { id: 'admins', label: 'Admins', icon: Users },
  { id: 'updates', label: 'Updates', icon: CloudDownload },
  { id: 'services', label: 'Services', icon: Server },
] as const satisfies readonly { id: string; label: string; icon: ComponentType<{ className?: string }> }[]

type TabId = (typeof TABS)[number]['id']

export function AdminPage({ tab }: { tab: string | null }) {
  const { me } = useSession()
  if (!me?.admin)
    return (
      <Message
        icon={<ShieldCheck className="size-10" />}
        title="Admins only"
        body="This page is for the people who look after the lab speakers."
        action={
          <button type="button" onClick={() => navigate('/')} className="inline-flex h-10 items-center rounded-full bg-fg px-5 text-sm font-semibold text-canvas transition hover:scale-[1.03]">
            Go home
          </button>
        }
      />
    )
  const current: TabId = TABS.find((t) => t.id === tab)?.id ?? 'system'

  return (
    <div className="px-3 pb-12 pt-2 max-sm:px-2">
      <h1 className="mb-4 px-3 font-display text-[clamp(1.9rem,4vw,3rem)] font-extrabold tracking-tight max-sm:px-2">Admin</h1>
      <div className="flex gap-6 px-3 max-md:flex-col max-md:gap-4 max-sm:px-2">
        <nav aria-label="Admin sections" className="no-scrollbar -mx-2 flex shrink-0 gap-1.5 overflow-x-auto px-2 md:sticky md:top-20 md:mx-0 md:w-48 md:flex-col md:self-start md:overflow-visible md:px-0">
          {TABS.map(({ id, label, icon: Icon }) => {
            const on = id === current
            return (
              <Link
                key={id}
                href={`/admin/${id}`}
                aria-current={on ? 'page' : undefined}
                className={`flex shrink-0 items-center gap-2.5 rounded-full px-4 py-2 text-sm font-semibold transition-colors md:rounded-md md:px-3 ${
                  on ? 'bg-white/[0.12] text-fg' : 'text-dim hover:bg-white/[0.06] hover:text-fg'
                }`}
              >
                <Icon className="size-4" />
                {label}
              </Link>
            )
          })}
        </nav>
        <div className="min-w-0 flex-1">
          {current === 'system' && <SystemTab active />}
          {current === 'quiet-hours' && <QuietHoursTab active />}
          {current === 'admins' && <AdminsTab active />}
          {current === 'updates' && <UpdatesTab active />}
          {current === 'services' && <ServicesTab active />}
        </div>
      </div>
    </div>
  )
}
