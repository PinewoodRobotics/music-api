import { api } from '../../lib/api'
import { byline, idFromUri } from '../../lib/format'
import { navigate } from '../../lib/router'
import { Artwork } from '../../components/Artwork'
import { usePlayer } from '../../state/player'
import { PlayFab } from './PlayFab'
import type { TopResult } from './topResult'

const LABELS = { artist: 'Artist', album: 'Album', playlist: 'Playlist', track: 'Song' }

function details(top: TopResult) {
  switch (top.kind) {
    case 'artist':
      return { sub: '', href: `/artist/${top.item.id}` }
    case 'album':
      return { sub: byline(top.item), href: `/album/${top.item.id}` }
    case 'playlist':
      return { sub: top.item.owner, href: null }
    case 'track':
      return { sub: byline(top.item), href: top.item.album?.uri ? `/album/${idFromUri(top.item.album.uri)}` : null }
  }
}

export function TopResultCard({ top }: { top: TopResult }) {
  const { status, isPlaying, togglePlay, start, pending } = usePlayer()
  const { uri, name, artwork } = top.item
  const { sub, href } = details(top)
  const current = top.kind === 'track' ? status?.track?.uri === uri : status?.context?.uri === uri
  const play = () => (current ? togglePlay() : void start(uri, () => api.play({ uri })))

  return (
    <div
      role="link"
      tabIndex={0}
      onClick={() => (href ? navigate(href) : play())}
      onKeyDown={(e) => e.key === 'Enter' && (href ? navigate(href) : play())}
      className="group relative min-h-[236px] flex-1 cursor-pointer rounded-lg bg-white/[0.04] p-5 transition-colors hover:bg-white/[0.08]"
    >
      <Artwork src={artwork} round={top.kind === 'artist'} className="size-24 shadow-[0_8px_24px_rgba(0,0,0,0.5)]" />
      <h3 className="mt-5 line-clamp-2 pr-14 font-display text-[2rem] font-bold leading-tight tracking-tight">{name}</h3>
      <p className="mt-2 flex min-w-0 items-center gap-2 pr-14 text-sm text-dim">
        <span className="shrink-0 rounded-full bg-black/40 px-2.5 py-0.5 text-xs font-semibold text-fg">{LABELS[top.kind]}</span>
        <span className="truncate">{sub}</span>
      </p>
      <PlayFab
        playing={current && isPlaying}
        pending={pending === uri}
        label={`Play ${name}`}
        onClick={play}
        className={`absolute bottom-5 right-5 ${
          current || pending === uri ? 'opacity-100' : 'md:translate-y-2 md:opacity-0 md:group-hover:translate-y-0 md:group-hover:opacity-100'
        }`}
      />
    </div>
  )
}
