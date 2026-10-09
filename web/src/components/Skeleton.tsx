const bar = 'animate-pulse rounded bg-white/[0.07]'

export function RowsSkeleton({ count = 8, numbered = false }: { count?: number; numbered?: boolean }) {
  return (
    <div aria-busy="true" aria-label="Loading">
      {Array.from({ length: count }, (_, i) => (
        <div key={i} className="flex h-14 items-center gap-4 px-4 max-md:px-2" style={{ opacity: 1 - i * (0.7 / count) }}>
          {numbered && <div className={`${bar} h-3 w-4 max-md:hidden`} />}
          <div className={`${bar} size-10 shrink-0 rounded-[4px]`} />
          <div className="flex-1 space-y-2">
            <div className={`${bar} h-3`} style={{ width: `${38 + ((i * 17) % 30)}%` }} />
            <div className={`${bar} h-2.5`} style={{ width: `${18 + ((i * 11) % 18)}%` }} />
          </div>
          <div className={`${bar} h-3 w-9`} />
        </div>
      ))}
    </div>
  )
}

export function CardsSkeleton({ count = 6, round = false }: { count?: number; round?: boolean }) {
  return (
    <div className="grid grid-cols-[repeat(auto-fill,minmax(168px,1fr))] max-sm:grid-cols-2" aria-busy="true">
      {Array.from({ length: count }, (_, i) => (
        <div key={i} className="p-3 max-sm:p-2">
          <div className={`${bar} mb-3 aspect-square w-full ${round ? '!rounded-full' : '!rounded-[6px]'}`} />
          <div className={`${bar} h-3 w-3/4`} />
          <div className={`${bar} mt-2 h-2.5 w-1/2`} />
        </div>
      ))}
    </div>
  )
}

export function HeaderSkeleton() {
  return (
    <div className="flex items-end gap-6 px-6 pb-6 pt-6 max-sm:flex-col max-sm:items-start max-sm:px-4" aria-busy="true">
      <div className={`${bar} size-[clamp(160px,20vw,232px)] shrink-0 !rounded-[6px] max-sm:mx-auto max-sm:size-[min(60vw,240px)]`} />
      <div className="w-full flex-1 space-y-4 pb-2">
        <div className={`${bar} h-3 w-16`} />
        <div className={`${bar} h-12 w-2/3`} />
        <div className={`${bar} h-3 w-1/3`} />
      </div>
    </div>
  )
}
