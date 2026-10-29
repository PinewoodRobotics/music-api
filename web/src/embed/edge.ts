const EDGE = 48

/** Swipes that start on the top edge belong to the framing panel (it slides the app away), so they are posted up. */
export function forwardEdgeSwipes() {
  const parentOrigin = location.ancestorOrigins?.[0]
  if (!parentOrigin || window.parent === window) return
  let start: { y: number; t: number } | null = null
  const post = (phase: 'move' | 'end', y: number) => {
    if (!start) return
    const dy = Math.max(0, y - start.y)
    window.parent.postMessage({ type: 'fms-edge', phase, dy, vy: dy / Math.max(1, performance.now() - start.t) }, parentOrigin)
  }
  window.addEventListener(
    'touchstart',
    (e) => {
      const y = e.touches[0]?.clientY ?? Infinity
      start = e.touches.length === 1 && y < EDGE ? { y, t: performance.now() } : null
    },
    { passive: true },
  )
  window.addEventListener(
    'touchmove',
    (e) => {
      if (!start) return
      e.preventDefault()
      post('move', e.touches[0].clientY)
    },
    { passive: false },
  )
  const end = (e: TouchEvent) => {
    post('end', e.changedTouches[0]?.clientY ?? 0)
    start = null
  }
  window.addEventListener('touchend', end, { passive: true })
  window.addEventListener('touchcancel', end, { passive: true })
}
