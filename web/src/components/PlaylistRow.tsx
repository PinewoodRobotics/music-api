import { Volume2 } from 'lucide-react'
import type { AppPlaylist } from '../lib/api'
import { usePlayer } from '../state/player'
import { Artwork } from './Artwork'
import { Link } from './Link'

export function creatorLine(p: AppPlaylist) {
  if (!p.created_by) return p.source_url ? 'Imported from Spotify' : 'Playlist'
  return p.source_url ? `Imported by ${p.created_by.name}` : `By ${p.created_by.name}`
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
        <div className="truncate text-[13px] text-dim">{creatorLine(playlist)}</div>
      </div>
      {playing && isPlaying && <Volume2 className="mr-1 size-4 shrink-0 text-accent" aria-label="Playing" />}
    </Link>
  )
}
