import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react'
import { errorMessage } from '../lib/api'

export type ToastAction = { label: string; run: () => void }
export type Toast = { id: number; message: string; tone: 'info' | 'error'; action?: ToastAction }

type ToastApi = { show: (message: string, action?: ToastAction) => void; error: (err: unknown) => void }

const ToastContext = createContext<ToastApi | null>(null)
const ToastListContext = createContext<{ toasts: Toast[]; dismiss: (id: number) => void }>({ toasts: [], dismiss: () => {} })

let nextId = 1

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([])
  const dismiss = useCallback((id: number) => setToasts((t) => t.filter((x) => x.id !== id)), [])
  const push = useCallback(
    (message: string, tone: Toast['tone'], action?: ToastAction) => {
      const id = nextId++
      setToasts((t) => [...t.filter((x) => x.message !== message), { id, message, tone, action }].slice(-3))
      setTimeout(() => dismiss(id), tone === 'error' ? 6000 : action ? 7000 : 3500)
    },
    [dismiss],
  )
  const api = useMemo<ToastApi>(
    () => ({ show: (m, action) => push(m, 'info', action), error: (e) => push(errorMessage(e), 'error') }),
    [push],
  )
  const list = useMemo(() => ({ toasts, dismiss }), [toasts, dismiss])
  return (
    <ToastContext.Provider value={api}>
      <ToastListContext.Provider value={list}>{children}</ToastListContext.Provider>
    </ToastContext.Provider>
  )
}

export function useToast() {
  const ctx = useContext(ToastContext)
  if (!ctx) throw new Error('useToast outside ToastProvider')
  return ctx
}

export const useToastList = () => useContext(ToastListContext)
