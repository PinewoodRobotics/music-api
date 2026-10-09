import { Music2 } from 'lucide-react'
import { useState } from 'react'

type Props = { src: string | null | undefined; className?: string; round?: boolean; alt?: string }

export function Artwork({ src, className = '', round = false, alt = '' }: Props) {
  const [failed, setFailed] = useState<string | null>(null)
  const shape = round ? 'rounded-full' : 'rounded-[6px]'
  if (!src || failed === src)
    return (
      <div className={`grid place-items-center bg-gradient-to-br from-raised to-panel text-faint ${shape} ${className}`}>
        <Music2 className="size-[38%] max-h-16 max-w-16" strokeWidth={1.5} />
      </div>
    )
  return (
    <img
      src={src}
      alt={alt}
      loading="lazy"
      draggable={false}
      onError={() => setFailed(src)}
      className={`bg-raised object-cover ${shape} ${className}`}
    />
  )
}
