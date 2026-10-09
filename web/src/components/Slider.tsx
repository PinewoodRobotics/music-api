import { useRef, useState, type KeyboardEvent, type PointerEvent } from 'react'

type Props = {
  value: number
  max: number
  label: string
  step: number
  onCommit: (value: number) => void
  onPreview?: (value: number | null) => void
  valueText?: string
  className?: string
  thick?: boolean
}

export function Slider({ value, max, label, step, onCommit, onPreview, valueText, className = '', thick }: Props) {
  const ref = useRef<HTMLDivElement>(null)
  const [drag, setDrag] = useState<number | null>(null)

  const valueAt = (clientX: number) => {
    const r = ref.current!.getBoundingClientRect()
    return Math.min(1, Math.max(0, (clientX - r.left) / r.width)) * max
  }
  const update = (v: number | null) => {
    setDrag(v)
    onPreview?.(v)
  }
  const down = (e: PointerEvent<HTMLDivElement>) => {
    if (max <= 0) return
    e.currentTarget.setPointerCapture(e.pointerId)
    update(valueAt(e.clientX))
  }
  const move = (e: PointerEvent<HTMLDivElement>) => {
    if (drag !== null) update(valueAt(e.clientX))
  }
  const up = (e: PointerEvent<HTMLDivElement>) => {
    if (drag === null) return
    onCommit(valueAt(e.clientX))
    update(null)
  }
  const key = (e: KeyboardEvent<HTMLDivElement>) => {
    const delta = { ArrowLeft: -step, ArrowDown: -step, ArrowRight: step, ArrowUp: step }[e.key]
    if (delta === undefined) return
    e.preventDefault()
    e.stopPropagation()
    onCommit(Math.min(max, Math.max(0, value + delta)))
  }

  const shown = drag ?? value
  const pct = max > 0 ? Math.min(100, (shown / max) * 100) : 0
  const dragging = drag !== null

  return (
    <div
      ref={ref}
      role="slider"
      tabIndex={0}
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={Math.round(max)}
      aria-valuenow={Math.round(shown)}
      aria-valuetext={valueText}
      onPointerDown={down}
      onPointerMove={move}
      onPointerUp={up}
      onPointerCancel={() => update(null)}
      onKeyDown={key}
      className={`group relative flex h-4 cursor-pointer touch-none items-center ${className}`}
    >
      <div className={`relative w-full overflow-hidden rounded-full bg-white/20 ${thick ? 'h-1.5' : 'h-1'}`}>
        <div
          className={`absolute inset-y-0 left-0 rounded-full ${dragging ? 'bg-accent' : 'bg-fg group-hover:bg-accent'}`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <div
        className={`pointer-events-none absolute size-3 -translate-x-1/2 rounded-full bg-white shadow-md shadow-black/50 transition-opacity ${
          dragging ? 'opacity-100' : 'opacity-0 group-hover:opacity-100 group-focus-visible:opacity-100'
        }`}
        style={{ left: `${pct}%` }}
      />
    </div>
  )
}
