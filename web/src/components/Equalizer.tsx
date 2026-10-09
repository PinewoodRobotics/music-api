export function Equalizer({ playing = true, className = '' }: { playing?: boolean; className?: string }) {
  return (
    <span className={`inline-flex h-3.5 items-end gap-[2px] ${className}`} aria-label="Now playing">
      {[0, 0.25, 0.5, 0.15].map((delay, i) => (
        <span
          key={i}
          className={`w-[3px] rounded-full bg-accent ${playing ? 'eq-bar h-full' : 'h-1'}`}
          style={{ animationDelay: `${-delay * 3}s` }}
        />
      ))}
    </span>
  )
}
