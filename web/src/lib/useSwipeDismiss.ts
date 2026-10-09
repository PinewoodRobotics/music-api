import { useCallback, useRef, type MouseEvent, type PointerEvent } from 'react'

const START_SLOP = 8
const DISMISS_FRACTION = 0.25
const FLICK_VELOCITY = 0.6
const EXIT_MS = 220

type Drag = { id: number; x: number; y: number; lastY: number; lastT: number; v: number; dy: number; active: boolean }

export function useSwipeDismiss(onDismiss: () => void) {
  const ref = useRef<HTMLDivElement>(null)
  const drag = useRef<Drag | null>(null)
  const swallowClick = useRef(false)

  const animate = (transform: string, transition: string) => {
    const el = ref.current
    if (!el) return
    el.style.transition = transition
    el.style.transform = transform
  }

  const dismiss = useCallback(() => {
    const el = ref.current
    if (!el || window.matchMedia('(prefers-reduced-motion: reduce)').matches) return onDismiss()
    el.style.transition = `transform ${EXIT_MS}ms cubic-bezier(0.4, 0, 1, 1)`
    el.style.transform = 'translate3d(0, 100%, 0)'
    setTimeout(onDismiss, EXIT_MS)
  }, [onDismiss])

  const onPointerDown = (e: PointerEvent<HTMLDivElement>) => {
    if (e.button !== 0 || (e.target as Element).closest('[data-no-swipe]')) return
    drag.current = { id: e.pointerId, x: e.clientX, y: e.clientY, lastY: e.clientY, lastT: e.timeStamp, v: 0, dy: 0, active: false }
  }

  const onPointerMove = (e: PointerEvent<HTMLDivElement>) => {
    const d = drag.current
    if (!d || d.id !== e.pointerId) return
    const dy = e.clientY - d.y
    if (!d.active) {
      if (Math.abs(dy) < START_SLOP && Math.abs(e.clientX - d.x) < START_SLOP) return
      if (dy <= 0 || Math.abs(e.clientX - d.x) > Math.abs(dy)) {
        drag.current = null
        return
      }
      d.active = true
      try {
        ref.current?.setPointerCapture(e.pointerId)
      } catch {
        drag.current = null
        return
      }
    }
    const dt = Math.max(1, e.timeStamp - d.lastT)
    d.v = 0.7 * ((e.clientY - d.lastY) / dt) + 0.3 * d.v
    d.lastY = e.clientY
    d.lastT = e.timeStamp
    d.dy = dy
    animate(`translate3d(0, ${dy > 0 ? dy : dy / 4}px, 0)`, 'none')
  }

  const onPointerEnd = (e: PointerEvent<HTMLDivElement>) => {
    const d = drag.current
    if (!d || d.id !== e.pointerId) return
    drag.current = null
    if (!d.active) return
    swallowClick.current = true
    setTimeout(() => (swallowClick.current = false), 0)
    const height = ref.current?.offsetHeight ?? window.innerHeight
    if (e.type !== 'pointercancel' && (d.dy > height * DISMISS_FRACTION || d.v > FLICK_VELOCITY)) dismiss()
    else animate('translate3d(0, 0, 0)', 'transform 380ms cubic-bezier(0.2, 0.9, 0.3, 1.15)')
  }

  const onClickCapture = (e: MouseEvent) => {
    if (!swallowClick.current) return
    e.preventDefault()
    e.stopPropagation()
  }

  return {
    ref,
    dismiss,
    handlers: { onPointerDown, onPointerMove, onPointerUp: onPointerEnd, onPointerCancel: onPointerEnd, onClickCapture },
  }
}
