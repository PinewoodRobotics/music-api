import { useEffect, useState } from 'react'

export type Palette = { accent: string; ink: string; ambient: string; glow: string }

export const DEFAULT_PALETTE: Palette = {
  accent: 'hsl(36 79% 57%)',
  ink: '#1a1206',
  ambient: 'hsl(30 18% 13%)',
  glow: 'hsl(36 60% 30%)',
}

const cache = new Map<string, Palette>()

function rgbToHsl(r: number, g: number, b: number): [number, number, number] {
  r /= 255
  g /= 255
  b /= 255
  const max = Math.max(r, g, b)
  const min = Math.min(r, g, b)
  const l = (max + min) / 2
  if (max === min) return [0, 0, l]
  const d = max - min
  const s = l > 0.5 ? d / (2 - max - min) : d / (max + min)
  const h = max === r ? (g - b) / d + (g < b ? 6 : 0) : max === g ? (b - r) / d + 2 : (r - g) / d + 4
  return [h * 60, s, l]
}

const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v))

function paletteFrom(pixels: Uint8ClampedArray): Palette {
  const bins = Array.from({ length: 12 }, () => ({ score: 0, h: 0, s: 0, l: 0, n: 0 }))
  let grey = { l: 0, n: 0 }
  for (let i = 0; i < pixels.length; i += 4) {
    const [h, s, l] = rgbToHsl(pixels[i], pixels[i + 1], pixels[i + 2])
    if (l < 0.08 || l > 0.95) continue
    grey = { l: grey.l + l, n: grey.n + 1 }
    if (s < 0.18) continue
    const bin = bins[Math.floor(h / 30) % 12]
    const weight = s * (1 - Math.abs(l - 0.5))
    bin.score += weight
    bin.h += h * weight
    bin.s += s * weight
    bin.l += l * weight
    bin.n += weight
  }
  const best = bins.reduce((a, b) => (b.score > a.score ? b : a))
  if (best.score < pixels.length / 4 / 40) {
    return { accent: 'hsl(0 0% 88%)', ink: '#111', ambient: 'hsl(0 0% 12%)', glow: 'hsl(0 0% 26%)' }
  }
  const h = Math.round(best.h / best.n)
  const s = clamp(best.s / best.n, 0.35, 0.85)
  return {
    accent: `hsl(${h} ${Math.round(s * 100)}% 64%)`,
    ink: '#0d0d0d',
    ambient: `hsl(${h} ${Math.round(s * 45)}% 13%)`,
    glow: `hsl(${h} ${Math.round(s * 70)}% 32%)`,
  }
}

export function extractPalette(url: string): Promise<Palette> {
  const hit = cache.get(url)
  if (hit) return Promise.resolve(hit)
  return new Promise((resolve) => {
    const img = new Image()
    img.crossOrigin = 'anonymous'
    img.onload = () => {
      try {
        const canvas = document.createElement('canvas')
        canvas.width = canvas.height = 28
        const ctx = canvas.getContext('2d', { willReadFrequently: true })
        if (!ctx) return resolve(DEFAULT_PALETTE)
        ctx.drawImage(img, 0, 0, 28, 28)
        const palette = paletteFrom(ctx.getImageData(0, 0, 28, 28).data)
        cache.set(url, palette)
        resolve(palette)
      } catch {
        resolve(DEFAULT_PALETTE)
      }
    }
    img.onerror = () => resolve(DEFAULT_PALETTE)
    img.src = url
  })
}

export function usePalette(url: string | null | undefined) {
  const [palette, setPalette] = useState<Palette>(() => (url && cache.get(url)) || DEFAULT_PALETTE)
  useEffect(() => {
    let live = true
    if (!url) setPalette(DEFAULT_PALETTE)
    else extractPalette(url).then((p) => live && setPalette(p))
    return () => {
      live = false
    }
  }, [url])
  return palette
}

const meshCache = new Map<string, string[]>()
export const DEFAULT_MESH = ['hsl(36 55% 45%)', 'hsl(18 50% 38%)', 'hsl(48 45% 52%)', 'hsl(28 40% 30%)']

function meshFrom(pixels: Uint8ClampedArray): string[] {
  const bins = Array.from({ length: 12 }, () => ({ score: 0, h: 0, s: 0, l: 0, n: 0 }))
  let lightSum = 0
  let count = 0
  for (let i = 0; i < pixels.length; i += 4) {
    const [h, s, l] = rgbToHsl(pixels[i], pixels[i + 1], pixels[i + 2])
    lightSum += l
    count++
    if (s < 0.15 || l < 0.08 || l > 0.95) continue
    const bin = bins[Math.floor(h / 30) % 12]
    const weight = s * (1 - Math.abs(l - 0.5)) + 0.05
    bin.score += weight
    bin.h += h * weight
    bin.s += s * weight
    bin.l += l * weight
    bin.n += weight
  }
  const ranked = bins.filter((b) => b.n > 0 && b.score > count / 400).sort((a, b) => b.score - a.score)
  if (!ranked.length) {
    const l = Math.round(clamp(lightSum / Math.max(count, 1), 0.25, 0.5) * 100)
    return [`hsl(230 8% ${l}%)`, `hsl(230 6% ${l - 8}%)`, `hsl(230 10% ${l + 8}%)`, `hsl(230 5% ${l - 14}%)`]
  }
  const colors = ranked.slice(0, 4).map((b) => {
    const h = Math.round(b.h / b.n)
    const s = Math.round(clamp(b.s / b.n, 0.3, 0.72) * 100)
    const l = Math.round(clamp(b.l / b.n, 0.36, 0.6) * 100)
    return { h, s, l }
  })
  while (colors.length < 4) {
    const base = colors[colors.length % Math.max(1, ranked.length)] ?? colors[0]
    colors.push({ h: (base.h + 18 * colors.length) % 360, s: base.s, l: clamp(base.l + (colors.length % 2 ? -10 : 8), 28, 62) })
  }
  return colors.map(({ h, s, l }) => `hsl(${h} ${s}% ${l}%)`)
}

export function useMesh(url: string | null | undefined) {
  const [mesh, setMesh] = useState<string[]>(() => (url && meshCache.get(url)) || DEFAULT_MESH)
  useEffect(() => {
    if (!url) return setMesh(DEFAULT_MESH)
    const hit = meshCache.get(url)
    if (hit) return setMesh(hit)
    let live = true
    const img = new Image()
    img.crossOrigin = 'anonymous'
    img.onload = () => {
      try {
        const canvas = document.createElement('canvas')
        canvas.width = canvas.height = 32
        const ctx = canvas.getContext('2d', { willReadFrequently: true })
        if (!ctx) return
        ctx.drawImage(img, 0, 0, 32, 32)
        const colors = meshFrom(ctx.getImageData(0, 0, 32, 32).data)
        meshCache.set(url, colors)
        if (live) setMesh(colors)
      } catch {
        return
      }
    }
    img.src = url
    return () => {
      live = false
    }
  }, [url])
  return mesh
}
