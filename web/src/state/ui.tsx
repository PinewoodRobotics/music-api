import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react'
import type { AppPlaylist } from '../lib/api'

export type Panel = 'queue' | 'lyrics'
export type Dialog =
  | { kind: 'new' }
  | { kind: 'import'; url?: string }
  | { kind: 'edit'; playlist: AppPlaylist }
  | { kind: 'delete'; playlist: AppPlaylist }
  | { kind: 'api' }

type UI = {
  expanded: boolean
  setExpanded: (open: boolean) => void
  panel: Panel | null
  togglePanel: (panel: Panel) => void
  dialog: Dialog | null
  openDialog: (dialog: Dialog) => void
  closeDialog: () => void
}

const UIContext = createContext<UI | null>(null)

export function UIProvider({ children }: { children: ReactNode }) {
  const [expanded, setExpanded] = useState(false)
  const [panel, setPanel] = useState<Panel | null>(null)
  const [dialog, setDialog] = useState<Dialog | null>(null)
  const togglePanel = useCallback((p: Panel) => setPanel((cur) => (cur === p ? null : p)), [])
  const value = useMemo<UI>(
    () => ({
      expanded,
      setExpanded,
      panel,
      togglePanel,
      dialog,
      openDialog: setDialog,
      closeDialog: () => setDialog(null),
    }),
    [expanded, panel, togglePanel, dialog],
  )
  return <UIContext.Provider value={value}>{children}</UIContext.Provider>
}

export function useUI() {
  const ctx = useContext(UIContext)
  if (!ctx) throw new Error('useUI outside UIProvider')
  return ctx
}
