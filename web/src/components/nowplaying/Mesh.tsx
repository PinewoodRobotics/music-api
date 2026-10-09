import { useMesh } from '../../lib/color'

const BLOBS = [
  { left: '-30vmax', top: '-35vmax', animation: 'drift-a 28s ease-in-out infinite alternate' },
  { right: '-35vmax', top: '-20vmax', animation: 'drift-b 34s ease-in-out infinite alternate' },
  { left: '-20vmax', bottom: '-40vmax', animation: 'drift-b 31s ease-in-out -9s infinite alternate' },
  { right: '-30vmax', bottom: '-35vmax', animation: 'drift-a 37s ease-in-out -14s infinite alternate' },
]

export function Mesh({ art }: { art: string | null | undefined }) {
  const colors = useMesh(art)
  return (
    <div
      className="absolute inset-0 overflow-hidden transition-[background] duration-1000"
      style={{ background: `linear-gradient(160deg, ${colors[0]}, ${colors[3]})` }}
      aria-hidden
    >
      {art && (
        <img
          key={art}
          src={art}
          alt=""
          className="animate-[fade-in_1.2s_ease] absolute inset-0 size-full scale-150 object-cover opacity-45 blur-[90px] saturate-150"
        />
      )}
      {BLOBS.map((pos, i) => (
        <div key={i} className="mesh-blob" style={{ ...pos, background: `radial-gradient(circle at center, ${colors[i]} 0%, transparent 62%)` }} />
      ))}
      <div className="absolute inset-0 bg-black/30" />
    </div>
  )
}
