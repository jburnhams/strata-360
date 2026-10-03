import { useState } from 'react'
import { api, type MotionStyle, type Photo } from '../api'
import NoteBox from './NoteBox'
import PhotoMotion from './PhotoMotion'

// A photo used in the film as a page of its own, with the same sections as a gap: the picture and its move, how it is drawn and how long it is, whether the film must use it, what the script says over it, and your notes with the
// voice-over you want inside it. "Use in the film" on the overview only makes a photo an option (it is then in the film list); "Must be used" here makes the plan add it if the script leaves it out.
const STYLES: Record<MotionStyle, string> = { push_in: 'push in', pull_out: 'pull out', pan: 'pan across', drift: 'drift', reveal: 'reveal', hold: 'hold' }
const Card = ({ title, children }: { title: string; children: React.ReactNode }) => (
  <section className="rounded-xl border border-stone-200 bg-white p-4 dark:border-stone-800 dark:bg-stone-900"><h3 className="mb-2 text-sm font-semibold">{title}</h3>{children}</section>
)
export default function PhotoPage({ folder, photo, tz, onChanged }: { folder: string; photo?: Photo; tz: string; onChanged: () => void }) {
  const [err, setErr] = useState<string>(), [draft, setDraft] = useState<string>()
  if (!photo) return <p className="text-sm text-stone-500">That photo is not there any more.</p>
  const p = photo, label = p.id.toUpperCase(), m = p.motion ?? { style: 'auto' as const, seconds: null, seed: 0 }
  const run = async (fn: () => Promise<unknown>) => { setErr(undefined); try { await fn() } catch (e) { setErr((e as Error).message) } onChanged() }
  const secondsText = draft ?? (m.seconds != null ? String(m.seconds) : '')
  const commit = () => { if (draft === undefined) return; const v = Number(draft); setDraft(undefined); if (Number.isFinite(v) && draft.trim() !== '' && v !== m.seconds) run(() => api.saveMotion(folder, p.id, { ...m, seconds: v })) }
  const when = new Intl.DateTimeFormat('en-GB', { timeZone: tz, weekday: 'short', day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', hour12: false }).format(new Date(p.taken_utc * 1000)).replace(',', '')
  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-lg font-semibold">Photo {label} <span className="text-sm font-normal text-stone-500">{when}</span></h2>
        <p className="text-sm text-stone-500">{p.name}{p.track ? ` · km ${p.track.km}` : ''}{p.analysis?.place ? ` · ${p.analysis.place}` : ''}</p>
      </div>
      {err && <p role="alert" className="text-sm text-red-600">{err}</p>}
      <Card title="Preview">
        <a href={api.photoFile(folder, p.id)} target="_blank" rel="noreferrer"><img src={api.photoThumb(folder, p.id, 960)} alt={p.name} className="w-full max-w-3xl rounded" /></a>
        <div className="mt-2"><PhotoMotion folder={folder} p={p} onChanged={onChanged} /></div>
      </Card>
      <Card title="How it is drawn and how long it is">
        <div className="grid gap-3 text-sm sm:grid-cols-2">
          <label className="flex items-center gap-2"><span className="w-24 text-stone-500">Drawn as</span>
            <select aria-label="Drawn as" value={m.style === 'auto' ? '' : m.style} onChange={e => run(() => api.saveMotion(folder, p.id, { ...m, style: (e.target.value || 'auto') as MotionStyle | 'auto' }))} className="rounded border border-stone-300 bg-transparent px-1 py-0.5 dark:border-stone-700">
              <option value="">the planner chooses</option>{(Object.keys(STYLES) as MotionStyle[]).map(k => <option key={k} value={k}>{STYLES[k]}</option>)}
            </select></label>
          <div className="flex items-center gap-2"><span className="w-24 text-stone-500">Length</span>
            <select aria-label="Length" value={m.seconds == null ? '' : 'set'} onChange={e => run(() => api.saveMotion(folder, p.id, { ...m, seconds: e.target.value ? 2.5 : null }))} className="rounded border border-stone-300 bg-transparent px-1 py-0.5 dark:border-stone-700">
              <option value="">the plan decides</option><option value="set">exactly</option>
            </select>
            <input aria-label="Length in seconds" type="number" min={2} max={8} step={0.5} disabled={m.seconds == null} value={secondsText} onChange={e => setDraft(e.target.value)} onBlur={commit} onKeyDown={e => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur() }}
              className="w-16 rounded border border-stone-300 bg-transparent px-1 py-0.5 disabled:opacity-40 dark:border-stone-700" /> <span className="text-xs text-stone-500">s</span></div>
          <label className="flex items-center gap-2 sm:col-span-2"><input type="checkbox" aria-label="Must be used in the film" checked={!!p.must} onChange={e => run(() => api.setPhotoMust(folder, p.id, e.target.checked))} /> <span>Must be used in the film <span className="text-xs text-stone-500">(added where it falls in the race if the script leaves it out; otherwise it is only an option)</span></span></label>
        </div>
        <p className="mt-2 text-xs text-stone-500">{m.seconds != null ? 'The film shows this photo for exactly this long; the music fit never changes it.' : 'The plan sets the length to fit the music, 2 to 3 s by how busy the photo is. Left to the planner, the move follows the shape of the photo and what is in it.'}</p>
      </Card>
      <Card title="Voice-over">
        {(p.script ?? []).length === 0 ? <p className="text-sm text-stone-500">The newest script draft does not use this photo{p.must ? ' (it is marked must-use, so the plan adds it)' : ''}.</p>
          : <ul className="space-y-1 text-sm">{(p.script ?? []).map(it => (
            <li key={it.n}><span className="mr-2 font-mono text-xs text-stone-500">item {it.n} · {it.type}{it.seconds ? ` · ${it.seconds} s` : ''}</span>{it.text || <span className="text-stone-500">picture only</span>}</li>))}</ul>}
        <p className="mt-2 text-xs text-stone-500">Narration you want spoken inside this photo goes in “Voice-over MUST INCLUDE” below.</p>
      </Card>
      <NoteBox folder={folder} clip={label} title="Notes for this photo" placeholder="What was this? Where were you, what to mention or avoid…" />
    </div>
  )
}
