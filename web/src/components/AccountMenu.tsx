import { LogOut } from 'lucide-react'
import { useState } from 'react'
import { useSession } from '../state/session'
import { Avatar } from './Avatar'
import { Popover, type AnchorRect } from './Popover'

export function AccountMenu() {
  const { me, signOut } = useSession()
  const [anchor, setAnchor] = useState<AnchorRect | null>(null)
  if (!me) return null
  return (
    <>
      <button
        type="button"
        onClick={(e) => setAnchor(e.currentTarget.getBoundingClientRect())}
        aria-label="Account"
        className="flex items-center gap-2 rounded-full bg-black/50 p-1 pr-1 text-sm font-semibold transition-colors hover:bg-black/70 md:pr-3"
      >
        <Avatar person={me} className="size-7 text-xs" />
        <span className="max-w-32 truncate max-md:hidden">{me.name}</span>
      </button>
      {anchor && (
        <Popover anchor={anchor} align="end" onClose={() => setAnchor(null)} className="w-64 p-0">
          <div className="flex items-center gap-3 border-b border-white/[0.07] p-4">
            <Avatar person={me} className="size-10 text-base" />
            <div className="min-w-0">
              <div className="truncate font-semibold">{me.name}</div>
              <div className="text-xs text-dim">{me.kind === 'slack' ? 'Signed in with Slack' : 'Signed in with an API token'}</div>
            </div>
          </div>
          <div className="p-1">
            <button
              type="button"
              role="menuitem"
              onClick={() => {
                setAnchor(null)
                void signOut()
              }}
              className="flex w-full items-center gap-3 rounded-[5px] px-3 py-2 text-left text-sm hover:bg-white/[0.08]"
            >
              <LogOut className="size-4 text-dim" />
              Sign out
            </button>
          </div>
        </Popover>
      )}
    </>
  )
}
