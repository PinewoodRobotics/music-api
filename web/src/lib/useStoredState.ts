import { useState } from 'react'
import { storage } from './storage'

export function useStoredState<T extends string>(key: string, fallback: T, allowed: readonly T[]) {
  const [value, setValue] = useState<T>(() => {
    const stored = storage.get(key) as T | null
    return stored && allowed.includes(stored) ? stored : fallback
  })
  const update = (next: T) => {
    storage.set(key, next)
    setValue(next)
  }
  return [value, update] as const
}
