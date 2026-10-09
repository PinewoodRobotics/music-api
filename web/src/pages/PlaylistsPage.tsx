import { Download, Plus } from 'lucide-react'
import type { ReactNode } from 'react'
import { api } from '../lib/api'
import { EmptyPlaylists } from '../components/EmptyPlaylists'
import { CardGrid, MediaCard } from '../components/MediaCard'
import { PlaylistByline } from '../components/PlaylistRow'
import { CardsSkeleton } from '../components/Skeleton'
import { usePlayer } from '../state/player'
import { useSession } from '../state/session'
import { useUI } from '../state/ui'
import { ErrorState } from './Message'

function Action({ icon, label, onClick, primary }: { icon: ReactNode; label: string; onClick: () => void; primary?: boolean }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`inline-flex h-11 items-center gap-2 rounded-full px-4 text-sm font-semibold transition active:scale-95 [&>svg]:size-4 ${
        primary ? 'bg-fg text-canvas hover:scale-[1.03]' : 'bg-white/10 text-fg hover:bg-white/15 active:bg-white/20'
      }`}
    >
      {icon}
      {label}
    </button>
  )
}

export function PlaylistsPage() {
  const { playlists, playlistsError, retryPlaylists } = useSession()
  const { status, isPlaying, togglePlay, start, pending } = usePlayer()
  const { openDialog } = useUI()
  const sorted = [...(playlists ?? [])].sort((a, b) => (b.created ?? '').localeCompare(a.created ?? ''))

  return (
    <div className="px-3 pb-12 pt-2 max-sm:px-2">
      <div className="mb-4 flex flex-wrap items-end justify-between gap-3 px-3 max-sm:px-2">
        <h1 className="font-display text-[clamp(1.9rem,4vw,3rem)] font-extrabold tracking-tight">Playlists</h1>
        {sorted.length > 0 && (
          <div className="flex gap-2">
            <Action primary icon={<Plus />} label="New playlist" onClick={() => openDialog({ kind: 'new' })} />
            <Action icon={<Download />} label="Import" onClick={() => openDialog({ kind: 'import' })} />
          </div>
        )}
      </div>
      {playlists === null && playlistsError != null ? (
        <ErrorState title="Couldn't load playlists" error={playlistsError} onRetry={retryPlaylists} />
      ) : playlists === null ? (
        <CardsSkeleton count={6} />
      ) : sorted.length === 0 ? (
        <EmptyPlaylists />
      ) : (
        <CardGrid>
          {sorted.map((p) => {
            const current = status?.context?.uri === p.uri
            return (
              <MediaCard
                key={p.id}
                title={p.name}
                subtitle={<PlaylistByline playlist={p} />}
                artwork={p.artwork}
                href={`/playlist/${p.id}`}
                playing={current && isPlaying}
                pending={pending === p.uri}
                onPlay={() => (current ? togglePlay() : void start(p.uri, () => api.playPlaylist(p.id, { shuffle: false }), false))}
              />
            )
          })}
        </CardGrid>
      )}
    </div>
  )
}
