import { useState } from 'react'
import { api } from '../api'
import { usePoll } from '../usePoll'
import { Button } from 'strata-react'

// Which face is you. The app groups every face it finds; the sheet shows each group with its number. Pick your group (or several: the same face from other angles often splits), and the stages
// that need to know who you are (where you are in the picture, framing on you, who is speaking) can run.
export default function WhoPanel({ folder }: { folder: string }) {
  const [ver, setVer] = useState(0)
  const w = usePoll(() => api.who(folder), 15000, [folder, ver])
  const [pick, setPick] = useState<number[]>([]), [busy, setBusy] = useState(false), [err, setErr] = useState<string>(), [open, setOpen] = useState(false)
  if (!w) return null
  if (!w.ready) return w.profile ? null : <section className="rounded-overlay border border-border bg-card p-4 type-body-sm text-muted-foreground">Which face is you: available once faces have been found in the footage ({w.reason}).</section>
  const chosen = pick.length ? pick : (w.suggested?.clusters ?? [])
  const save = async () => { setBusy(true); setErr(undefined); try { await api.setWho(folder, chosen); setOpen(false); setVer(v => v + 1) } catch (e) { setErr((e as Error).message) } setBusy(false) }
  return (
    <section className="rounded-overlay border border-border bg-card p-4">
      <div className="flex flex-wrap items-center gap-3 type-body-sm">
        <h3 className="type-body-sm font-semibold">Which face is you</h3>
        <span className={w.profile ? 'text-primary' : 'text-warning'}>{w.profile ? 'chosen' : 'not chosen yet'}</span>
        {w.profile && <img src={api.whoMeUrl(folder, ver)} alt="the chosen face" className="h-14 rounded-control border border-border" />}
        <Button size="sm" onClick={() => setOpen(o => !o)}>{open || !w.profile ? (open ? 'hide' : 'show the faces') : 'change'}</Button>
      </div>
      {(open || !w.profile) && <div className="mt-3">
        {w.suggested && <p className="mb-2 type-body-sm text-muted-foreground">{w.suggested.confident ? 'Suggested' : 'Best guess (not sure)'}: {w.suggested.clusters.join(', ')}. {w.suggested.why}</p>}
        {w.sheet && <img src={api.whoSheetUrl(folder, ver)} alt="face groups" className="mb-2 max-h-[420px] w-auto rounded-surface border border-border" />}
        <div className="flex flex-wrap gap-2 type-body-sm">{w.clusters?.slice(0, 16).map(c => <label key={c.cluster} className={`cursor-pointer rounded-control border px-2 py-0.5 ${chosen.includes(c.cluster) ? 'border-primary bg-primary-3' : 'border-border'}`} title={`${c.n} faces in ${c.clips} clips, ${Math.round(c.rear_fraction * 100)}% on the rear lens`}>
          <input type="checkbox" className="mr-1" checked={chosen.includes(c.cluster)} onChange={e => setPick((pick.length ? pick : chosen).filter(x => x !== c.cluster).concat(e.target.checked ? [c.cluster] : []))} />#{c.cluster} <span className="type-caption text-muted-foreground">{c.n}</span></label>)}</div>
        <Button variant="default" disabled={busy || !chosen.length} className="mt-3" onClick={save}>{busy ? 'saving…' : `This is me (${chosen.join(', ')})`}</Button>
        {err && <p className="mt-1 type-body-sm text-danger">{err}</p>}
      </div>}
    </section>
  )
}
