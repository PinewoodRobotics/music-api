import type { CSSProperties } from 'react'

const GLYPH_EM = 0.6

export function fitTitle(title: string, maxCqw = 13): CSSProperties {
  const longest = Math.max(...title.split(/\s+/).map((w) => w.length), 1)
  const byWord = 96 / (longest * GLYPH_EM)
  const byLength = title.length > 40 ? 6 : title.length > 22 ? 9 : maxCqw
  return { fontSize: `clamp(1.6rem, ${Math.min(byWord, byLength).toFixed(2)}cqw, 6rem)` }
}
