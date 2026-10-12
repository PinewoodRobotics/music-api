import type { LinkSource } from '../lib/links'

export function SourceIcon({ source, className = 'size-5' }: { source: LinkSource; className?: string }) {
  if (source === 'spotify')
    return (
      <svg viewBox="0 0 24 24" className={className} aria-hidden>
        <circle cx="12" cy="12" r="12" fill="#1ed760" />
        <path d="M6.2 9.4c3.9-1.2 8.3-.8 11.6 1.1M6.9 12.5c3.2-.9 6.6-.6 9.4 1M7.5 15.4c2.5-.7 5-.5 7.2.8" stroke="#000" strokeWidth="1.6" strokeLinecap="round" fill="none" />
      </svg>
    )
  if (source === 'youtube')
    return (
      <svg viewBox="0 0 24 24" className={className} aria-hidden>
        <rect y="3.5" width="24" height="17" rx="5" fill="#ff0033" />
        <path d="M9.8 8.6v6.8l5.9-3.4Z" fill="#fff" />
      </svg>
    )
  return (
    <svg viewBox="0 0 24 24" className={className} aria-hidden>
      <defs>
        <linearGradient id="am" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#fa5c73" />
          <stop offset="1" stopColor="#fa233b" />
        </linearGradient>
      </defs>
      <rect width="24" height="24" rx="6" fill="url(#am)" />
      <path d="M15.6 5.6v8.7a2 2 0 1 1-1.2-1.8V8.4l-5 1.1v6.1a2 2 0 1 1-1.2-1.8V7.6Z" fill="#fff" />
    </svg>
  )
}
