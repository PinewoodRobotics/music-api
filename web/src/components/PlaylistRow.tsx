import { Volume2 } from 'lucide-react'
import type { AppPlaylist } from '../lib/api'
import { usePlayer } from '../state/player'
import { Artwork } from './Artwork'
import { Attribution } from './Attribution'
import { Link } from './Link'

export function PlaylistByline({ playlist, className = '' }: { playlist: AppPlaylist; className?: string }) {
  if (!playlist.created_by && !playlist.source_url) return <span className={className}>Playlist</span>
  return <Attribution person={playlist.created_by} sourceUrl={playlist.source_url} className={className} />
}

export function PlaylistRow({ playlist, active }: { playlist: AppPlaylist; active: boolean }) {
  const { status, isPlaying } = usePlayer()
  const playing = status?.context?.uri === playlist.uri
  return (
    <Link
      href={`/playlist/${playlist.id}`}
      className={`flex items-center gap-3 rounded-md p-1.5 transition-colors ${active ? 'bg-white/[0.09]' : 'hover:bg-white/[0.05]'}`}
    >
      <Artwork src={playlist.artwork} className="size-11 shrink-0" />
      <div className="min-w-0 flex-1">
        <div className={`truncate text-[15px] ${playing ? 'text-accent' : 'text-fg'}`}>{playlist.name}</div>
        <PlaylistByline playlist={playlist} className="text-[13px] text-dim" />
      </div>
      {playing && isPlaying && <Volume2 className="mr-1 size-4 shrink-0 text-accent" aria-label="Playing" />}
    </Link>
  )
}
