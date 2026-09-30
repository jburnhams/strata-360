import { useState } from 'react'
import { api } from '../api'
import { usePoll } from '../usePoll'

// The music: its tempo, bar line and loudness drive the plan (cuts on the beat, calm and busy parts follow the music) and it is mixed under the voice-over, from its first downbeat.
export default function MusicPanel({ folder, onChanged }: { folder: string; onChanged: () => void }) {
  const [ver, setVer] = useState(0)
  const st = usePoll(() => api.music(folder), 4000, [folder, ver])
  const [busy, setBusy] = useState(false), [msg, setMsg] = useState<string>()
  const pick = async (f?: File) => { if (!f) return; setBusy(true); setMsg(undefined); try { const r = await api.uploadMusic(folder, f); if (r.warning) setMsg(r.warning) } catch (e) { setMsg((e as Error).message) } setBusy(false); setVer(v => v + 1); onChanged() }
  const a = st?.analysis
  return (
    <section className="rounded-xl border border-stone-200 bg-white p-4 dark:border-stone-800 dark:bg-stone-900">
      <div className="flex flex-wrap items-center gap-3">
        <h3 className="text-sm font-semibold">Music</h3>
        <label className="cursor-pointer rounded-lg border border-stone-300 px-3 py-1.5 text-sm dark:border-stone-700">{busy ? 'analysing…' : st?.file ? 'Replace track' : 'Add a track'}<input type="file" accept="audio/*" className="hidden" disabled={busy} onChange={e => pick(e.target.files?.[0])} /></label>
        {st?.file && <button className="text-xs underline" onClick={async () => { await api.removeMusic(folder); setVer(v => v + 1); onChanged() }}>remove</button>}
        {a && <span className="text-sm text-stone-500">{a.bpm} bpm · first bar at {a.offset_s.toFixed(1)} s · {Math.round(a.duration_s)} s long{a.confidence < 0.4 && <span className="text-amber-700"> · the beat is uncertain (tempo may change in this track)</span>}</span>}
      </div>
      {a && <div className="mt-2 flex h-3 w-full overflow-hidden rounded bg-stone-200 dark:bg-stone-800" title="energy of the music, bar by bar: the film cuts faster and uses livelier shots where it is high">
        {a.sections.map(([s, e, en], i) => <div key={i} style={{ width: `${(100 * (e - s)) / a.usable_beats}%`, background: `hsl(150 60% ${75 - 40 * en}%)` }} />)}</div>}
      {msg && <p className="mt-2 text-sm text-amber-700">{msg}</p>}
      {!st?.file && <p className="mt-2 text-xs text-stone-500">Optional. Without a track the plan uses a steady 120 bpm.</p>}
    </section>
  )
}
