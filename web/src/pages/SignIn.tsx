import { useEffect, useState } from 'react'
import { BrandMark } from '../components/Brand'
import { SlackLogo } from '../components/SlackLogo'

const BARS = [0.35, 0.6, 0.9, 0.55, 0.75, 1, 0.65, 0.4, 0.8, 0.5, 0.95, 0.7, 0.45, 0.85, 0.6, 0.3, 0.7, 0.9, 0.5, 0.65]

type Methods = { slack: boolean; google: boolean }

function useMethods() {
  const [methods, setMethods] = useState<Methods | null>(null)
  useEffect(() => {
    let live = true
    fetch('/auth/methods', { credentials: 'same-origin' })
      .then((r) => (r.ok ? r.json() : null))
      .then((m: Methods | null) => live && setMethods(m && typeof m.google === 'boolean' ? m : { slack: true, google: false }))
      .catch(() => live && setMethods({ slack: true, google: false }))
    return () => {
      live = false
    }
  }, [])
  return methods
}

function GoogleLogo() {
  return (
    <svg viewBox="0 0 48 48" className="size-5" aria-hidden>
      <path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z" />
      <path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z" />
      <path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z" />
      <path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z" />
    </svg>
  )
}

const loginHref = (provider: 'google' | 'slack') => `/auth/${provider}/login?next=${encodeURIComponent(location.pathname + location.search)}`

function GoogleButton() {
  return (
    <a
      href={loginHref('google')}
      className="inline-flex h-12 w-full items-center justify-center gap-3 rounded-full border border-[#747775] bg-white px-6 text-[15px] font-medium text-[#1f1f1f] transition-transform hover:scale-[1.02] active:scale-[0.98]"
    >
      <GoogleLogo />
      Sign in with Google
    </a>
  )
}

function SlackButton({ secondary = false }: { secondary?: boolean }) {
  return (
    <a
      href={loginHref('slack')}
      className={`inline-flex h-12 w-full items-center justify-center gap-3 rounded-full px-6 text-[15px] font-semibold transition-transform hover:scale-[1.02] active:scale-[0.98] ${
        secondary ? 'text-fg ring-1 ring-white/25 hover:bg-white/[0.06]' : 'bg-white text-black'
      }`}
    >
      <SlackLogo className="size-5" />
      Sign in with Slack
    </a>
  )
}

function Buttons({ methods }: { methods: Methods | null }) {
  if (!methods) return <div className="h-[7.5rem] w-full" aria-busy="true" />
  if (methods.google && methods.slack)
    return (
      <div className="w-full">
        <GoogleButton />
        <p className="mt-3 text-xs text-dim">Use your @pinewood.edu account</p>
        <div className="my-5 flex items-center gap-3 text-xs text-faint">
          <span className="h-px flex-1 bg-white/10" />
          or
          <span className="h-px flex-1 bg-white/10" />
        </div>
        <SlackButton secondary />
        <p className="mt-3 text-xs text-faint">For members of the Pinewood Robotics Slack.</p>
      </div>
    )
  if (methods.google)
    return (
      <div className="w-full">
        <GoogleButton />
        <p className="mt-3 text-xs text-dim">Use your @pinewood.edu account</p>
      </div>
    )
  if (methods.slack)
    return (
      <div className="w-full">
        <SlackButton />
        <p className="mt-5 text-xs text-faint">For members of the Pinewood Robotics Slack.</p>
      </div>
    )
  return <p className="text-sm text-dim">Sign-in isn't set up on this server yet.</p>
}

export function SignIn() {
  const methods = useMethods()
  return (
    <div className="relative grid min-h-dvh place-items-center overflow-hidden bg-black px-6">
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(ellipse_80%_60%_at_50%_110%,hsl(36_70%_28%/.55),transparent_70%)]" />
      <div className="pointer-events-none absolute inset-x-0 bottom-0 flex h-[28vh] items-end justify-center gap-[1.2vw] px-[4vw] opacity-[0.16]" aria-hidden>
        {BARS.map((h, i) => (
          <span
            key={i}
            className="eq-bar w-full max-w-10 rounded-t-full bg-accent"
            style={{ height: `${h * 100}%`, animationDuration: `${2.4 + (i % 5) * 0.45}s`, animationDelay: `${-i * 0.37}s` }}
          />
        ))}
      </div>
      <main className="animate-rise relative flex w-full max-w-sm flex-col items-center text-center">
        <BrandMark className="size-16" />
        <h1 className="mt-8 font-display text-5xl font-extrabold tracking-[-0.04em]">Robotics Music</h1>
        <p className="mt-2 font-display text-lg font-semibold text-accent">So Musical!!</p>
        <p className="mt-4 text-[15px] leading-relaxed text-dim">Pick what plays on the lab speakers, queue up songs and build playlists together.</p>
        <div className="mt-10 w-full">
          <Buttons methods={methods} />
        </div>
      </main>
    </div>
  )
}
