import { EmptyPlaylists } from '../components/EmptyPlaylists'
import { PlaylistActions } from '../components/PlaylistActions'
import { PlaylistRow } from '../components/PlaylistRow'
import { useSession } from '../state/session'
import { RowsSkeleton } from '../components/Skeleton'
import { ErrorState } from './Message'

export function LibraryPage() {
  const { playlists, playlistsError, retryPlaylists } = useSession()
  return (
    <div className="px-4 pb-10 pt-2">
      <h1 className="mb-4 px-1.5 font-display text-3xl font-extrabold tracking-tight">Playlists</h1>
      {playlists === null && playlistsError != null ? (
        <ErrorState title="Couldn't load playlists" error={playlistsError} onRetry={retryPlaylists} />
      ) : playlists === null ? (
        <RowsSkeleton count={5} />
      ) : playlists.length === 0 ? (
        <EmptyPlaylists />
      ) : (
        <>
          <PlaylistActions />
          <div className="mx-1.5 my-2 h-px bg-white/[0.06]" />
          {playlists.map((p) => (
            <PlaylistRow key={p.id} playlist={p} active={false} />
          ))}
        </>
      )}
    </div>
  )
}
