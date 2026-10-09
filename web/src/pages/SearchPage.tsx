import { Loader2, Search, X } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { api, type SearchResults } from '../lib/api'
import { byline, year } from '../lib/format'
import { navigate, useLocation } from '../lib/router'
import { CardGrid, MediaCard, Section } from '../components/MediaCard'
import { TrackList } from '../components/TrackList'
import { usePlayer } from '../state/player'
import { useToast } from '../state/toast'
import { CardsSkeleton, RowsSkeleton } from '../components/Skeleton'
import { Message } from './Message'

function useSearch(q: string) {
  const [results, setResults] = useState<{ q: string; data: SearchResults } | null>(null)
  const [loading, setLoading] = useState(false)
  const toast = useToast()
  useEffect(() => {
    if (!q) {
      setResults(null)
      setLoading(false)
      return
    }
    let live = true
    setLoading(true)
    api
      .search(q)
      .then((data) => live && setResults({ q, data }))
      .catch((err) => live && toast.error(err))
      .finally(() => live && setLoading(false))
    return () => {
      live = false
    }
  }, [q, toast])
  return { results, loading }
}

export function SearchPage() {
  const { query } = useLocation()
  const initial = query.get('q') ?? ''
  const [text, setText] = useState(initial)
  const [q, setQ] = useState(initial.trim())
  const input = useRef<HTMLInputElement>(null)
  const { results, loading } = useSearch(q)
  const { status, isPlaying, togglePlay, start, pending } = usePlayer()

  useEffect(() => {
    const timer = setTimeout(() => {
      const trimmed = text.trim()
      setQ(trimmed)
      navigate(trimmed ? `/search?q=${encodeURIComponent(trimmed)}` : '/search', { replace: true })
    }, 300)
    return () => clearTimeout(timer)
  }, [text])

  const data = results?.data
  const tracks = data?.tracks?.items.filter(Boolean) ?? []
  const artists = data?.artists?.items.filter(Boolean) ?? []
  const albums = data?.albums?.items.filter(Boolean) ?? []
  const playlists = data?.playlists?.items.filter(Boolean) ?? []
  const empty = data && !tracks.length && !artists.length && !albums.length && !playlists.length
  const playUri = (uri: string) => (status?.context?.uri === uri ? togglePlay() : void start(uri, () => api.play({ uri })))

  return (
    <div className="px-3 pb-12 max-sm:px-2">
      <div className="sticky top-16 z-10 px-3 pb-2 pt-1 max-sm:top-14 max-sm:px-2">
        <label className="flex h-12 max-w-xl items-center gap-3 rounded-full bg-raised px-4 ring-white/30 transition focus-within:bg-hover focus-within:ring-2 hover:bg-hover">
          {loading ? <Loader2 className="size-5 shrink-0 animate-spin text-dim" /> : <Search className="size-5 shrink-0 text-dim" />}
          <input
            ref={input}
            autoFocus
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="What do you want to play?"
            aria-label="Search"
            className="min-w-0 flex-1 bg-transparent text-[15px] text-fg outline-none placeholder:text-faint"
          />
          {text && (
            <button
              type="button"
              aria-label="Clear search"
              onClick={() => {
                setText('')
                input.current?.focus()
              }}
              className="grid size-7 place-items-center rounded-full text-dim hover:text-fg"
            >
              <X className="size-5" />
            </button>
          )}
        </label>
      </div>

      {q && loading && !results && (
        <>
          <Section title="Songs">
            <RowsSkeleton count={5} />
          </Section>
          <Section title="Albums">
            <CardsSkeleton count={5} />
          </Section>
        </>
      )}
      {!q && <Message icon={<Search className="size-10" />} title="Search Spotify" body="Find songs, albums, artists and playlists to play on the lab speakers." />}
      {empty && <Message title={`No results for “${results?.q}”`} body="Check the spelling, or try fewer words." />}

      {tracks.length > 0 && (
        <Section title="Songs">
          <div className="px-0">
            <TrackList
              tracks={tracks}
              context="search"
              numbered={false}
              onPlay={(i) => void start(`search#${i}`, () => api.play({ uri: tracks[i].uri }))}
            />
          </div>
        </Section>
      )}
      {artists.length > 0 && (
        <Section title="Artists">
          <CardGrid>
            {artists.map((a) => (
              <MediaCard
                key={a.id}
                round
                title={a.name}
                subtitle="Artist"
                artwork={a.artwork}
                href={`/artist/${a.id}`}
                playing={status?.context?.uri === a.uri && isPlaying}
                pending={pending === a.uri}
                onPlay={() => playUri(a.uri)}
              />
            ))}
          </CardGrid>
        </Section>
      )}
      {albums.length > 0 && (
        <Section title="Albums">
          <CardGrid>
            {albums.map((a) => (
              <MediaCard
                key={a.id}
                title={a.name}
                subtitle={[year(a.release_date), byline(a)].filter(Boolean).join(' • ')}
                artwork={a.artwork}
                href={`/album/${a.id}`}
                playing={status?.context?.uri === a.uri && isPlaying}
                pending={pending === a.uri}
                onPlay={() => playUri(a.uri)}
              />
            ))}
          </CardGrid>
        </Section>
      )}
      {playlists.length > 0 && (
        <Section title="Playlists">
          <CardGrid>
            {playlists.map((p) => (
              <MediaCard
                key={p.id}
                title={p.name}
                subtitle={`By ${p.owner}`}
                artwork={p.artwork}
                playing={status?.context?.uri === p.uri && isPlaying}
                pending={pending === p.uri}
                onPlay={() => playUri(p.uri)}
              />
            ))}
          </CardGrid>
        </Section>
      )}
    </div>
  )
}
