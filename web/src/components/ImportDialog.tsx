import { Check, ChevronDown, Link2, ListMusic, Loader2 } from 'lucide-react'
import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react'
import { api, ApiError, type AlbumImportResult, type ImportResult, type PlaylistImportResult } from '../lib/api'
import { idFromUri, plural } from '../lib/format'
import { detectLink, type DetectedLink } from '../lib/links'
import { navigate } from '../lib/router'
import { useElapsed } from '../lib/useElapsed'
import { useSession } from '../state/session'
import { Button, Field, fieldClass, Modal } from './Modal'
import { Artwork } from './Artwork'
import { SourceIcon } from './SourceIcon'

function LinkBadge({ link, text }: { link: DetectedLink | null; text: string }) {
  if (!text.trim()) return null
  if (!link)
    return (
      <p className="flex items-center gap-2 text-xs text-dim">
        <Link2 className="size-4" />
        Paste a Spotify, Apple Music or YouTube link.
      </p>
    )
  return (
    <p className={`flex items-center gap-2 text-xs ${link.importable ? 'text-fg' : 'text-danger'}`}>
      <SourceIcon source={link.source} className="size-4" />
      {link.importable ? link.label : `${link.label}. Only playlists and albums can be imported.`}
    </p>
  )
}

function workingMessage(link: DetectedLink | null) {
  if (link && link.source !== 'spotify') return `Matching songs from ${link.name}…`
  return link?.kind === 'album' ? 'Adding the album…' : 'Copying songs from Spotify…'
}

const isAlbumResult = (result: ImportResult): result is AlbumImportResult => result.kind === 'album'

function AlbumSummary({ result }: { result: AlbumImportResult }) {
  const { album } = result
  return (
    <div className="flex items-center gap-4">
      <Artwork src={album.artwork} className="size-16 shrink-0" />
      <div className="min-w-0">
        <p className="font-semibold">{album.already ? 'Already in the Library' : 'Added to the Library'}</p>
        <p className="truncate text-sm text-dim">
          {album.name}
          {album.artists.length > 0 && ` · ${album.artists.map((a) => a.name).join(', ')}`}
        </p>
      </div>
    </div>
  )
}

function ProgressNote({ message, seconds, hint }: { message: string; seconds: number; hint: string }) {
  return (
    <div className="space-y-2" aria-live="polite">
      <div className="h-1 overflow-hidden rounded-full bg-white/10">
        <div className="h-full w-1/3 animate-[indeterminate_1.2s_ease-in-out_infinite] rounded-full bg-accent" />
      </div>
      <p className="flex justify-between gap-4 text-xs text-dim">
        <span>
          {message} {hint}
        </span>
        <span className="tabular">{seconds}s</span>
      </p>
    </div>
  )
}

function Summary({ result }: { result: PlaylistImportResult }) {
  const unmatched = result.unmatched ?? []
  const headline =
    result.total != null && result.total !== result.imported
      ? `Imported ${result.imported.toLocaleString()} of ${plural(result.total, 'song')}`
      : `Imported ${plural(result.imported, 'song')}`
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-3">
        <span className="grid size-9 shrink-0 place-items-center rounded-full bg-accent text-ink">
          <Check className="size-5" />
        </span>
        <div className="min-w-0">
          <p className="font-semibold">{headline}</p>
          <p className="truncate text-sm text-dim">into {result.playlist.name}</p>
        </div>
      </div>
      {result.truncated && <p className="text-sm text-dim">Spotify only lets us copy the first 100 songs of a playlist.</p>}
      {unmatched.length > 0 && (
        <details className="group rounded-md bg-white/[0.05]">
          <summary className="flex cursor-pointer list-none items-center justify-between px-3 py-2.5 text-sm">
            {plural(unmatched.length, 'song')} not found on Spotify
            <ChevronDown className="size-4 text-dim transition-transform group-open:rotate-180" />
          </summary>
          <ul className="scroll-thin max-h-48 overflow-y-auto px-3 pb-3 text-sm">
            {unmatched.map((t, i) => (
              <li key={i} className="truncate py-1 text-dim">
                <span className="text-fg">{t.name}</span>
                {t.artists.length > 0 && <span className="ml-2">{t.artists.join(', ')}</span>}
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  )
}

export function ImportDialog({ onClose, initialUrl, asPlaylist = false }: { onClose: () => void; initialUrl?: string; asPlaylist?: boolean }) {
  const [url, setUrl] = useState(initialUrl ?? '')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [noAlbumMatch, setNoAlbumMatch] = useState(false)
  const [result, setResult] = useState<ImportResult | null>(null)
  const { upsertPlaylist, upsertAlbum } = useSession()
  const link = detectLink(url)
  const seconds = useElapsed(busy)
  const started = useRef(false)

  const run = useCallback(
    async (target: string, copyAsPlaylist = false) => {
      setBusy(true)
      setError(null)
      setNoAlbumMatch(false)
      try {
        const res = await api.importPlaylist(target.trim(), copyAsPlaylist)
        if (isAlbumResult(res)) upsertAlbum(res.album)
        else upsertPlaylist(res.playlist)
        setResult(res)
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err))
        setNoAlbumMatch(err instanceof ApiError && err.status === 422 && detectLink(target)?.kind === 'album')
      } finally {
        setBusy(false)
      }
    },
    [upsertPlaylist, upsertAlbum],
  )

  useEffect(() => {
    if (!initialUrl || started.current || !detectLink(initialUrl)?.importable) return
    started.current = true
    void run(initialUrl, asPlaylist)
  }, [initialUrl, asPlaylist, run])

  const submit = (e: FormEvent) => {
    e.preventDefault()
    if (!link?.importable) return setError('Paste a link to a Spotify, Apple Music or YouTube playlist or album.')
    void run(url)
  }

  const open = () => {
    if (!result) return
    onClose()
    navigate(isAlbumResult(result) ? `/album/${idFromUri(result.album.uri)}` : `/playlist/${result.playlist.id}`)
  }

  if (result)
    return (
      <Modal title="Import" onClose={onClose}>
        {isAlbumResult(result) ? <AlbumSummary result={result} /> : <Summary result={result} />}
        <div className="mt-6 flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            Done
          </Button>
          <Button onClick={open}>{isAlbumResult(result) ? 'Open album' : 'Open playlist'}</Button>
        </div>
      </Modal>
    )

  return (
    <Modal title="Import" onClose={onClose} dismissable={!busy}>
      <form onSubmit={submit} className="space-y-4">
        <div className="space-y-2 text-sm leading-relaxed text-dim">
          <p>
            Paste a public playlist or album link from Spotify, Apple Music or YouTube. Playlists are copied into a new shared playlist
            credited to you; albums are added to the Library as albums.
          </p>
          <ul className="space-y-1 text-[13px]">
            <li className="flex gap-2">
              <SourceIcon source="spotify" className="mt-0.5 size-4 shrink-0" />
              Spotify playlists copy their first 100 songs.
            </li>
            <li className="flex gap-2">
              <SourceIcon source="apple" className="mt-0.5 size-4 shrink-0" />
              Apple Music songs are matched to Spotify by title, artist and length. Songs that aren't on Spotify are skipped.
              Playlists must be shared publicly.
            </li>
            <li className="flex gap-2">
              <SourceIcon source="youtube" className="mt-0.5 size-4 shrink-0" />
              YouTube and YouTube Music links are matched to Spotify the same way; nothing plays from YouTube. Playlists copy their
              first 500 songs and must be public or unlisted.
            </li>
          </ul>
        </div>
        <Field label="Link">
          <input
            autoFocus
            value={url}
            disabled={busy}
            onChange={(e) => {
              setUrl(e.target.value)
              setError(null)
            }}
            placeholder="https://open.spotify.com/playlist/…"
            className={fieldClass}
          />
        </Field>
        {!busy && <LinkBadge link={link} text={url} />}
        {busy && (
          <ProgressNote
            message={workingMessage(link)}
            seconds={seconds}
            hint={link && link.source !== 'spotify' ? 'This can take up to 30 seconds.' : 'This takes a few seconds.'}
          />
        )}
        {error && <p className="text-sm text-danger">{error}</p>}
        {noAlbumMatch && !busy && (
          <Button variant="ghost" className="w-full ring-1 ring-white/20" onClick={() => void run(url, true)}>
            <ListMusic className="size-4" />
            Import as playlist
          </Button>
        )}
        <div className="flex justify-end gap-2 pt-2">
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button type="submit" disabled={busy || !link?.importable}>
            {busy && <Loader2 className="size-4 animate-spin" />}
            {link?.kind === 'album' ? (busy ? 'Adding…' : 'Add album to Library') : busy ? 'Importing…' : 'Import'}
          </Button>
        </div>
      </form>
    </Modal>
  )
}
