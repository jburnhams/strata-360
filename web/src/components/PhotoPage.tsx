import { useState } from 'react'
import { api, type MotionStyle, type Photo } from '../api'
import ItemPage, { LengthField } from './ItemPage'
import PhotoMotion from './PhotoMotion'
import TrackMap from './TrackMap'

// A photo used in the film as a page of its own, with the same sections as a gap (ItemPage). "Use in the film" on the overview only makes a photo an option (it is then in the film list); "Must be used" here makes the plan add it if
// the script leaves it out.
const STYLES: Record<MotionStyle, string> = { push_in: 'push in', pull_out: 'pull out', pan: 'pan across', drift: 'drift', reveal: 'reveal', hold: 'hold' }
export default function PhotoPage({ folder, photo, tz, onChanged }: { folder: string; photo?: Photo; tz: string; onChanged: () => void }) {
  const [err, setErr] = useState<string>()
  if (!photo) return <p className="text-sm text-stone-500">That photo is not there any more.</p>
  const p = photo, label = p.id.toUpperCase(), m = p.motion ?? { style: 'auto' as const, seconds: null, seed: 0 }
  const run = async (fn: () => Promise<unknown>) => { setErr(undefined); try { await fn() } catch (e) { setErr((e as Error).message) } onChanged() }
  const when = new Intl.DateTimeFormat('en-GB', { timeZone: tz, weekday: 'short', day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', hour12: false }).format(new Date(p.taken_utc * 1000)).replace(',', '')
  return (
    <ItemPage folder={folder} noun="photo" must={!!p.must} script={p.script ?? []} err={err} noteClip={label} noteTitle="Notes for this photo" notePlaceholder="What was this? Where were you, what to mention or avoid…"
      heading={<>Photo {label} <span className="text-sm font-normal text-stone-500">{when}</span></>}
      sub={`${p.name}${p.track ? ` · km ${p.track.km}` : ''}${p.analysis?.place ? ` · ${p.analysis.place}` : ''}`}
      where={p.loc || p.track ? <TrackMap folder={folder} tz={tz} point={p.loc ?? p.track!} label={`Photo ${label}`} /> : <p className="text-sm text-stone-500">This photo is not on the run: it has no place, or its time is outside the run.</p>}
      preview={<>
        <a href={api.photoFile(folder, p.id)} target="_blank" rel="noreferrer"><img src={api.photoThumb(folder, p.id, 960)} alt={p.name} className="w-full max-w-3xl rounded" /></a>
        <div className="mt-2"><PhotoMotion folder={folder} p={p} onChanged={onChanged} /></div>
      </>}
      settings={<>
        <label className="flex items-center gap-2"><span className="w-24 text-stone-500">Drawn as</span>
          <select aria-label="Drawn as" value={m.style === 'auto' ? '' : m.style} onChange={e => run(() => api.saveMotion(folder, p.id, { ...m, style: (e.target.value || 'auto') as MotionStyle | 'auto' }))} className="rounded border border-stone-300 bg-transparent px-1 py-0.5 dark:border-stone-700">
            <option value="">the planner chooses</option>{(Object.keys(STYLES) as MotionStyle[]).map(k => <option key={k} value={k}>{STYLES[k]}</option>)}
          </select></label>
        <LengthField id={p.id} mode={m.seconds == null ? '' : 'set'} seconds={m.seconds} modes={['set']} min={2} max={8} fallback={2.5} onChange={(_, seconds) => run(() => api.saveMotion(folder, p.id, { ...m, seconds }))} />
        <label className="flex items-center gap-2 sm:col-span-2"><input type="checkbox" aria-label="Must be used in the film" checked={!!p.must} onChange={e => run(() => api.setPhotoMust(folder, p.id, e.target.checked))} /> <span>Must be used in the film <span className="text-xs text-stone-500">(added where it falls in the race if the script leaves it out; otherwise it is only an option)</span></span></label>
      </>}
      help={m.seconds != null ? 'The film shows this photo for exactly this long; the music fit never changes it.' : 'The plan sets the length to fit the music, 2 to 3 s by how busy the photo is. Left to the planner, the move follows the shape of the photo and what is in it.'} />
  )
}
