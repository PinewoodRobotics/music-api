import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react'
import type { AppPlaylist } from '../lib/api'

export type Panel = 'queue' | 'lyrics'
export type Dialog =
  | { kind: 'new' }
  | { kind: 'import'; url?: string; asPlaylist?: boolean }
  | { kind: 'edit'; playlist: AppPlaylist }
  | { kind: 'delete'; playlist: AppPlaylist }
  | { kind: 'api' }
  | { kind: 'activity' }

type UI = {
  expanded: boolean
  setExpanded: (open: boolean) => void
  panel: Panel | null
  togglePanel: (panel: Panel) => void
  showPanel: (panel: Panel) => void
  dialog: Dialog | null
  openDialog: (dialog: Dialog) => void
  closeDialog: () => void
}

const UIContext = createContext<UI | null>(null)

const devPlayerView = () => (import.meta.env.DEV ? new URLSearchParams(location.search).get('np') : null)

export function UIProvider({ children }: { children: ReactNode }) {
  const [expanded, setExpanded] = useState(() => !!devPlayerView())
  const [panel, setPanel] = useState<Panel | null>(() => {
    const view = devPlayerView()
    return view === 'lyrics' || view === 'queue' ? view : null
  })
  const [dialog, setDialog] = useState<Dialog | null>(null)
  const togglePanel = useCallback((p: Panel) => setPanel((cur) => (cur === p ? null : p)), [])
  const showPanel = useCallback(
    (p: Panel) => {
      if (window.matchMedia('(min-width: 1024px)').matches) return togglePanel(p)
      setPanel(p)
      setExpanded(true)
    },
    [togglePanel],
  )
  const value = useMemo<UI>(
    () => ({
      expanded,
      setExpanded,
      panel,
      togglePanel,
      showPanel,
      dialog,
      openDialog: setDialog,
      closeDialog: () => setDialog(null),
    }),
    [expanded, panel, togglePanel, showPanel, dialog],
  )
  return <UIContext.Provider value={value}>{children}</UIContext.Provider>
}

export function useUI() {
  const ctx = useContext(UIContext)
  if (!ctx) throw new Error('useUI outside UIProvider')
  return ctx
}
