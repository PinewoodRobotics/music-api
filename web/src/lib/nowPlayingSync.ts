import { useSyncExternalStore } from 'react'
import { storage } from './storage'

export type SyncState = 'off' | 'starting' | 'on' | 'interrupted'
export type SyncTarget = { key: string; durationMs: number; positionMs: number; playing: boolean }

const STORAGE_KEY = 'syncNowPlaying'
const SAMPLE_RATE = 8000
const MAX_SECONDS = 20 * 60
const DRIFT_S = 1.5
const END_SLACK_S = 0.3

export const mediaSessionSupported = false && typeof navigator !== 'undefined' && 'mediaSession' in navigator

let state: SyncState = mediaSessionSupported && storage.get(STORAGE_KEY) === '1' ? 'starting' : 'off'
let error: string | null = null
let audio: HTMLAudioElement | null = null
let primerUrl: string | null = null
let trackUrl: string | null = null
let trackKey: string | null = null
let target: SyncTarget | null = null
let ourPause = false
let ourSeek = false
let unlocking = false
let onSystemSeek: ((ms: number) => void) | null = null
const playingListeners = new Set<() => void>()
const listeners = new Set<() => void>()

function emit() {
  listeners.forEach((l) => l())
}

function setState(next: SyncState, nextError: string | null = null) {
  if (next === state && nextError === error) return
  state = next
  error = nextError
  emit()
}

function silentWavUrl(seconds: number) {
  const samples = Math.max(1, Math.round(seconds * SAMPLE_RATE))
  const bytes = new Uint8Array(44 + samples)
  const view = new DataView(bytes.buffer)
  const text = (offset: number, value: string) => [...value].forEach((c, i) => (bytes[offset + i] = c.charCodeAt(0)))
  text(0, 'RIFF')
  view.setUint32(4, 36 + samples, true)
  text(8, 'WAVE')
  text(12, 'fmt ')
  view.setUint32(16, 16, true)
  view.setUint16(20, 1, true)
  view.setUint16(22, 1, true)
  view.setUint32(24, SAMPLE_RATE, true)
  view.setUint32(28, SAMPLE_RATE, true)
  view.setUint16(32, 1, true)
  view.setUint16(34, 8, true)
  text(36, 'data')
  view.setUint32(40, samples, true)
  bytes.fill(0x80, 44)
  return URL.createObjectURL(new Blob([bytes], { type: 'audio/wav' }))
}

const atEnd = (el: HTMLAudioElement) => el.ended || (el.duration > 0 && el.currentTime >= el.duration - END_SLACK_S)

function element() {
  if (audio) return audio
  const el = new Audio()
  el.preload = 'auto'
  el.setAttribute('playsinline', '')
  el.addEventListener('pause', () => {
    if (ourPause) {
      ourPause = false
      return
    }
    if (state === 'on' && target?.playing && !atEnd(el)) setState('interrupted')
  })
  el.addEventListener('seeking', () => {
    if (ourSeek) return
    if (state === 'on' && trackKey && el.src === trackUrl) onSystemSeek?.(el.currentTime * 1000)
  })
  el.addEventListener('playing', () => playingListeners.forEach((l) => l()))
  el.addEventListener('seeked', () => {
    ourSeek = false
  })
  audio = el
  return el
}

function seekTo(el: HTMLAudioElement, seconds: number) {
  if (!(el.duration > 0) || seconds >= el.duration) return
  ourSeek = true
  el.currentTime = seconds
}

function play(el: HTMLAudioElement) {
  if (!el.paused || atEnd(el)) return
  el.play().catch((err: unknown) => setState('interrupted', describe(err)))
}

function pause(el: HTMLAudioElement) {
  if (el.paused) return
  ourPause = true
  el.pause()
}

function describe(err: unknown) {
  return err instanceof Error ? err.message || err.name : String(err)
}

function loadTrack(el: HTMLAudioElement, next: SyncTarget) {
  const previous = trackUrl
  trackKey = next.key
  trackUrl = silentWavUrl(Math.min(MAX_SECONDS, Math.max(1, next.durationMs / 1000)))
  ourPause = !el.paused
  el.src = trackUrl
  el.addEventListener(
    'loadedmetadata',
    () => {
      ourPause = false
      if (!target || target.key !== trackKey) return
      seekTo(el, target.positionMs / 1000)
      if (target.playing) play(el)
    },
    { once: true },
  )
  el.load()
  if (previous) URL.revokeObjectURL(previous)
}

function apply() {
  const el = audio
  if (state !== 'on' || unlocking || !el || !target) return
  if (target.key !== trackKey) return loadTrack(el, target)
  if (el.readyState >= 1) {
    const wanted = target.positionMs / 1000
    if (Math.abs(el.currentTime - wanted) > DRIFT_S) seekTo(el, wanted)
  }
  if (target.playing) play(el)
  else pause(el)
}

function start() {
  const el = element()
  if (!primerUrl) primerUrl = silentWavUrl(2)
  if (!el.src) el.src = primerUrl
  unlocking = true
  setState('on')
  el.play().then(
    () => {
      unlocking = false
      trackKey = null
      apply()
    },
    (err: unknown) => {
      unlocking = false
      storage.set(STORAGE_KEY, null)
      setState('off', `Couldn't start: ${describe(err)}`)
    },
  )
}

function armGestureStart() {
  const go = () => {
    window.removeEventListener('pointerdown', go, true)
    window.removeEventListener('keydown', go, true)
    if (state === 'starting') start()
  }
  window.addEventListener('pointerdown', go, true)
  window.addEventListener('keydown', go, true)
}

if (state === 'starting') armGestureStart()

export const nowPlayingSync = {
  enable() {
    storage.set(STORAGE_KEY, '1')
    start()
  },
  disable() {
    storage.set(STORAGE_KEY, null)
    if (audio) pause(audio)
    setState('off')
  },
  sync(next: SyncTarget | null) {
    target = next
    if (!next && audio) pause(audio)
    else apply()
  },
  onSeek(handler: ((ms: number) => void) | null) {
    onSystemSeek = handler
  },
  onPlaying(listener: () => void) {
    playingListeners.add(listener)
    return () => void playingListeners.delete(listener)
  },
}

const subscribe = (listener: () => void) => {
  listeners.add(listener)
  return () => void listeners.delete(listener)
}

export function useSyncState() {
  const current = useSyncExternalStore(subscribe, () => state)
  const message = useSyncExternalStore(subscribe, () => error)
  return { state: current, error: message }
}
