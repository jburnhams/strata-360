import { useEffect, useRef, useState } from 'react'
import { api, type ReviewItem } from '../api'
import { usePoll } from '../usePoll'
import { diffPhrase } from '../phraseDiff'
import { PanelSkeleton } from './Skeleton'

const PAGE = 20
const short = (id: string) => id.replace(/^CAM_/, '').replace(/_D$/, '').replace(/^(\d{8})(\d{6})_/, (_, d, t) => `${d.slice(6)}/${d.slice(4, 6)} ${t.slice(0, 2)}:${t.slice(2, 4)} · `)
const mmss = (s: number) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`
const shownText = (it: ReviewItem) => it.words.map(w => w.w.trim()).filter(Boolean).join(' ')

// One shared audio element: playing a phrase stops the previous one. The phrase plays in the clip's stored sound at the given speed (pitch kept, so slowed speech still sounds like speech), from a little before its first word
// to a little after its last (play0 to play1) so it is heard in context; the card marks where the phrase itself is on a timeline and lights the word being heard.
let el: HTMLAudioElement | null = null
let timer: number | undefined
let now: string | null = null
let pos = 0                                                   // where the sound is now (seconds into the clip), kept for the cards while it plays
let loop = true                                               // one setting for every player on the page: the phrase repeats until you stop it, save, or hide it
const subs = new Set<() => void>()
const emit = (k: string | null) => { now = k; subs.forEach(f => f()) }
const setLoop = (v: boolean) => { loop = v; subs.forEach(f => f()) }
function stop() { window.clearInterval(timer); el?.pause(); emit(null) }
/** The word being heard at `t`: the last one that has begun, until the phrase has ended (-1 before its first word and after its last). */
function wordAt(words: { t0: number; t1: number }[], t: number): number {
  let k = -1
  words.forEach((w, i) => { if (t >= w.t0) k = i })
  return k >= 0 && t > words[k].t1 + 0.25 ? -1 : k
}
function play(url: string, key: string, t0: number, t1: number, rate: number) {
  if (now === key) { stop(); return }
  stop()
  if (!el) el = new Audio()
  const a = el
  const go = () => {
    a.currentTime = t0; a.preservesPitch = true; a.playbackRate = rate
    void a.play().then(() => { pos = a.currentTime; emit(key); window.clearInterval(timer); timer = window.setInterval(() => {
      if (a.currentTime >= t1 || a.ended) { if (!loop) { stop(); return }; a.currentTime = t0; if (a.ended || a.paused) void a.play() }       // looping: back to the start of the span (the sound may have run out at the end of the clip first)
      pos = a.currentTime; subs.forEach(f => f())
    }, 40) }).catch(() => emit(null))
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
  const list = data.items.filter(x => x.hidden || showDone || !x.reviewed)                  // the hidden ones are always listed (last), so they can be shown again
  const refresh = () => setVer(v => v + 1)
  const fail = (e: unknown) => setErr((e as Error).message)
  return (
    <section className="rounded-overlay border border-border bg-card p-4">
      <div className="mb-1 flex flex-wrap items-center justify-between gap-2 type-body-sm">
        <b>Review the transcript</b>
        <span className="flex flex-wrap items-center gap-3 type-caption text-muted-foreground">
          <span>{data.todo} to look at of {data.total} phrases</span>
          <label className="flex items-center gap-1">sound <select value={kind} onChange={e => setKind(e.target.value as 'original' | 'clean')} className="rounded-control border border-border bg-transparent px-1 py-0.5"><option value="clean">cleaned</option><option value="original">original</option></select></label>
          <label className="flex items-center gap-1"><input type="checkbox" checked={showDone} onChange={e => setShowDone(e.target.checked)} /> show ones I have looked at</label>
        </span>
      </div>
      <p className="mb-3 type-caption text-muted-foreground">Worst first: unsure words, speech faster than {data.fast_wps} words a second, and phrases the recogniser itself doubted. Press play (the slowed one plays fast speech at the normal {data.normal_wps} words a second), retype what you hear, press Enter.
        Keys in the box: Enter saves and moves on, Alt+1 plays at the original speed, Alt+2 slowed, Esc stops.</p>
      {err && <p className="mb-2 type-body-sm text-danger" role="alert">{err}</p>}
      {list.length === 0 && <p className="type-body-sm text-muted-foreground">{data.total === 0 ? 'No speech recognised yet.' : 'Nothing left to look at.'}</p>}
      <ol className="space-y-3">
        {list.slice(0, limit).map((it, k) => <Card key={`${it.clip}:${it.si}:${it.t0}:${it.reviewed}:${it.hidden}`} folder={folder} it={it} kind={kind} first={k === 0} onOpen={onOpen} onChanged={refresh} onError={fail} />)}
      </ol>
      {list.length > limit && <button className="mt-3 rounded-control border border-border px-3 py-1 type-body-sm" onClick={() => setLimit(l => l + PAGE)}>show {Math.min(PAGE, list.length - limit)} more</button>}
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
  const mine = `${it.clip}|${it.si}|`
  useEffect(() => () => { if (now?.startsWith(mine)) stop() }, [mine])                      // the card has gone (saved, hidden, filtered out): its sound must not play on, least of all in a loop
  const url = api.clipAudioUrl(folder, it.clip, kind), slowed = it.play_rate < 1
  const keyOf = (r: number) => `${it.clip}|${it.si}|${r}`
  const active = now?.startsWith(`${it.clip}|${it.si}|`) ?? false
  const heard = active ? wordAt(it.words, pos) : -1
  const span = Math.max(it.play1 - it.play0, 0.1), at = (t: number) => `${Math.min(Math.max((t - it.play0) / span, 0), 1) * 100}%`
  const first0 = it.words[0]?.t0 ?? it.t0, last1 = it.words[it.words.length - 1]?.t1 ?? it.t1
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
  const hide = async (state: boolean) => {
    setBusy(true); stop()
    try { await api.hideTranscriptPhrase(folder, it.clip, it.si, state); onChanged() } catch (e) { onError(e) } finally { setBusy(false) }
  }
  const conf = it.logprob == null ? null : Math.round(Math.exp(it.logprob) * 100)
  const badge = 'rounded-pill border px-1.5 text-[11px] leading-5'
  const btn = (r: number, label: string, on: boolean) => (
    <button type="button" onClick={() => go(r)} aria-pressed={on} className={`rounded-control border px-2 py-0.5 type-caption ${on ? 'border-primary bg-primary text-primary-foreground' : 'border-border hover:border-primary'}`}>{on ? '■' : '▶'} {label}</button>)
  return (
    <li className={`rounded-surface border p-3 type-body-sm ${it.hidden ? 'border-dashed border-border opacity-50' : it.reviewed ? 'border-border opacity-60' : 'border-border'}`}>
      <div className="mb-1 flex flex-wrap items-center gap-1.5 type-caption text-muted-foreground">
        <button type="button" className="font-mono hover:underline" onClick={() => onOpen?.(it.clip, it.t0)} title="open the clip at this moment">{short(it.clip)} · {mmss(it.t0)}</button>
        <span className={`${badge} ${it.wps != null && it.wps > 4.5 ? 'border-warning text-warning' : 'border-border'}`} title="words a second">{it.wps == null ? 'pace n/a' : `${it.wps.toFixed(1)} w/s · ${Math.round(it.wps * 60)} wpm`}</span>
        <span className={`${badge} ${conf != null && conf < 60 ? 'border-danger text-danger' : 'border-border'}`} title="how sure the recogniser was of the whole phrase">{conf == null ? 'confidence n/a' : `${conf}% sure`}</span>
        {it.low_words > 0 && <span className={`${badge} border-danger text-danger`} title="words the recogniser was under half sure of">{it.low_words} of {it.n_words} words unsure</span>}
        {it.flags.map(f => <span key={f} className={`${badge} border-border`}>{f.replace(/_/g, ' ')}</span>)}
        {it.lang !== 'en' && <span className={`${badge} border-info text-info`}>{it.lang.toUpperCase()}</span>}
        {it.hidden && <span className={`${badge} border-input text-foreground`} title="the rest of the pipeline does not see this phrase">hidden</span>}
        <span className="ml-auto">priority {it.priority.toFixed(1)}</span>
      </div>
      <p className="mb-2 leading-relaxed" aria-label="what the recogniser heard">
        {it.words.map((w, i) => w.w.trim() ? <span key={i} title={w.p == null ? '' : `${Math.round(w.p * 100)}% sure`} className={`mr-1 rounded-control px-0.5 ${w.p != null && w.p < 0.4 ? 'bg-danger-subtle' : w.p != null && w.p < 0.6 ? 'bg-warning-subtle' : ''} ${w.e ? 'underline decoration-dotted decoration-info decoration-2' : ''} ${i === heard ? 'outline outline-2 outline-primary' : ''}`} aria-current={i === heard ? 'true' : undefined}>{w.w}</span> : null)}
      </p>
      <div className="mb-2" data-testid="phrase-timeline">
        <div role="img" aria-label={`the phrase runs from ${mmss(first0)} to ${mmss(last1)} of the clip; the player plays from ${mmss(it.play0)} to ${mmss(it.play1)}`} className="relative h-3 overflow-hidden rounded-control bg-muted">
          <div className="absolute inset-y-0 bg-primary" style={{ left: at(first0), width: `calc(${at(last1)} - ${at(first0)})` }} />
          {it.words.map((w, i) => w.w.trim() ? <div key={i} className={`absolute inset-y-0 w-px ${i === heard ? 'bg-primary' : 'bg-primary/40'}`} style={{ left: at(w.t0) }} /> : null)}
          {active && <div className="absolute inset-y-0 w-0.5 bg-danger" style={{ left: at(pos) }} data-testid="playhead" />}
        </div>
        <div className="mt-0.5 flex justify-between font-mono text-[10px] text-muted-foreground"><span>{mmss(it.play0)}</span><span>phrase {mmss(first0)}–{mmss(last1)}</span><span>{mmss(it.play1)}</span></div>
      </div>
      <div className="mb-2 flex flex-wrap items-center gap-2">
        {btn(1, 'original speed', now === keyOf(1))}
        {slowed ? btn(it.play_rate, `slowed to normal pace (×${it.play_rate})`, now === keyOf(it.play_rate)) : <span className="type-caption text-muted-foreground">not fast: no slowed version</span>}
        <button type="button" onClick={() => setLoop(!loop)} aria-pressed={loop} title="repeat the phrase until you stop it, save a correction or hide it (the same for every player on the page)" className={`ml-auto rounded-control border px-2 py-0.5 type-caption ${loop ? 'border-primary bg-primary text-primary-foreground' : 'border-border hover:border-primary'}`}>⟳ loop</button>
      </div>
      {it.hidden ? <button type="button" disabled={busy} className="rounded-control border border-border px-2 py-0.5 type-caption" title="put the phrase back in the transcript" onClick={() => void hide(false)}>show again</button> : <>
      <textarea ref={input} rows={2} value={text} onChange={e => setText(e.target.value)} aria-label="what was said" disabled={busy}
        onKeyDown={e => {
          if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); void save(changed) }
          else if (e.key === 'Escape') stop()
          else if (e.altKey && e.key === '1') { e.preventDefault(); go(1) }
          else if (e.altKey && e.key === '2' && slowed) { e.preventDefault(); go(it.play_rate) }
        }}
        className="w-full rounded-control border border-border bg-transparent px-2 py-1" />
      <div className="mt-1 flex flex-wrap items-center gap-2">
        {it.reviewed
          ? <button type="button" disabled={busy} className="rounded-control border border-border px-2 py-0.5 type-caption" onClick={() => void save(false)}>put back in the list</button>
          : <>
            <button type="button" disabled={busy || !changed} className="rounded-control bg-primary px-2 py-0.5 type-caption text-primary-foreground disabled:opacity-40" onClick={() => void save(true)}>save correction</button>
            <button type="button" disabled={busy} className="rounded-control border border-border px-2 py-0.5 type-caption" title="the text is right as it is: take it off the list" onClick={() => void save(false)}>looks right</button>
          </>}
        {changed && <button type="button" className="rounded-control border border-border px-2 py-0.5 type-caption" onClick={() => setText(shownText(it))}>undo my typing</button>}
        <span className="type-caption text-muted-foreground">{changed ? 'Enter saves' : 'Enter: looks right'}</span>
        <button type="button" disabled={busy} className="ml-auto rounded-control border border-danger px-2 py-0.5 type-caption text-danger" title="take this phrase out of the transcript for everything after it (it stays at the bottom of this page)" onClick={() => void hide(true)}>hide</button>
      </div></>}
    </li>
  )
}
