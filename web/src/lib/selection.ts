import { useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent, type MouseEvent, type PointerEvent } from 'react'
import { isTouch } from './device'

const LONG_PRESS_MS = 450
const MOVE_TOLERANCE = 10
const KEEP_SELECTION = '[data-selection-root], [role="menu"], [role="dialog"]:not([aria-label="Now Playing"]), [data-selection-bar], [role="status"]'

const isMac = () => /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent)
const commandKey = (e: { metaKey: boolean; ctrlKey: boolean }) => (isMac() ? e.metaKey : e.ctrlKey)

type RowOptions = {
  primary: () => void
  openMenu?: (e: MouseEvent, indices: number[]) => void
}

type KeyOptions = {
  primary?: (indices: number[]) => void
  remove?: (indices: number[]) => void
  scrollTo?: (index: number) => void
}

export function useSelection(keys: string[], { forceTouchMode = false }: { forceTouchMode?: boolean } = {}) {
  const [selected, setSelected] = useState<Set<string>>(() => new Set())
  const [touchModeState, setTouchMode] = useState(false)
  const [pressing, setPressing] = useState<number | null>(null)
  const anchor = useRef<string | null>(null)
  const focus = useRef<string | null>(null)
  const root = useRef<HTMLElement | null>(null)
  const press = useRef<{ timer: ReturnType<typeof setTimeout>; x: number; y: number; fired: boolean } | null>(null)
  const swallowClick = useRef(false)
  const touchMode = forceTouchMode || touchModeState

  const keyIndex = useMemo(() => new Map(keys.map((k, i) => [k, i])), [keys])

  useEffect(() => {
    setSelected((prev) => {
      const next = new Set([...prev].filter((k) => keyIndex.has(k)))
      return next.size === prev.size ? prev : next
    })
  }, [keyIndex])

  const indices = useMemo(
    () => [...selected].map((k) => keyIndex.get(k)).filter((i): i is number => i !== undefined).sort((a, b) => a - b),
    [selected, keyIndex],
  )

  const clear = useCallback(() => {
    setSelected((prev) => (prev.size ? new Set() : prev))
    anchor.current = null
  }, [])

  const selectAll = useCallback(() => setSelected(new Set(keys)), [keys])

  const range = (from: string, to: number) => {
    const a = keyIndex.get(from) ?? to
    const [lo, hi] = [Math.min(a, to), Math.max(a, to)]
    return keys.slice(lo, hi + 1)
  }

  const selectOnly = (i: number) => {
    anchor.current = focus.current = keys[i]
    setSelected(new Set([keys[i]]))
  }

  const toggle = (i: number) => {
    anchor.current = focus.current = keys[i]
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(keys[i])) next.delete(keys[i])
      else next.add(keys[i])
      return next
    })
  }

  const click = (i: number, e: MouseEvent, primary: () => void) => {
    if (swallowClick.current) {
      swallowClick.current = false
      return
    }
    if (touchMode) return toggle(i)
    if (isTouch()) return primary()
    if (e.shiftKey && anchor.current !== null) {
      const span = range(anchor.current, i)
      focus.current = keys[i]
      setSelected((prev) => (commandKey(e) ? new Set([...prev, ...span]) : new Set(span)))
      return
    }
    if (commandKey(e)) return toggle(i)
    selectOnly(i)
  }

  const ensureSelected = (i: number) => {
    if (selected.has(keys[i])) return indices
    selectOnly(i)
    return [i]
  }

  const cancelPress = () => {
    if (press.current) clearTimeout(press.current.timer)
    press.current = null
    setPressing(null)
  }

  useEffect(() => {
    if (touchMode) return
    const down = (e: globalThis.PointerEvent) => {
      if (!selected.size || e.pointerType !== 'mouse') return
      const target = e.target as Element | null
      if (target?.closest(KEEP_SELECTION)) return
      clear()
    }
    document.addEventListener('pointerdown', down)
    return () => document.removeEventListener('pointerdown', down)
  }, [selected.size, touchMode, clear])

  const rowProps = (i: number, { primary, openMenu }: RowOptions) => ({
    'data-row-index': i,
    'aria-selected': selected.has(keys[i]),
    onClick: (e: MouseEvent) => {
      e.stopPropagation()
      click(i, e, primary)
    },
    onDoubleClick: () => {
      if (!touchMode && !isTouch()) primary()
    },
    onContextMenu: (e: MouseEvent) => {
      e.preventDefault()
      if (isTouch()) return
      const target = ensureSelected(i)
      openMenu?.(e, target)
    },
    onPointerDown: (e: PointerEvent) => {
      if (e.pointerType === 'mouse' || touchMode) return
      const timer = setTimeout(() => {
        if (!press.current) return
        press.current.fired = true
        swallowClick.current = true
        navigator.vibrate?.(12)
        setTouchMode(true)
        selectOnly(i)
        setPressing(null)
      }, LONG_PRESS_MS)
      press.current = { timer, x: e.clientX, y: e.clientY, fired: false }
      setPressing(i)
    },
    onPointerMove: (e: PointerEvent) => {
      const p = press.current
      if (p && Math.hypot(e.clientX - p.x, e.clientY - p.y) > MOVE_TOLERANCE) cancelPress()
    },
    onPointerUp: () => {
      if (press.current && !press.current.fired) cancelPress()
      else press.current = null
    },
    onPointerCancel: cancelPress,
    style: pressing === i ? { transform: 'scale(0.97)', transition: 'transform 300ms ease' } : undefined,
  })

  const onKeyDown = (e: KeyboardEvent, { primary, remove, scrollTo }: KeyOptions = {}) => {
    const target = e.target as HTMLElement
    if (target.closest('input, textarea, [contenteditable="true"]')) return
    if (e.key === 'Escape' && selected.size) {
      e.stopPropagation()
      clear()
      return
    }
    if ((e.key === 'a' || e.key === 'A') && commandKey(e)) {
      e.preventDefault()
      selectAll()
      return
    }
    if (e.key === 'Enter' && indices.length && primary) {
      e.preventDefault()
      primary(indices)
      return
    }
    if ((e.key === 'Delete' || e.key === 'Backspace') && indices.length && remove) {
      e.preventDefault()
      remove(indices)
      return
    }
    if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp') return
    e.preventDefault()
    const current = focus.current !== null ? (keyIndex.get(focus.current) ?? -1) : indices.length ? indices[indices.length - 1] : -1
    const next = Math.max(0, Math.min(keys.length - 1, current + (e.key === 'ArrowDown' ? 1 : -1)))
    if (e.shiftKey && anchor.current !== null) {
      focus.current = keys[next]
      setSelected(new Set(range(anchor.current, next)))
    } else selectOnly(next)
    scrollTo?.(next)
    requestAnimationFrame(() => root.current?.querySelector<HTMLElement>(`[data-row-index="${next}"]`)?.focus({ preventScroll: !!scrollTo }))
  }

  const rootProps = (options: KeyOptions = {}) => ({
    ref: (el: HTMLElement | null) => {
      root.current = el
    },
    'data-selection-root': '',
    onKeyDown: (e: KeyboardEvent) => onKeyDown(e, options),
    onClick: (e: MouseEvent) => {
      if (!touchMode && !(e.target as Element).closest('[data-row-index]')) clear()
    },
  })

  const exitTouchMode = () => {
    setTouchMode(false)
    clear()
  }

  return {
    selected,
    indices,
    isSelected: (i: number) => selected.has(keys[i]),
    touchMode,
    rowProps,
    rootProps,
    ensureSelected,
    clear,
    selectAll,
    exitTouchMode,
  }
}

export type Selection = ReturnType<typeof useSelection>
