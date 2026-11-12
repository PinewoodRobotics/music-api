import type { ReactNode } from 'react'
import ReactMarkdown, { type Components } from 'react-markdown'
import remarkGfm from 'remark-gfm'

function shortUrl(href: string) {
  try {
    const u = new URL(href)
    const rest = (u.pathname + u.search).replace(/\/$/, '')
    const host = u.host.replace(/^www\./, '')
    return rest.length > 24 ? `${host}${rest.slice(0, 20)}…` : host + rest
  } catch {
    return href
  }
}

const isBare = (href: string | undefined, children: ReactNode) => !!href && typeof children === 'string' && (children === href || `mailto:${children}` === href)

const components: Components = {
  h1: ({ children }) => <h3 className="mb-2 mt-4 font-display text-lg font-bold tracking-tight text-fg first:mt-0">{children}</h3>,
  h2: ({ children }) => <h3 className="mb-2 mt-4 font-display text-base font-bold tracking-tight text-fg first:mt-0">{children}</h3>,
  h3: ({ children }) => <h4 className="mb-1.5 mt-3 text-sm font-semibold text-fg first:mt-0">{children}</h4>,
  h4: ({ children }) => <h4 className="mb-1.5 mt-3 text-sm font-semibold text-fg first:mt-0">{children}</h4>,
  h5: ({ children }) => <h5 className="mb-1 mt-3 text-sm font-semibold text-dim first:mt-0">{children}</h5>,
  h6: ({ children }) => <h6 className="mb-1 mt-3 text-sm font-semibold text-dim first:mt-0">{children}</h6>,
  p: ({ children }) => <p className="my-2 first:mt-0 last:mb-0">{children}</p>,
  a: ({ href, children }) => (
    <a href={href} title={href} target="_blank" rel="noopener noreferrer" className="font-medium text-fg underline decoration-white/30 underline-offset-2 transition-colors hover:decoration-white">
      {isBare(href, children) && href && !href.startsWith('mailto:') ? shortUrl(href) : children}
    </a>
  ),
  strong: ({ children }) => <strong className="font-semibold text-fg">{children}</strong>,
  em: ({ children }) => <em className="italic">{children}</em>,
  del: ({ children }) => <del className="text-faint">{children}</del>,
  ul: ({ children }) => <ul className="my-2 list-disc space-y-1 pl-5 marker:text-faint first:mt-0 last:mb-0">{children}</ul>,
  ol: ({ children }) => <ol className="my-2 list-decimal space-y-1 pl-5 marker:text-faint first:mt-0 last:mb-0">{children}</ol>,
  blockquote: ({ children }) => <blockquote className="my-2 border-l-2 border-white/20 pl-3 text-dim first:mt-0 last:mb-0">{children}</blockquote>,
  code: ({ children }) => <code className="rounded bg-white/[0.08] px-1 py-0.5 font-mono text-[0.85em] text-fg">{children}</code>,
  pre: ({ children }) => (
    <pre className="scroll-thin my-2 overflow-x-auto rounded-md bg-black/40 p-3 text-[0.85em] leading-relaxed first:mt-0 last:mb-0 [&>code]:bg-transparent [&>code]:p-0">{children}</pre>
  ),
  table: ({ children }) => (
    <div className="scroll-thin my-2 overflow-x-auto first:mt-0 last:mb-0">
      <table className="w-full border-collapse text-left text-[0.9em]">{children}</table>
    </div>
  ),
  th: ({ children }) => <th className="border-b border-white/15 px-2 py-1.5 font-semibold text-fg">{children}</th>,
  td: ({ children }) => <td className="border-b border-white/[0.06] px-2 py-1.5">{children}</td>,
  hr: () => <hr className="my-3 border-white/10" />,
  img: ({ alt }) => <span className="text-faint">{alt ? `[${alt}]` : ''}</span>,
}

export function Markdown({ children, className = 'text-sm text-dim' }: { children: string; className?: string }) {
  return (
    <div className={`break-words leading-relaxed ${className}`}>
      <ReactMarkdown components={components} remarkPlugins={[remarkGfm]} skipHtml>
        {children}
      </ReactMarkdown>
    </div>
  )
}
