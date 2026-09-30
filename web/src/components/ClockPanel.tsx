import { useState } from 'react'
import { api, type ClockState } from '../api'
import { usePoll } from '../usePoll'

// The camera clock: how many seconds the camera is ahead of the real time (UTC). It decides which part of the race track belongs to each clip. Nudge it, or let the app suggest it from the moments
// where both the camera and the GPS saw you start or stop running. Changing it re-times every clip and redoes the stages that use the track (places).
export default function ClockPanel({ folder }: { folder: string }) {
  const [ver, setVer] = useState(0)
  const c = usePoll(() => api.clock(folder), 5000, [folder, ver])
  const [sug, setSug] = useState<{ offset_s: number; votes: number; confidence: number }[]>(), [busy, setBusy] = useState(false), [err, setErr] = useState<string>(), [val, setVal] = useState<string>()
  if (!c) return null
  const apply = async (off: number) => { setBusy(true); setErr(undefined); try { await api.setClock(folder, off); setVal(undefined); setVer(v => v + 1) } catch (e) { setErr((e as Error).message) } setBusy(false) }
  const cur = c.offset_s, nudge = (d: number) => apply(Math.round((cur + d) * 10) / 10)
  const btn = 'rounded border border-stone-300 px-2 py-0.5 text-xs disabled:opacity-40 dark:border-stone-700'
  return (
    <section className="rounded-xl border border-stone-200 bg-white p-4 dark:border-stone-800 dark:bg-stone-900">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <h3 className="mr-2 text-sm font-semibold">Camera clock</h3>
        <span>{cur >= 0 ? '+' : ''}{cur.toFixed(1)} s</span><span className={c.verified ? 'text-emerald-700' : 'text-amber-700'}>{c.verified ? 'confirmed' : 'not confirmed yet'}</span>
        {[-10, -1, 1, 10].map(d => <button key={d} disabled={busy} className={btn} onClick={() => nudge(d)}>{d > 0 ? '+' : ''}{d} s</button>)}
        <input value={val ?? ''} onChange={e => setVal(e.target.value)} placeholder="seconds" className="w-24 rounded border border-stone-300 bg-transparent px-2 py-0.5 text-sm dark:border-stone-700" />
        <button disabled={busy || val === undefined || isNaN(Number(val))} className={btn} onClick={() => apply(Number(val))}>set</button>
        <button disabled={busy || !c.has_track} className={btn} title="uses the moments both the camera and the GPS saw you start or stop running" onClick={async () => { setBusy(true); setErr(undefined); try { setSug((await api.clockSuggest(folder)).suggestions) } catch (e) { setErr((e as Error).message) } setBusy(false) }}>suggest</button>
        {busy && <span className="text-xs text-stone-500">working…</span>}
      </div>
      {c.note && <p className="mt-1 text-xs text-stone-500">{c.note}</p>}
      {sug && <ul className="mt-2 text-sm">{sug.length === 0 ? <li className="text-stone-500">No starts or stops matched between the camera and the GPS.</li> : sug.map((s, i) => <li key={i} className="flex items-center gap-2">
        <span className="font-mono">{s.offset_s >= 0 ? '+' : ''}{s.offset_s.toFixed(1)} s</span><span className="text-xs text-stone-500">{s.votes} matching events · {Math.round(s.confidence * 100)}% sure</span>
        <button disabled={busy} className={btn} onClick={() => apply(s.offset_s)}>use</button></li>)}</ul>}
      {err && <p className="mt-1 text-sm text-red-600">{err}</p>}
      {!c.has_track && <p className="mt-1 text-xs text-stone-500">Add the race track to get suggestions.</p>}
    </section>
  )
}
