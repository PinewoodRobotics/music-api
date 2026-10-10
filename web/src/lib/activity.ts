import { useSyncExternalStore } from 'react'
import { api, type ActivityEntry } from './api'

const DAY_MS = 24 * 60 * 60 * 1000
const TOAST_MAX_AGE_MS = 30_000
const MAX_ENTRIES = 500

type ToastListener = (entry: ActivityEntry, isUpdate: boolean) => void

let entries: ActivityEntry[] = []
let latest = 0
let loaded = false
let loading: Promise<void> | null = null
const listeners = new Set<() => void>()
const toastListeners = new Set<ToastListener>()

function emit() {
  listeners.forEach((l) => l())
}

function prune(list: ActivityEntry[]) {
  const cutoff = Date.now() - DAY_MS
  return list.filter((e) => e.at >= cutoff).slice(-MAX_ENTRIES)
}

function upsert(entry: ActivityEntry, live: boolean) {
  const index = entries.findIndex((e) => e.id === entry.id)
  const isUpdate = index >= 0
  if (isUpdate) entries = entries.map((e, i) => (i === index ? entry : e))
  else entries = prune([...entries, entry].sort((a, b) => a.id - b.id))
  latest = Math.max(latest, entry.id)
  emit()
  if (live && (isUpdate || Date.now() - entry.at < TOAST_MAX_AGE_MS)) toastListeners.forEach((l) => l(entry, isUpdate))
}

export const activity = {
  load() {
    if (loaded) return Promise.resolve()
    loading ??= api
      .activity({ limit: MAX_ENTRIES })
      .then((res) => {
        entries = prune(res.entries)
        latest = Math.max(latest, res.latest ?? 0, ...entries.map((e) => e.id))
        loaded = true
        emit()
      })
      .finally(() => (loading = null))
    return loading
  },
  receive(entry: ActivityEntry) {
    upsert(entry, true)
  },
  async catchUp() {
    if (!loaded) return activity.load()
    const res = await api.activity({ since: latest })
    res.entries.forEach((e) => upsert(e, true))
  },
  onToast(listener: ToastListener) {
    toastListeners.add(listener)
    return () => void toastListeners.delete(listener)
  },
}

const subscribe = (listener: () => void) => {
  listeners.add(listener)
  return () => void listeners.delete(listener)
}

export function useActivity() {
  const list = useSyncExternalStore(subscribe, () => entries)
  const ready = useSyncExternalStore(subscribe, () => loaded)
  return { entries: list, ready }
}
