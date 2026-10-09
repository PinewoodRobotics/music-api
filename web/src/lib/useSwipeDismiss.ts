import { useCallback, useEffect, useRef } from 'react'

const LOCK_SLOP = 8
const DISMISS_FRACTION = 0.2
const FLICK_VELOCITY = 0.5
const VELOCITY_WINDOW_MS = 80
const SPRING = 'cubic-bezier(0.32, 0.72, 0, 1)'
const NO_DRAG = '[role="slider"], input, textarea, [data-no-swipe]'

type Gesture = {
  startX: number
  startY: number
  originY: number
  mode: 'undecided' | 'dismiss' | 'native'
  scroller: HTMLElement | null
  samples: { y: number; t: number }[]
  offset: number
}

function blocksDrag(target: EventTarget | null) {
  if (!(target instanceof Element)) return false
  if (target.closest(NO_DRAG)) return true
  const button = target.closest('button, a')
  return !!button && !button.closest('[data-swipe-ok]')
}

function scrollerFor(target: EventTarget | null, root: HTMLElement) {
  for (let el = target instanceof Element ? (target as HTMLElement) : null; el && el !== root; el = el.parentElement) {
    const { overflowY } = getComputedStyle(el)
    if ((overflowY === 'auto' || overflowY === 'scroll') && el.scrollHeight > el.clientHeight) return el
  }
  return null
}

const reducedMotion = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches

export function useSwipeDismiss(onDismiss: () => void) {
  const ref = useRef<HTMLDivElement>(null)
  const backdropRef = useRef<HTMLDivElement>(null)
  const closing = useRef(false)
  const dismissRef = useRef(onDismiss)
  dismissRef.current = onDismiss

  const paint = useCallback((offset: number, transition: string) => {
    const sheet = ref.current
    if (!sheet) return
    const progress = Math.min(1, Math.max(0, offset / window.innerHeight))
    sheet.style.transition = transition
    sheet.style.transform = offset ? `translate3d(0, ${offset}px, 0)` : ''
    const backdrop = backdropRef.current
    if (backdrop) {
      backdrop.style.transition = transition.replace('transform', 'opacity')
      backdrop.style.opacity = String(0.55 * (1 - progress))
    }
    const shell = document.querySelector<HTMLElement>('[data-app-shell]')
    if (shell) {
      shell.style.transition = transition
      shell.style.transformOrigin = 'center top'
      shell.style.transform = offset ? `scale(${0.94 + 0.06 * progress})` : ''
    }
  }, [])

  const finish = useCallback(
    (fromOffset: number, velocity: number) => {
      if (closing.current) return
      closing.current = true
      const remaining = Math.max(0, window.innerHeight - fromOffset)
      const duration = reducedMotion() ? 0 : Math.round(Math.min(320, Math.max(140, remaining / Math.max(velocity, 1.6))))
      paint(window.innerHeight, `transform ${duration}ms cubic-bezier(0.2, 0.6, 0.35, 1)`)
      setTimeout(() => {
        const shell = document.querySelector<HTMLElement>('[data-app-shell]')
        if (shell) shell.style.transform = shell.style.transition = ''
        dismissRef.current()
      }, duration)
    },
    [paint],
  )

  const dismiss = useCallback(() => finish(0, 0), [finish])

  useEffect(() => {
    const sheet = ref.current
    if (!sheet) return
    let gesture: Gesture | null = null
    let frame = 0

    const begin = (x: number, y: number, target: EventTarget | null) => {
      if (closing.current || blocksDrag(target)) return
      gesture = { startX: x, startY: y, originY: y, mode: 'undecided', scroller: scrollerFor(target, sheet), samples: [{ y, t: performance.now() }], offset: 0 }
    }

    const move = (x: number, y: number): boolean => {
      const g = gesture
      if (!g || g.mode === 'native') return false
      if (g.mode === 'undecided') {
        const dx = x - g.startX
        const dy = y - g.startY
        if (Math.abs(dx) < LOCK_SLOP && Math.abs(dy) < LOCK_SLOP) return false
        const downward = dy > 0 && dy > Math.abs(dx)
        if (!downward || (g.scroller && g.scroller.scrollTop > 0)) {
          g.mode = 'native'
          return false
        }
        g.mode = 'dismiss'
        g.originY = y
      }
      const raw = y - g.originY
      g.offset = raw >= 0 ? raw : raw / 4
      const now = performance.now()
      g.samples.push({ y, t: now })
      while (g.samples.length > 2 && now - g.samples[0].t > VELOCITY_WINDOW_MS) g.samples.shift()
      cancelAnimationFrame(frame)
      frame = requestAnimationFrame(() => gesture && paint(gesture.offset, 'none'))
      return true
    }

    const end = (cancelled: boolean): boolean => {
      const g = gesture
      gesture = null
      if (!g || g.mode !== 'dismiss') return false
      cancelAnimationFrame(frame)
      const first = g.samples[0]
      const last = g.samples[g.samples.length - 1]
      const velocity = last.t > first.t ? (last.y - first.y) / (last.t - first.t) : 0
      if (!cancelled && (g.offset > window.innerHeight * DISMISS_FRACTION || velocity > FLICK_VELOCITY)) finish(g.offset, velocity)
      else paint(0, `transform 350ms ${SPRING}`)
      return true
    }

    const onTouchStart = (e: TouchEvent) => {
      if (e.touches.length !== 1) return void (gesture = null)
      begin(e.touches[0].clientX, e.touches[0].clientY, e.target)
    }
    const onTouchMove = (e: TouchEvent) => {
      if (e.touches.length !== 1) return
      if (move(e.touches[0].clientX, e.touches[0].clientY) && e.cancelable) e.preventDefault()
    }
    const onTouchEnd = (e: TouchEvent) => {
      if (end(e.type === 'touchcancel') && e.cancelable) e.preventDefault()
    }

    const onPointerDown = (e: PointerEvent) => {
      if (e.pointerType !== 'mouse' || e.button !== 0) return
      begin(e.clientX, e.clientY, e.target)
    }
    const onPointerMove = (e: PointerEvent) => {
      if (e.pointerType === 'mouse' && move(e.clientX, e.clientY) && !sheet.hasPointerCapture(e.pointerId)) sheet.setPointerCapture(e.pointerId)
    }
    let swallowClick = false
    const onPointerUp = (e: PointerEvent) => {
      if (e.pointerType !== 'mouse') return
      if (end(false)) swallowClick = true
    }
    const onClick = (e: MouseEvent) => {
      if (!swallowClick) return
      swallowClick = false
      e.preventDefault()
      e.stopPropagation()
    }

    sheet.addEventListener('touchstart', onTouchStart, { passive: true })
    sheet.addEventListener('touchmove', onTouchMove, { passive: false })
    sheet.addEventListener('touchend', onTouchEnd, { passive: false })
    sheet.addEventListener('touchcancel', onTouchEnd, { passive: false })
    sheet.addEventListener('pointerdown', onPointerDown)
    sheet.addEventListener('pointermove', onPointerMove)
    sheet.addEventListener('pointerup', onPointerUp)
    sheet.addEventListener('click', onClick, true)

    const html = document.documentElement
    const previousOverflow = html.style.overflow
    html.style.overflow = 'hidden'

    return () => {
      cancelAnimationFrame(frame)
      sheet.removeEventListener('touchstart', onTouchStart)
      sheet.removeEventListener('touchmove', onTouchMove)
      sheet.removeEventListener('touchend', onTouchEnd)
      sheet.removeEventListener('touchcancel', onTouchEnd)
      sheet.removeEventListener('pointerdown', onPointerDown)
      sheet.removeEventListener('pointermove', onPointerMove)
      sheet.removeEventListener('pointerup', onPointerUp)
      sheet.removeEventListener('click', onClick, true)
      html.style.overflow = previousOverflow
      const shell = document.querySelector<HTMLElement>('[data-app-shell]')
      if (shell) shell.style.transform = shell.style.transition = ''
    }
  }, [finish, paint])

  return { ref, backdropRef, dismiss }
}
