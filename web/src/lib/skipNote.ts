import { useEffect, useSyncExternalStore } from 'react'
import type { Person, Skip } from './api'

const VISIBLE_MS = 4000
const FADE_MS = 300

type Note = { person: Person; visible: boolean } | null

let note: Note = null
let lastShownAt = 0
let hideTimer: ReturnType<typeof setTimeout> | undefined
let clearTimer: ReturnType<typeof setTimeout> | undefined
const listeners = new Set<() => void>()

function set(next: Note) {
  note = next
  listeners.forEach((l) => l())
}

function show(person: Person) {
  clearTimeout(hideTimer)
  clearTimeout(clearTimer)
  set({ person, visible: true })
  hideTimer = setTimeout(() => {
    set(note && { ...note, visible: false })
    clearTimer = setTimeout(() => set(null), FADE_MS)
  }, VISIBLE_MS)
}

export function useSkipWatcher(skip: Skip | null | undefined, myId: string | null | undefined) {
  useEffect(() => {
    if (!skip || skip.at <= lastShownAt) return
    lastShownAt = skip.at
    if (skip.by.id && skip.by.id === myId) return
    show(skip.by)
  }, [skip, myId])
}

export function useSkipNote() {
  return useSyncExternalStore(
    (l) => {
      listeners.add(l)
      return () => void listeners.delete(l)
    },
    () => note,
  )
}
