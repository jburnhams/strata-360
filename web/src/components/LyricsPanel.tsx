import { useState } from 'react'
import { api, type LyricPhrase } from '../api'
import { usePoll } from '../usePoll'

const mmss = (s: number) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`

// The words in the music track, found by speech recognition (rough on music: the times are what count, the words are a guide). Where it is sung matters: the film keeps the voice-over and the runner's speech
// out of the singing. A phrase the recogniser doubted does not count as sung until you say so; a phrase that is not a lyric can be marked "not sung"; the words can be corrected.
export default function LyricsPanel({ folder }: { folder: string }) {
  const [tick, setTick] = useState(0)
  const [err, setErr] = useState<string>()
  const ly = usePoll(() => api.lyrics(folder), 3000, [folder, tick])
  if (!ly || !ly.has_track) return null
  const run = async (fn: () => Promise<unknown>) => { setErr(undefined); try { await fn() } catch (e) { setErr((e as Error).message) } setTick(t => t + 1) }
  const find = () => run(async () => { const r = await api.findLyrics(folder); if (!r.started) throw new Error(r.reason ?? 'could not start') })
  const pct = ly.sung_s != null && ly.duration_s ? Math.round(100 * ly.sung_s / ly.duration_s) : null
  const row = (p: LyricPhrase) => (
    <li key={p.key} className={`flex flex-wrap items-center gap-2 py-1 ${p.deleted ? 'opacity-50' : ''}`}>
      <span className="w-20 shrink-0 font-mono type-caption text-muted-foreground">{mmss(p.t0)}–{mmss(p.t1)}</span>
      <input aria-label={`Words at ${mmss(p.t0)}`} defaultValue={p.text} className={`min-w-[12rem] flex-1 rounded-control border border-transparent bg-transparent px-1 hover:border-border ${p.deleted ? 'line-through' : ''}`}
        onBlur={e => { if (e.target.value.trim() !== p.text) void run(() => api.editLyric(folder, p.key, { text: e.target.value.trim() === p.heard ? '' : e.target.value })) }} />
      {p.doubtful && !p.deleted && <span className="type-caption text-warning">{p.counts ? 'doubtful, counted' : 'doubtful, not counted'}</span>}
      {p.doubtful && !p.deleted && <button className="type-caption underline" onClick={() => void run(() => api.editLyric(folder, p.key, { keep: !p.counts }))}>{p.counts ? 'Do not count' : 'Count it'}</button>}
      <button className="type-caption text-muted-foreground underline" onClick={() => void run(() => api.editLyric(folder, p.key, { deleted: !p.deleted }))}>{p.deleted ? 'Restore' : 'Not sung'}</button>
    </li>)
  return (
    <div className="mt-3 border-t border-border pt-3">
      <div className="flex flex-wrap items-center gap-3 type-body-sm">
        <h4 className="font-semibold">Lyrics</h4>
        <button disabled={ly.building} className="rounded-surface border border-border px-3 py-1 disabled:opacity-50" onClick={() => void find()}>{ly.building ? 'Listening…' : ly.exists ? 'Find them again' : 'Find the lyrics'}</button>
        {ly.building && <span className="font-mono type-caption text-muted-foreground">{ly.log}</span>}
        {ly.exists && !ly.building && <span className="type-caption text-muted-foreground">{ly.instrumental ? 'instrumental: no singing found' : `${ly.phrases} phrases, ${ly.sung_s} s sung${pct != null ? ` (${pct}%)` : ''}, ${ly.language}`}</span>}
        {ly.exists && ly.stale && !ly.building && <span className="type-caption text-warning">out of date: the track has changed since</span>}
        {ly.exists && !ly.building && <button className="type-caption text-muted-foreground underline" title="forget the lyrics (your corrections are kept)" onClick={() => void run(() => api.resetLyrics(folder))}>Reset</button>}
        {(err || (!ly.building && ly.error)) && <span role="alert" className="type-caption text-danger">{err ?? `Finding the lyrics failed: ${ly.error}`}</span>}
      </div>
      {ly.exists && ly.phrases_list.length > 0 && <ul className="mt-2 max-h-72 divide-y divide-border overflow-y-auto type-body-sm">{ly.phrases_list.map(row)}</ul>}
    </div>
  )
}
