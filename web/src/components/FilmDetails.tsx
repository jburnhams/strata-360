import { useEffect, useState } from 'react'
import { api, type Meta, type Results } from '../api'
import { PanelSkeleton } from './Skeleton'

// Title, date and race results. The date defaults to the earliest capture in the footage; results feed the voice-over script (a DNF has no finishing position).
export default function FilmDetails({ folder }: { folder: string }) {
  const [m, setM] = useState<Meta>()
  const [err, setErr] = useState<string>()
  useEffect(() => { api.meta(folder).then(setM) }, [folder])
  if (!m) return <PanelSkeleton title="Film details" rows={4} />
  const save = async (patch: Parameters<typeof api.saveMeta>[1]) => {
    try { setM(await api.saveMeta(folder, patch)); setErr(undefined) } catch (e) { setErr((e as Error).message) }
  }
  const r = m.results
  const num = (k: 'starters' | 'finishers' | 'position', label: string, disabled = false) => (
    <label className="text-sm"><span className="mb-1 block text-stone-500">{label}</span>
      <input type="number" min={1} disabled={disabled} defaultValue={r[k] ?? ''} key={`${k}-${r[k]}-${disabled}`}
        onBlur={e => { const v = e.target.value; if (String(r[k] ?? '') !== v) save({ results: { [k]: v === '' ? null : Number(v) } as Partial<Results> }) }}
        className="w-full rounded-lg border border-stone-300 bg-stone-50 px-2 py-1.5 disabled:opacity-40 dark:border-stone-700 dark:bg-stone-950" /></label>
  )
  const inp = 'w-full rounded-lg border border-stone-300 bg-stone-50 px-2 py-1.5 dark:border-stone-700 dark:bg-stone-950'
  return (
    <section className="rounded-xl border border-stone-200 bg-white p-4 dark:border-stone-800 dark:bg-stone-900">
      <h3 className="mb-3 text-sm font-semibold">Film details</h3>
      <div className="grid gap-3 md:grid-cols-2">
        <label className="text-sm"><span className="mb-1 block text-stone-500">Title</span>
          <input className={inp} defaultValue={m.title ?? ''} placeholder={m.defaults.title ?? 'Race or film title'} onBlur={e => e.target.value !== (m.title ?? '') && save({ title: e.target.value })} /></label>
        <label className="text-sm"><span className="mb-1 block text-stone-500">Date {m.date == null && m.defaults.date ? <span className="text-xs">(earliest capture)</span> : <button className="text-xs underline" onClick={() => save({ date: '' })}>use earliest capture</button>}</span>
          <input type="date" className={inp} value={m.effective.date ?? ''} onChange={e => save({ date: e.target.value })} /></label>
      </div>
      <h4 className="mb-2 mt-4 text-sm font-medium">Race results</h4>
      <div className="grid gap-3 sm:grid-cols-4">
        {num('starters', 'Starters')}{num('finishers', 'Finishers')}
        <label className="text-sm"><span className="mb-1 block text-stone-500">You</span>
          <select className={inp} value={r.finished == null ? '' : r.finished ? 'yes' : 'no'} onChange={e => save({ results: { finished: e.target.value === '' ? null : e.target.value === 'yes' } })}>
            <option value="">not set</option><option value="yes">finished</option><option value="no">did not finish</option></select></label>
        {num('position', 'Your position', r.finished !== true)}
      </div>
      {err && <p className="mt-2 text-sm text-red-600">{err}</p>}
    </section>
  )
}
