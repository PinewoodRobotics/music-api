export function BrandMark({ className = 'size-8' }: { className?: string }) {
  return (
    <span className={`grid shrink-0 place-items-center rounded-[28%] bg-accent text-ink ${className}`} aria-hidden>
      <svg viewBox="0 0 64 64" className="size-[70%]" fill="currentColor">
        <rect x="9" y="25" width="7" height="14" rx="3.5" />
        <rect x="21" y="14" width="7" height="36" rx="3.5" />
        <rect x="33" y="20" width="7" height="24" rx="3.5" />
        <rect x="45" y="27" width="7" height="10" rx="3.5" />
      </svg>
    </span>
  )
}

export function Brand() {
  return (
    <div className="flex items-center gap-3">
      <BrandMark className="size-9" />
      <div className="leading-tight">
        <div className="font-display text-[17px] font-bold tracking-tight">Robotics Music</div>
        <div className="text-[11px] text-faint">So Musical!!</div>
      </div>
    </div>
  )
}
