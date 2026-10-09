import { ListMusic, Maximize2, MicVocal, Search } from 'lucide-react'
import type { ReactNode } from 'react'
import { api } from '../lib/api'
import { byline, idFromUri } from '../lib/format'
import { navigate } from '../lib/router'
import { Artwork } from '../components/Artwork'
import { BigPlayButton } from '../components/CollectionHeader'
import { EmptyPlaylists } from '../components/EmptyPlaylists'
import { Equalizer } from '../components/Equalizer'
import { Link } from '../components/Link'
import { CardGrid, MediaCard, Section } from '../components/MediaCard'
import { Button } from '../components/Modal'
import { creatorLine } from '../components/PlaylistRow'
import { usePlayer } from '../state/player'
import { useSession } from '../state/session'
import { useUI } from '../state/ui'
import { CardsSkeleton } from '../components/Skeleton'

function Pill({ icon, label, onClick, active }: { icon: ReactNode; label: string; onClick: () => void; active?: boolean }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`inline-flex h-9 items-center gap-2 rounded-full px-4 text-sm font-semibold transition-colors [&>svg]:size-4 ${
        active ? 'bg-white text-black' : 'bg-white/10 text-fg hover:bg-white/20'
      }`}
    >
      {icon}
      {label}
    </button>
  )
}

function Hero() {
  const { status, isPlaying, togglePlay } = usePlayer()
  const { setExpanded, panel, togglePanel } = useUI()
  const track = status?.track
  const device = status?.device?.name ?? 'Lab Speakers'
  const context = status?.context
  const contextHref =
    context && ['playlist', 'album', 'artist'].includes(context.type) ? `/${context.type}/${idFromUri(context.uri)}` : null

  return (
    <section className="relative">
      <div className="pointer-events-none absolute inset-x-0 -top-16 h-[calc(100%+12rem)] bg-[linear-gradient(to_bottom,var(--glow),transparent)] transition-[background] duration-700" />
      {track ? (
        <div className="relative flex items-end gap-8 px-6 pb-4 pt-4 max-sm:flex-col max-sm:items-start max-sm:gap-5 max-sm:px-4">
          <button type="button" onClick={() => setExpanded(true)} className="group relative shrink-0 max-sm:mx-auto" aria-label="Open Now Playing">
            <Artwork src={track.artwork} className="size-[clamp(180px,22vw,260px)] shadow-[0_24px_60px_rgba(0,0,0,0.6)] max-sm:size-[min(70vw,280px)]" />
            <span className="absolute inset-0 grid place-items-center rounded-[6px] bg-black/40 opacity-0 transition-opacity group-hover:opacity-100">
              <Maximize2 className="size-8" />
            </span>
          </button>
          <div className="min-w-0 flex-1 pb-1">
            <div className="flex items-center gap-2 text-sm font-medium text-white/80">
              <Equalizer playing={isPlaying} />
              {isPlaying ? `Playing on ${device}` : `Paused on ${device}`}
            </div>
            <h1 className="mt-2 line-clamp-2 pb-[0.08em] font-display text-[clamp(2rem,5vw,4.5rem)] font-extrabold leading-[0.98] tracking-[-0.04em]">
              {track.name}
            </h1>
            <p className="mt-2 truncate text-lg text-white/75">
              {byline(track)}
              {context?.name && (
                <span className="text-white/55">
                  {' '}
                  from{' '}
                  {contextHref ? (
                    <Link href={contextHref} className="text-white/80 hover:underline">
                      {context.name}
                    </Link>
                  ) : (
                    context.name
                  )}
                </span>
              )}
            </p>
            <div className="mt-6 flex flex-wrap items-center gap-3">
              <BigPlayButton playing={isPlaying} label={isPlaying ? 'Pause' : 'Play'} onClick={togglePlay} />
              <Pill icon={<MicVocal />} label="Lyrics" active={panel === 'lyrics'} onClick={() => togglePanel('lyrics')} />
              <Pill icon={<ListMusic />} label="Up next" active={panel === 'queue'} onClick={() => togglePanel('queue')} />
            </div>
          </div>
        </div>
      ) : (
        <div className="relative px-6 pb-6 pt-10 max-sm:px-4">
          <div className="text-sm font-medium text-white/70">{device}</div>
          <h1 className="mt-2 font-display text-[clamp(2.25rem,5vw,4.5rem)] font-extrabold leading-[0.98] tracking-[-0.04em]">
            The speakers are quiet.
          </h1>
          <p className="mt-3 max-w-md text-white/70">Start a playlist below or search for something to play.</p>
          <Button className="mt-6" onClick={() => navigate('/search')}>
            <Search className="size-4" />
            Search
          </Button>
        </div>
      )}
    </section>
  )
}

export function HomePage() {
  const { playlists } = useSession()
  const { status, isPlaying, togglePlay, start, pending } = usePlayer()
  const sorted = [...(playlists ?? [])].sort((a, b) => (b.created ?? '').localeCompare(a.created ?? ''))
  return (
    <div className="pb-12">
      <Hero />
      <div className="px-3 max-sm:px-2">
        <Section title="Playlists">
          {playlists === null ? (
            <CardsSkeleton count={4} />
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
                    subtitle={creatorLine(p)}
                    artwork={p.artwork}
                    href={`/playlist/${p.id}`}
                    playing={current && isPlaying}
                    pending={pending === p.uri}
                    onPlay={() => (current ? togglePlay() : void start(p.uri, () => api.playPlaylist(p.id)))}
                  />
                )
              })}
            </CardGrid>
          )}
        </Section>
      </div>
    </div>
  )
}
