import { BrandMark } from '../components/Brand'

function SlackLogo() {
  return (
    <svg viewBox="0 0 122.8 122.8" className="size-5" aria-hidden>
      <path d="M25.8 77.6a12.9 12.9 0 1 1-12.9-12.9h12.9v12.9zm6.5 0a12.9 12.9 0 0 1 25.8 0v32.3a12.9 12.9 0 1 1-25.8 0V77.6z" fill="#e01e5a" />
      <path d="M45.2 25.8a12.9 12.9 0 1 1 12.9-12.9v12.9H45.2zm0 6.5a12.9 12.9 0 0 1 0 25.8H12.9a12.9 12.9 0 1 1 0-25.8h32.3z" fill="#36c5f0" />
      <path d="M97 45.2a12.9 12.9 0 1 1 12.9 12.9H97V45.2zm-6.5 0a12.9 12.9 0 0 1-25.8 0V12.9a12.9 12.9 0 1 1 25.8 0v32.3z" fill="#2eb67d" />
      <path d="M77.6 97a12.9 12.9 0 1 1-12.9 12.9V97h12.9zm0-6.5a12.9 12.9 0 0 1 0-25.8h32.3a12.9 12.9 0 1 1 0 25.8H77.6z" fill="#ecb22e" />
    </svg>
  )
}

const BARS = [0.35, 0.6, 0.9, 0.55, 0.75, 1, 0.65, 0.4, 0.8, 0.5, 0.95, 0.7, 0.45, 0.85, 0.6, 0.3, 0.7, 0.9, 0.5, 0.65]

export function SignIn() {
  const next = location.pathname + location.search
  const href = `/auth/slack/login?next=${encodeURIComponent(next)}`
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
        <a
          href={href}
          className="mt-10 inline-flex h-12 w-full items-center justify-center gap-3 rounded-full bg-white px-6 text-[15px] font-semibold text-black transition-transform hover:scale-[1.02] active:scale-[0.98]"
        >
          <SlackLogo />
          Sign in with Slack
        </a>
        <p className="mt-5 text-xs text-faint">For members of the Pinewood Robotics Slack.</p>
      </main>
    </div>
  )
}
