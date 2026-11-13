import { useEffect, useState } from 'react'
import { api, type Meta, type Results } from '../api'
import { PanelSkeleton } from './Skeleton'
import { Button, Input } from 'strata-react'

// Title, date and race results. The date defaults to the earliest capture in the footage; results feed the voice-over script (a DNF has no finishing position).
export default function FilmDetails({ folder }: { folder: string }) {
  const [m, setM] = useState<Meta>()
  const [err, setErr] = useState<string>()
  useEffect(() => { let live = true; api.meta(folder).then(x => live && setM(x)).catch(() => {}); return () => { live = false } }, [folder])      // a failed request leaves the skeleton: it must not be an unhandled rejection
  if (!m) return <PanelSkeleton title="Film details" rows={4} />
  const save = async (patch: Parameters<typeof api.saveMeta>[1]) => {
    try { setM(await api.saveMeta(folder, patch)); setErr(undefined) } catch (e) { setErr((e as Error).message) }
  }
  const r = m.results
  const num = (k: 'starters' | 'finishers' | 'position', label: string, disabled = false) => (
    <label className="type-body-sm"><span className="mb-1 block text-muted-foreground">{label}</span>
      <Input type="number" min={1} disabled={disabled} defaultValue={r[k] ?? ''} key={`${k}-${r[k]}-${disabled}`}
        onBlur={e => { const v = e.target.value; if (String(r[k] ?? '') !== v) save({ results: { [k]: v === '' ? null : Number(v) } as Partial<Results> }) }}
        className="w-full" /></label>
  )
  const inp = 'w-full rounded-surface border border-border bg-card px-2 py-1.5'
  return (
    <section className="rounded-overlay border border-border bg-card p-4">
      <h3 className="mb-3 type-body-sm font-semibold">Film details</h3>
      <div className="grid gap-3 md:grid-cols-2">
        <label className="type-body-sm"><span className="mb-1 block text-muted-foreground">Title</span>
          <input className={inp} defaultValue={m.title ?? ''} placeholder={m.defaults.title ?? 'Race or film title'} onBlur={e => e.target.value !== (m.title ?? '') && save({ title: e.target.value })} /></label>
        <label className="type-body-sm"><span className="mb-1 block text-muted-foreground">Date {m.date == null && m.defaults.date ? <span className="type-caption">(earliest capture)</span> : <Button variant="link" size="sm" onClick={() => save({ date: '' })}>use earliest capture</Button>}</span>
          <input type="date" className={inp} value={m.effective.date ?? ''} onChange={e => save({ date: e.target.value })} /></label>
      </div>
      <label className="mt-3 block max-w-xs type-body-sm"><span className="mb-1 block text-muted-foreground">Official race distance (km) <span className="type-caption">(the script writer uses it for "km to go")</span></span>
        <input type="number" min={1} step="any" className={inp} defaultValue={m.distance_km ?? ''} key={`dist-${m.distance_km}`} placeholder="e.g. 100"
          onBlur={e => { const v = e.target.value; if (String(m.distance_km ?? '') !== v) save({ distance_km: v === '' ? null : Number(v) }) }} /></label>
      <h4 className="mb-2 mt-4 type-body-sm font-medium">Race results</h4>
      <div className="grid gap-3 sm:grid-cols-4">
        {num('starters', 'Starters')}{num('finishers', 'Finishers')}
        <label className="type-body-sm"><span className="mb-1 block text-muted-foreground">You</span>
          <select className={inp} value={r.finished == null ? '' : r.finished ? 'yes' : 'no'} onChange={e => save({ results: { finished: e.target.value === '' ? null : e.target.value === 'yes' } })}>
            <option value="">not set</option><option value="yes">finished</option><option value="no">did not finish</option></select></label>
        {num('position', 'Your position', r.finished !== true)}
      </div>
      {err && <p className="mt-2 type-body-sm text-danger">{err}</p>}
    </section>
  )
}
