import { Link2, Loader2, Search, X } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { api, type SearchResults } from '../lib/api'
import { byline, year } from '../lib/format'
import { detectLink, looksLikeUrl } from '../lib/links'
import { isTouch } from '../lib/device'
import { navigate, useLocation } from '../lib/router'
import { MediaCard, Section } from '../components/MediaCard'
import { CardsSkeleton, RowsSkeleton } from '../components/Skeleton'
import { SourceIcon } from '../components/SourceIcon'
import { TrackList } from '../components/TrackList'
import { usePlayer } from '../state/player'
import { ErrorState, Message } from './Message'
import { CardSection, ShowAll } from './search/CardSection'
import { LinkResult } from './search/LinkResult'
import { pickTopResult } from './search/topResult'
import { TopResultCard } from './search/TopResultCard'

function useSearch(q: string) {
  const [results, setResults] = useState<{ q: string; data: SearchResults } | null>(null)
  const [failure, setFailure] = useState<{ q: string; error: unknown } | null>(null)
  const [loading, setLoading] = useState(false)
  const [attempt, setAttempt] = useState(0)
  useEffect(() => {
    if (!q) {
      setResults(null)
      setLoading(false)
      return
    }
    let live = true
    setLoading(true)
    setFailure(null)
    api
      .search(q)
      .then((data) => live && setResults({ q, data }))
      .catch((error) => live && setFailure({ q, error }))
      .finally(() => live && setLoading(false))
    return () => {
      live = false
    }
  }, [q, attempt])
  return { results, loading, failure: failure?.q === q ? failure.error : null, retry: () => setAttempt((n) => n + 1) }
}

function Results({ q, data }: { q: string; data: SearchResults }) {
  const { status, isPlaying, togglePlay, start, pending } = usePlayer()
  const [allSongs, setAllSongs] = useState(false)
  const tracks = data.tracks?.items.filter(Boolean) ?? []
  const artists = data.artists?.items.filter(Boolean) ?? []
  const albums = data.albums?.items.filter(Boolean) ?? []
  const playlists = data.playlists?.items.filter(Boolean) ?? []
  const top = pickTopResult(q, data)

  if (!top) return <Message title={`No results for “${q}”`} body="Check the spelling, or try fewer words." />

  const playing = (uri: string) => status?.context?.uri === uri && isPlaying
  const playUri = (uri: string) => (status?.context?.uri === uri ? togglePlay() : void start(uri, () => api.play({ uri, shuffle: false }), false))
  const songs = allSongs ? tracks : tracks.slice(0, 5)

  return (
    <>
      <div className="grid gap-x-6 px-3 max-sm:px-2 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
        <section className="mt-6 flex flex-col">
          <h2 className="mb-3 font-display text-2xl font-bold tracking-tight">Top result</h2>
          <TopResultCard top={top} />
        </section>
        {tracks.length > 0 && (
          <section className="mt-6 min-w-0">
            <div className="mb-3 flex items-end justify-between">
              <h2 className="font-display text-2xl font-bold tracking-tight">Songs</h2>
              {tracks.length > 5 && <ShowAll expanded={allSongs} onToggle={() => setAllSongs((v) => !v)} />}
            </div>
            <TrackList
              tracks={songs}
              context="search"
              numbered={false}
              header={false}
              showAlbum={allSongs}
              onPlay={(i) => void start(`search#${i}`, () => api.play({ uri: songs[i].uri }))}
            />
          </section>
        )}
      </div>
      <div className="px-3 max-sm:px-2">
        <CardSection
          title="Artists"
          cards={artists.map((a) => (
            <MediaCard
              key={a.id}
              round
              title={a.name}
              subtitle="Artist"
              artwork={a.artwork}
              href={`/artist/${a.id}`}
              playing={playing(a.uri)}
              pending={pending === a.uri}
              onPlay={() => playUri(a.uri)}
            />
          ))}
        />
        <CardSection
          title="Albums"
          cards={albums.map((a) => (
            <MediaCard
              key={a.id}
              title={a.name}
              subtitle={[year(a.release_date), byline(a)].filter(Boolean).join(', ')}
              artwork={a.artwork}
              href={`/album/${a.id}`}
              playing={playing(a.uri)}
              pending={pending === a.uri}
              onPlay={() => playUri(a.uri)}
            />
          ))}
        />
        <CardSection
          title="Playlists"
          cards={playlists.map((p) => (
            <MediaCard
              key={p.id}
              title={p.name}
              subtitle={p.owner}
              artwork={p.artwork}
              href={`/open?url=${encodeURIComponent(`https://open.spotify.com/playlist/${p.id}`)}`}
              playing={playing(p.uri)}
              pending={pending === p.uri}
              onPlay={() => playUri(p.uri)}
            />
          ))}
        />
      </div>
    </>
  )
}

function SearchSkeleton() {
  return (
    <div className="px-3 max-sm:px-2">
      <div className="grid gap-x-6 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
        <div className="mt-6 h-[236px] animate-pulse rounded-lg bg-white/[0.05]" />
        <Section title="Songs">
          <RowsSkeleton count={4} />
        </Section>
      </div>
      <Section title="Albums">
        <CardsSkeleton count={5} />
      </Section>
    </div>
  )
}

export function SearchPage() {
  const { query } = useLocation()
  const initial = query.get('q') ?? ''
  const [text, setText] = useState(initial)
  const [q, setQ] = useState(initial.trim())
  const input = useRef<HTMLInputElement>(null)
  const link = detectLink(q)
  const unsupported = !link && looksLikeUrl(q)
  const typedLink = detectLink(text)
  const { results, loading, failure, retry } = useSearch(link || unsupported ? '' : q)
  const searching = !!q && !link && !unsupported

  useEffect(() => {
    const timer = setTimeout(() => {
      const trimmed = text.trim()
      setQ(trimmed)
      navigate(trimmed ? `/search?q=${encodeURIComponent(trimmed)}` : '/search', { replace: true })
    }, 300)
    return () => clearTimeout(timer)
  }, [text])

  return (
    <div className="pb-12">
      <div className="sticky top-16 z-10 px-6 pb-2 pt-1 max-sm:top-14 max-sm:px-4">
        <label className="flex h-12 max-w-xl items-center gap-3 rounded-full bg-raised px-4 ring-white/30 transition focus-within:bg-hover focus-within:ring-2 hover:bg-hover">
          {typedLink ? (
            <SourceIcon source={typedLink.source} className="size-5 shrink-0" />
          ) : looksLikeUrl(text) ? (
            <Link2 className="size-5 shrink-0 text-dim" />
          ) : loading ? (
            <Loader2 className="size-5 shrink-0 animate-spin text-dim" />
          ) : (
            <Search className="size-5 shrink-0 text-dim" />
          )}
          <input
            ref={input}
            autoFocus={!isTouch()}
            enterKeyHint="search"
            autoCapitalize="off"
            autoCorrect="off"
            spellCheck={false}
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="Search, or paste a Spotify or Apple Music link"
            aria-label="Search"
            className="min-w-0 flex-1 bg-transparent text-base text-fg outline-none placeholder:text-faint"
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

      {!q && (
        <Message
          icon={<Search className="size-10" />}
          title="Search Spotify"
          body="Find songs, albums, artists and playlists, or paste a Spotify or Apple Music link."
        />
      )}
      {link && (
        <div className="mt-4">
          <LinkResult key={q} url={q} link={link} />
        </div>
      )}
      {unsupported && (
        <Message
          icon={<Link2 className="size-10" />}
          title="That link isn't supported"
          body="Paste a Spotify or Apple Music link to a song, album or playlist."
        />
      )}
      {searching && failure != null && <ErrorState title="Search didn't load" error={failure} onRetry={retry} />}
      {searching && failure == null && !results && loading && <SearchSkeleton />}
      {searching && failure == null && results && <Results key={results.q} q={results.q} data={results.data} />}
    </div>
  )
}
