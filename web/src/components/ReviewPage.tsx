import { useEffect, useRef, useState } from 'react'
import { api, type ReviewItem } from '../api'
import { usePoll } from '../usePoll'
import { diffPhrase } from '../phraseDiff'
import { PanelSkeleton } from './Skeleton'

const PAGE = 20
const short = (id: string) => id.replace(/^CAM_/, '').replace(/_D$/, '').replace(/^(\d{8})(\d{6})_/, (_, d, t) => `${d.slice(6)}/${d.slice(4, 6)} ${t.slice(0, 2)}:${t.slice(2, 4)} · `)
const mmss = (s: number) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`
const shownText = (it: ReviewItem) => it.words.map(w => w.w.trim()).filter(Boolean).join(' ')

// One shared audio element: playing a phrase stops the previous one. The phrase plays from its start to its end in the clip's stored sound at the given speed (pitch kept, so slowed speech still sounds like speech).
let el: HTMLAudioElement | null = null
let timer: number | undefined
let now: string | null = null
const subs = new Set<() => void>()
const emit = (k: string | null) => { now = k; subs.forEach(f => f()) }
function stop() { window.clearInterval(timer); el?.pause(); emit(null) }
function play(url: string, key: string, t0: number, t1: number, rate: number) {
  if (now === key) { stop(); return }
  stop()
  if (!el) el = new Audio()
  const a = el
  const go = () => {
    a.currentTime = t0; a.preservesPitch = true; a.playbackRate = rate
    void a.play().then(() => { emit(key); window.clearInterval(timer); timer = window.setInterval(() => { if (a.currentTime >= t1 || a.ended) stop() }, 40) }).catch(() => emit(null))
  }
  if (!a.src.endsWith(url)) { a.src = url; a.addEventListener('loadedmetadata', go, { once: true }); a.load() } else go()
}

// The phrases most likely to be wrong, worst first (low confidence, fast speech, the recogniser's own flags), each with a player and a box to retype it. The player has the sound as it was and a version slowed to a normal pace
// (fast speech is where recognisers drop words, and where an ear needs help too). Saving a retyped phrase stores it as word-by-word corrections (timing kept) and takes the phrase off the list.
export default function ReviewPage({ folder, onOpen }: { folder: string; onOpen?: (clip: string, t: number) => void }) {
  const [ver, setVer] = useState(0)
  const data = usePoll(() => api.transcriptReview(folder), 60000, [folder, ver])
  const [showDone, setShowDone] = useState(false)
  const [kind, setKind] = useState<'original' | 'clean'>('clean')
  const [limit, setLimit] = useState(PAGE)
  const [err, setErr] = useState<string>()
  if (!data) return <PanelSkeleton title="Review the transcript" rows={6} />
  const list = data.items.filter(x => showDone || !x.reviewed)
  const refresh = () => setVer(v => v + 1)
  const fail = (e: unknown) => setErr((e as Error).message)
  return (
    <section className="rounded-xl border border-stone-200 bg-white p-4 dark:border-stone-800 dark:bg-stone-900">
      <div className="mb-1 flex flex-wrap items-center justify-between gap-2 text-sm">
        <b>Review the transcript</b>
        <span className="flex flex-wrap items-center gap-3 text-xs text-stone-500">
          <span>{data.todo} to look at of {data.total} phrases</span>
          <label className="flex items-center gap-1">sound <select value={kind} onChange={e => setKind(e.target.value as 'original' | 'clean')} className="rounded border border-stone-300 bg-transparent px-1 py-0.5 dark:border-stone-700"><option value="clean">cleaned</option><option value="original">original</option></select></label>
          <label className="flex items-center gap-1"><input type="checkbox" checked={showDone} onChange={e => setShowDone(e.target.checked)} /> show ones I have looked at</label>
        </span>
      </div>
      <p className="mb-3 text-xs text-stone-500">Worst first: unsure words, speech faster than {data.fast_wps} words a second, and phrases the recogniser itself doubted. Press play (the slowed one plays fast speech at the normal {data.normal_wps} words a second), retype what you hear, press Enter.
        Keys in the box: Enter saves and moves on, Alt+1 plays at the original speed, Alt+2 slowed, Esc stops.</p>
      {err && <p className="mb-2 text-sm text-red-600" role="alert">{err}</p>}
      {list.length === 0 && <p className="text-sm text-stone-500">{data.total === 0 ? 'No speech recognised yet.' : 'Nothing left to look at.'}</p>}
      <ol className="space-y-3">
        {list.slice(0, limit).map((it, k) => <Card key={`${it.clip}:${it.si}:${it.t0}:${it.reviewed}`} folder={folder} it={it} kind={kind} first={k === 0} onOpen={onOpen} onChanged={refresh} onError={fail} />)}
      </ol>
      {list.length > limit && <button className="mt-3 rounded border border-stone-300 px-3 py-1 text-sm dark:border-stone-700" onClick={() => setLimit(l => l + PAGE)}>show {Math.min(PAGE, list.length - limit)} more</button>}
    </section>
  )
}

function Card({ folder, it, kind, first, onOpen, onChanged, onError }: { folder: string; it: ReviewItem; kind: 'original' | 'clean'; first: boolean; onOpen?: (clip: string, t: number) => void; onChanged: () => void; onError: (e: unknown) => void }) {
  const [text, setText] = useState(shownText(it))
  const [busy, setBusy] = useState(false)
  const [, force] = useState(0)
  const input = useRef<HTMLTextAreaElement>(null)
  useEffect(() => { const f = () => force(n => n + 1); subs.add(f); return () => { subs.delete(f) } }, [])
  useEffect(() => { if (first) input.current?.focus() }, [first])
  const url = api.clipAudioUrl(folder, it.clip, kind), slowed = it.play_rate < 1
  const keyOf = (r: number) => `${it.clip}|${it.si}|${r}`
  const go = (r: number) => play(url, keyOf(r), it.play0, it.play1, r)
  const changed = text.trim().split(/\s+/).filter(Boolean).join(' ') !== shownText(it)
  const save = async (edit: boolean) => {
    setBusy(true); stop()
    try {
      if (edit) for (const c of diffPhrase(it.words.map(w => ({ i: w.i ?? 0, w: w.w })), text)) await api.editWord(folder, it.clip, it.si, c.i, c.text)
      await api.markReviewed(folder, it.clip, it.si, !it.reviewed || edit)
      onChanged()
    } catch (e) { onError(e) } finally { setBusy(false) }
  }
  const conf = it.logprob == null ? null : Math.round(Math.exp(it.logprob) * 100)
  const badge = 'rounded-full border px-1.5 text-[11px] leading-5'
  const btn = (r: number, label: string, on: boolean) => (
    <button type="button" onClick={() => go(r)} aria-pressed={on} className={`rounded border px-2 py-0.5 text-xs ${on ? 'border-emerald-600 bg-emerald-600 text-white' : 'border-stone-300 hover:border-emerald-600 dark:border-stone-600'}`}>{on ? '■' : '▶'} {label}</button>)
  return (
    <li className={`rounded-lg border p-3 text-sm ${it.reviewed ? 'border-stone-200 opacity-60 dark:border-stone-800' : 'border-stone-300 dark:border-stone-700'}`}>
      <div className="mb-1 flex flex-wrap items-center gap-1.5 text-xs text-stone-500">
        <button type="button" className="font-mono hover:underline" onClick={() => onOpen?.(it.clip, it.t0)} title="open the clip at this moment">{short(it.clip)} · {mmss(it.t0)}</button>
        <span className={`${badge} ${it.wps != null && it.wps > 4.5 ? 'border-amber-500 text-amber-700 dark:text-amber-300' : 'border-stone-300'}`} title="words a second">{it.wps == null ? 'pace n/a' : `${it.wps.toFixed(1)} w/s · ${Math.round(it.wps * 60)} wpm`}</span>
        <span className={`${badge} ${conf != null && conf < 60 ? 'border-red-400 text-red-700 dark:text-red-300' : 'border-stone-300'}`} title="how sure the recogniser was of the whole phrase">{conf == null ? 'confidence n/a' : `${conf}% sure`}</span>
        {it.low_words > 0 && <span className={`${badge} border-red-400 text-red-700 dark:text-red-300`} title="words the recogniser was under half sure of">{it.low_words} of {it.n_words} words unsure</span>}
        {it.flags.map(f => <span key={f} className={`${badge} border-stone-400`}>{f.replace(/_/g, ' ')}</span>)}
        {it.lang !== 'en' && <span className={`${badge} border-sky-400 text-sky-700 dark:text-sky-300`}>{it.lang.toUpperCase()}</span>}
        <span className="ml-auto">priority {it.priority.toFixed(1)}</span>
      </div>
      <p className="mb-2 leading-relaxed" aria-label="what the recogniser heard">
        {it.words.map((w, i) => w.w.trim() ? <span key={i} title={w.p == null ? '' : `${Math.round(w.p * 100)}% sure`} className={`mr-1 rounded px-0.5 ${w.p != null && w.p < 0.4 ? 'bg-red-200 dark:bg-red-500/40' : w.p != null && w.p < 0.6 ? 'bg-amber-200 dark:bg-amber-500/30' : ''} ${w.e ? 'underline decoration-dotted decoration-sky-500 decoration-2' : ''}`}>{w.w}</span> : null)}
      </p>
      <div className="mb-2 flex flex-wrap items-center gap-2">
        {btn(1, 'original speed', now === keyOf(1))}
        {slowed ? btn(it.play_rate, `slowed to normal pace (×${it.play_rate})`, now === keyOf(it.play_rate)) : <span className="text-xs text-stone-500">not fast: no slowed version</span>}
      </div>
      <textarea ref={input} rows={2} value={text} onChange={e => setText(e.target.value)} aria-label="what was said" disabled={busy}
        onKeyDown={e => {
          if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); void save(changed) }
          else if (e.key === 'Escape') stop()
          else if (e.altKey && e.key === '1') { e.preventDefault(); go(1) }
          else if (e.altKey && e.key === '2' && slowed) { e.preventDefault(); go(it.play_rate) }
        }}
        className="w-full rounded border border-stone-300 bg-transparent px-2 py-1 dark:border-stone-700" />
      <div className="mt-1 flex flex-wrap items-center gap-2">
        {it.reviewed
          ? <button type="button" disabled={busy} className="rounded border border-stone-300 px-2 py-0.5 text-xs dark:border-stone-700" onClick={() => void save(false)}>put back in the list</button>
          : <>
            <button type="button" disabled={busy || !changed} className="rounded bg-emerald-700 px-2 py-0.5 text-xs text-white disabled:opacity-40" onClick={() => void save(true)}>save correction</button>
            <button type="button" disabled={busy} className="rounded border border-stone-300 px-2 py-0.5 text-xs dark:border-stone-700" title="the text is right as it is: take it off the list" onClick={() => void save(false)}>looks right</button>
          </>}
        {changed && <button type="button" className="rounded border border-stone-300 px-2 py-0.5 text-xs dark:border-stone-700" onClick={() => setText(shownText(it))}>undo my typing</button>}
        <span className="text-xs text-stone-500">{changed ? 'Enter saves' : 'Enter: looks right'}</span>
      </div>
    </li>
  )
}
