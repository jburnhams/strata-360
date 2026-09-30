import { useState } from 'react'
import { api } from '../api'
import { usePoll } from '../usePoll'

// Which face is you. The app groups every face it finds; the sheet shows each group with its number. Pick your group (or several: the same face from other angles often splits), and the stages
// that need to know who you are (where you are in the picture, framing on you, who is speaking) can run.
export default function WhoPanel({ folder }: { folder: string }) {
  const [ver, setVer] = useState(0)
  const w = usePoll(() => api.who(folder), 15000, [folder, ver])
  const [pick, setPick] = useState<number[]>([]), [busy, setBusy] = useState(false), [err, setErr] = useState<string>(), [open, setOpen] = useState(false)
  if (!w) return null
  if (!w.ready) return w.profile ? null : <section className="rounded-xl border border-stone-200 bg-white p-4 text-sm text-stone-500 dark:border-stone-800 dark:bg-stone-900">Which face is you: available once faces have been found in the footage ({w.reason}).</section>
  const chosen = pick.length ? pick : (w.suggested?.clusters ?? [])
  const save = async () => { setBusy(true); setErr(undefined); try { await api.setWho(folder, chosen); setOpen(false); setVer(v => v + 1) } catch (e) { setErr((e as Error).message) } setBusy(false) }
  return (
    <section className="rounded-xl border border-stone-200 bg-white p-4 dark:border-stone-800 dark:bg-stone-900">
      <div className="flex flex-wrap items-center gap-3 text-sm">
        <h3 className="text-sm font-semibold">Which face is you</h3>
        <span className={w.profile ? 'text-emerald-700' : 'text-amber-700'}>{w.profile ? 'chosen' : 'not chosen yet'}</span>
        <button className="rounded border border-stone-300 px-2 py-0.5 text-xs dark:border-stone-700" onClick={() => setOpen(o => !o)}>{open || !w.profile ? (open ? 'hide' : 'show the faces') : 'change'}</button>
      </div>
      {(open || !w.profile) && <div className="mt-3">
        {w.suggested && <p className="mb-2 text-sm text-stone-500">{w.suggested.confident ? 'Suggested' : 'Best guess (not sure)'}: {w.suggested.clusters.join(', ')}. {w.suggested.why}</p>}
        {w.sheet && <img src={api.whoSheetUrl(folder, ver)} alt="face groups" className="mb-2 max-h-[420px] w-auto rounded-lg border border-stone-200 dark:border-stone-800" />}
        <div className="flex flex-wrap gap-2 text-sm">{w.clusters?.slice(0, 16).map(c => <label key={c.cluster} className={`cursor-pointer rounded border px-2 py-0.5 ${chosen.includes(c.cluster) ? 'border-emerald-600 bg-emerald-50 dark:bg-emerald-950/40' : 'border-stone-300 dark:border-stone-700'}`} title={`${c.n} faces in ${c.clips} clips, ${Math.round(c.rear_fraction * 100)}% on the rear lens`}>
          <input type="checkbox" className="mr-1" checked={chosen.includes(c.cluster)} onChange={e => setPick((pick.length ? pick : chosen).filter(x => x !== c.cluster).concat(e.target.checked ? [c.cluster] : []))} />#{c.cluster} <span className="text-xs text-stone-500">{c.n}</span></label>)}</div>
        <button disabled={busy || !chosen.length} className="mt-3 rounded-lg bg-emerald-700 px-3 py-1.5 text-sm text-white disabled:opacity-50" onClick={save}>{busy ? 'saving…' : `This is me (${chosen.join(', ')})`}</button>
        {err && <p className="mt-1 text-sm text-red-600">{err}</p>}
      </div>}
    </section>
  )
}
