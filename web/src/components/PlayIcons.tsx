import { useEffect, useState } from 'react'
import { api } from '../api'

// One shared audio element: starting one phrase stops the previous. A phrase plays from its start to its end in the stored sound of the clip, original or cleaned.
let el: HTMLAudioElement | null = null
let stopAt = 0
let now: string | null = null
const subs = new Set<() => void>()
const emit = (k: string | null) => { now = k; subs.forEach(f => f()) }

function play(url: string, key: string, t0: number, t1: number) {
  if (!el) { el = new Audio(); el.addEventListener('timeupdate', () => { if (el && el.currentTime >= stopAt) { el.pause(); emit(null) } }); el.addEventListener('ended', () => emit(null)); el.addEventListener('pause', () => { if (el && el.currentTime < stopAt) emit(null) }) }
  if (now === key) { el.pause(); emit(null); return }
  stopAt = t1
  const go = () => { if (!el) return; el.currentTime = t0; void el.play().then(() => emit(key)).catch(() => emit(null)) }
  if (!el.src.endsWith(url)) { el.src = url; el.addEventListener('loadedmetadata', go, { once: true }); el.load() } else go()
}

export default function PlayIcons({ folder, clip, t0, t1, original, clean }: { folder: string; clip: string; t0: number; t1: number; original: boolean; clean: boolean }) {
  const [, force] = useState(0)
  useEffect(() => { const f = () => force(n => n + 1); subs.add(f); return () => { subs.delete(f) } }, [])
  const btn = (kind: 'original' | 'clean', ok: boolean, label: string) => {
    const key = `${clip}|${kind}|${t0}`, on = now === key
    return (
      <button type="button" disabled={!ok} title={ok ? `play ${label} sound of this phrase` : kind === 'clean' ? 'the cleaned sound is not made yet' : 'the sound is not extracted yet'} onClick={e => { e.stopPropagation(); play(api.clipAudioUrl(folder, clip, kind), key, t0, t1) }}
        className={`mr-0.5 rounded border px-1 align-baseline text-[10px] leading-4 disabled:opacity-30 ${on ? 'border-emerald-600 bg-emerald-600 text-white' : 'border-stone-300 text-stone-600 hover:border-emerald-600 dark:border-stone-600 dark:text-stone-300'}`}>{on ? '■' : '▶'} {label}</button>)
  }
  return <span className="mr-1 whitespace-nowrap">{btn('original', original, 'orig')}{btn('clean', clean, 'clean')}</span>
}
