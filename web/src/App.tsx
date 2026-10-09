import { ChevronLeft, ChevronRight, Loader2 } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { AccountMenu } from './components/AccountMenu'
import { BrandMark } from './components/Brand'
import { MediaSessionBridge } from './components/MediaSessionBridge'
import { MobileNav } from './components/MobileNav'
import { Button } from './components/Modal'
import { NowPlayingBar } from './components/NowPlayingBar'
import { NowPlayingView } from './components/NowPlayingView'
import { Dialogs } from './components/PlaylistDialogs'
import { SidePanel } from './components/SidePanel'
import { Sidebar } from './components/Sidebar'
import { Toasts } from './components/Toasts'
import { usePalette } from './lib/color'
import { matchRoute, navigate, useLocation, type Route } from './lib/router'
import { focusSearch } from './lib/searchFocus'
import { AlbumPage } from './pages/AlbumPage'
import { ArtistPage } from './pages/ArtistPage'
import { PlaylistsPage } from './pages/PlaylistsPage'
import { OpenLinkPage } from './pages/OpenLinkPage'
import { Message } from './pages/Message'
import { PlaylistPage } from './pages/PlaylistPage'
import { SearchPage } from './pages/SearchPage'
import { SignIn } from './pages/SignIn'
import { PlayerProvider, usePlayer } from './state/player'
import { SessionProvider, useSession } from './state/session'
import { ToastProvider } from './state/toast'
import { UIProvider } from './state/ui'

export default function App() {
  return (
    <ToastProvider>
      <SessionProvider>
        <Root />
        <Toasts />
      </SessionProvider>
    </ToastProvider>
  )
}

function Root() {
  const { state, retry } = useSession()
  if (state.status === 'loading')
    return (
      <div className="grid min-h-dvh place-items-center bg-black">
        <Loader2 className="size-7 animate-spin text-faint" />
      </div>
    )
  if (state.status === 'signedOut') return <SignIn />
  if (state.status === 'error')
    return (
      <div className="grid min-h-dvh place-items-center bg-black">
        <Message title="Can't reach the lab speakers" body={state.message} action={<Button onClick={retry}>Try again</Button>} />
      </div>
    )
  return (
    <UIProvider>
      <PlayerProvider>
        <Shell />
      </PlayerProvider>
    </UIProvider>
  )
}

function AmbientTheme() {
  const { status } = usePlayer()
  const palette = usePalette(status?.track?.artwork)
  useEffect(() => {
    const root = document.documentElement.style
    root.setProperty('--accent', palette.accent)
    root.setProperty('--ink', palette.ink)
    root.setProperty('--ambient', palette.ambient)
    root.setProperty('--glow', palette.glow)
  }, [palette])
  return null
}

function useShortcuts() {
  const { togglePlay, seekBy } = usePlayer()
  useEffect(() => {
    const typing = (t: EventTarget | null) =>
      t instanceof HTMLElement && (t.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(t.tagName) || t.getAttribute('role') === 'slider')
    const blocked = () => !!document.querySelector('[aria-modal="true"][role="dialog"]:not([aria-label="Now Playing"])')
    const down = (e: KeyboardEvent) => {
      const commandK = e.key.toLowerCase() === 'k' && (e.metaKey || e.ctrlKey) && !e.altKey
      const slash = e.key === '/' && !e.metaKey && !e.ctrlKey && !e.altKey && !typing(e.target)
      if ((commandK || slash) && !blocked()) {
        e.preventDefault()
        if (!focusSearch()) {
          navigate('/search')
          setTimeout(focusSearch, 50)
        }
        return
      }
      if (e.metaKey || e.ctrlKey || e.altKey || typing(e.target) || blocked()) return
      if (e.code === 'Space') {
        e.preventDefault()
        if (!e.repeat) togglePlay()
      } else if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
        e.preventDefault()
        seekBy(e.key === 'ArrowLeft' ? -10000 : 10000)
      }
    }
    const up = (e: KeyboardEvent) => {
      if (e.code === 'Space' && !typing(e.target)) e.preventDefault()
    }
    window.addEventListener('keydown', down)
    window.addEventListener('keyup', up)
    return () => {
      window.removeEventListener('keydown', down)
      window.removeEventListener('keyup', up)
    }
  }, [togglePlay, seekBy])
}

function Page({ route }: { route: Route }) {
  switch (route.name) {
    case 'playlists':
      return <PlaylistsPage />
    case 'search':
      return <SearchPage />
    case 'playlist':
      return <PlaylistPage key={route.id} id={route.id} />
    case 'album':
      return <AlbumPage key={route.id} id={route.id} />
    case 'artist':
      return <ArtistPage key={route.id} id={route.id} />
    case 'open':
      return <OpenLinkPage key={route.url} url={route.url} />
    case 'notFound':
      return <Message title="Page not found" action={<Button onClick={() => navigate('/')}>Go home</Button>} />
  }
}

function TopBar({ scrolled }: { scrolled: boolean }) {
  return (
    <div
      className={`sticky top-0 z-20 flex h-16 items-center gap-2 px-4 transition-colors duration-300 max-sm:h-14 ${
        scrolled ? 'bg-panel/90 backdrop-blur-md' : ''
      }`}
    >
      <div className="flex items-center gap-2 max-md:hidden">
        <button type="button" aria-label="Go back" onClick={() => history.back()} className="grid size-8 place-items-center rounded-full bg-black/50 text-dim hover:text-fg">
          <ChevronLeft className="size-5" />
        </button>
        <button type="button" aria-label="Go forward" onClick={() => history.forward()} className="grid size-8 place-items-center rounded-full bg-black/50 text-dim hover:text-fg">
          <ChevronRight className="size-5" />
        </button>
      </div>
      <div className="flex items-center gap-2.5 md:hidden">
        <BrandMark className="size-7" />
        <span className="font-display text-base font-bold tracking-tight text-fg">Robotics Music</span>
      </div>
      <div className="flex-1" />
      <AccountMenu />
    </div>
  )
}

function Shell() {
  const { path, query } = useLocation()
  const route = matchRoute(path, query)
  const main = useRef<HTMLElement>(null)
  const [scrolled, setScrolled] = useState(false)
  useShortcuts()

  useEffect(() => {
    main.current?.scrollTo(0, 0)
  }, [path])

  return (
    <div data-app-shell className="flex h-dvh flex-col overflow-hidden bg-black pt-[env(safe-area-inset-top)] md:pt-0">
      <AmbientTheme />
      <MediaSessionBridge />
      <div className="flex min-h-0 flex-1 gap-2 md:p-2 md:pb-0">
        <Sidebar />
        <main
          ref={main}
          onScroll={(e) => setScrolled(e.currentTarget.scrollTop > 24)}
          className="scroll-thin relative min-w-0 flex-1 overflow-y-auto overflow-x-hidden bg-panel md:rounded-lg"
        >
          <TopBar scrolled={scrolled} />
          <Page route={route} />
        </main>
        <SidePanel />
      </div>
      <NowPlayingBar />
      <MobileNav />
      <NowPlayingView />
      <Dialogs />
    </div>
  )
}
