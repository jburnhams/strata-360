import { useState } from 'react'
import { api, type Gap, type GapClip, type GapKind, type GapSettings, type Photo } from '../api'
import PhotoStrip from './PhotoStrip'
import { usePoll } from '../usePoll'
import NoteBox from './NoteBox'
import { PanelSkeleton } from './Skeleton'

// A gap in the footage as a page of its own, like a clip: the preview of its generated clip, how it is drawn (2D map or 3D flyover, or left to the planner) and how long it is (set exactly, or at least),
// whether the film must use it, what the script says over it, and your notes with the voice-over you want inside it (they go to the script writer like a clip's).
const KIND: Record<GapKind, string> = { map: '2D map', flyover: '3D flyover (4K)' }
const Card = ({ title, children }: { title: string; children: React.ReactNode }) => (
  <section className="rounded-xl border border-stone-200 bg-white p-4 dark:border-stone-800 dark:bg-stone-900"><h3 className="mb-2 text-sm font-semibold">{title}</h3>{children}</section>
)
export default function GapView({ folder, gap, photos, tz = 'Europe/Brussels', onPhotosChanged }: { folder: string; gap: string; photos?: Photo[]; tz?: string; onPhotosChanged?: () => void }) {
  const [tick, setTick] = useState(0)
  const data = usePoll(() => api.gaps(folder), 4000, [folder, gap, tick])
  const [err, setErr] = useState<string>()
  const [draft, setDraft] = useState<{ gap: string; seconds: string }>()
  if (!data) return <div className="space-y-4"><PanelSkeleton title="Gap" rows={4} /></div>
  const g: Gap | undefined = data.gaps.find(x => x.id === gap)
  if (!g) return <p className="text-stone-500">No gap {gap}: the gaps are found from the clips on the race track.</p>
  const c: GapClip | undefined = g.clips.find(x => x.id === g.id)
  const s: GapSettings = g.settings ?? { kind: null, mode: null, seconds: null, must: false }
  const flyover = data.flyover ?? { available: true, note: '' }
  const run = async (fn: () => Promise<unknown>) => { setErr(undefined); try { await fn() } catch (e) { setErr((e as Error).message) } setTick(t => t + 1) }
  const save = (fields: Partial<GapSettings>) => run(() => api.setGapSettings(folder, g.id, fields))
  const secondsText = draft?.gap === g.id ? draft.seconds : s.seconds != null ? String(s.seconds) : ''
  const commitSeconds = () => { if (draft?.gap !== g.id) return; const v = Number(draft.seconds); setDraft(undefined); if (Number.isFinite(v) && draft.seconds.trim() !== '' && v !== s.seconds) save({ seconds: v }) }
  const setMode = (mode: 'set' | 'min' | '') => save(mode ? { mode, seconds: s.seconds ?? c?.seconds ?? g.default_seconds } : { mode: null, seconds: null })
  const kind: GapKind = s.kind ?? (c?.kind === 'flyover' ? 'flyover' : 'map')
  const generate = () => run(async () => {
    const sec = s.mode && s.seconds ? s.seconds : c?.seconds ?? g.default_seconds
    const made = await api.planGapClip(folder, g.id, sec, kind)
    const r = await api.renderGapClip(folder, made.id); if (!r.started) throw new Error(r.reason || 'could not start')
  })
  const state = c ? (c.rendering ? (c.progress || 'rendering…') : c.error ? `failed: ${c.error}` : c.exists ? `ready · ${c.kind === 'flyover' ? '3D · ' : '2D · '}${c.seconds} s for ${(c.duration_s / 3600).toFixed(1)} h (x${c.speedup})` : 'planned, not rendered yet') : 'no clip yet'
  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-lg font-semibold">Gap {g.id} <span className="text-sm font-normal text-stone-500">{g.local_start} → {g.local_end}</span></h2>
        <p className="text-sm text-stone-500">{(g.duration_s / 3600).toFixed(1)} h · km {g.km_start}–{g.km_end} · +{g.ascent_m} m{g.daylight ? ` · ${g.daylight}` : ''} · {Math.round(100 * g.moving_share)}% moving</p>
      </div>
      {err && <p role="alert" className="text-sm text-red-600">{err}</p>}
      <Card title="Preview">
        {c?.exists ? <video aria-label={`${g.id} ${c.kind === 'flyover' ? 'flyover' : 'map clip'}`} className="w-full max-w-3xl rounded" controls src={api.gapVideoUrl(folder, c.id)} />
          : <div className="flex aspect-video w-full max-w-3xl items-center justify-center rounded bg-stone-200 text-sm text-stone-500 dark:bg-stone-800">{c?.rendering ? (c.progress || 'rendering…') : 'No clip rendered yet'}</div>}
        <div className="mt-2 flex flex-wrap items-center gap-3 text-sm">
          <span className={c?.error && !c.rendering ? 'text-red-600' : 'text-stone-500'} aria-label="State">{state}</span>
          <button disabled={!!c?.rendering} className="rounded bg-emerald-700 px-3 py-1 text-white disabled:opacity-50" onClick={generate}>{c?.exists ? 'Regenerate' : kind === 'flyover' ? 'Generate 3D flyover' : 'Generate map clip'}</button>
          {c && !c.rendering && <button aria-label={`Remove the ${g.id} clip`} className="text-stone-500 underline" onClick={() => run(() => api.deleteGapClip(folder, c.id))}>Remove clip</button>}
        </div>
      </Card>
      <Card title="How it is drawn and how long it is">
        <div className="grid gap-3 text-sm sm:grid-cols-2">
          <label className="flex items-center gap-2"><span className="w-24 text-stone-500">Drawn as</span>
            <select aria-label="Drawn as" value={s.kind ?? ''} disabled={!!c?.rendering} onChange={e => save({ kind: (e.target.value || null) as GapKind | null })} className="rounded border border-stone-300 bg-transparent px-1 py-0.5 dark:border-stone-700">
              <option value="">the planner chooses</option><option value="map">{KIND.map}</option>
              <option value="flyover" disabled={!flyover.available} title={flyover.note || undefined}>{KIND.flyover}{flyover.available ? '' : ' (not installed)'}</option>
            </select></label>
          <div className="flex items-center gap-2"><span className="w-24 text-stone-500">Length</span>
            <select aria-label="Length" value={s.mode ?? ''} onChange={e => setMode(e.target.value as 'set' | 'min' | '')} className="rounded border border-stone-300 bg-transparent px-1 py-0.5 dark:border-stone-700">
              <option value="">the plan decides</option><option value="set">exactly</option><option value="min">at least</option>
            </select>
            <input aria-label="Length in seconds" type="number" min={2} max={45} step={1} disabled={!s.mode} value={secondsText} onChange={e => setDraft({ gap: g.id, seconds: e.target.value })} onBlur={commitSeconds} onKeyDown={e => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur() }}
              className="w-16 rounded border border-stone-300 bg-transparent px-1 py-0.5 disabled:opacity-40 dark:border-stone-700" /> <span className="text-xs text-stone-500">s</span></div>
          <label className="flex items-center gap-2 sm:col-span-2"><input type="checkbox" aria-label="Must be used in the film" checked={s.must} onChange={e => save({ must: e.target.checked })} /> <span>Must be used in the film <span className="text-xs text-stone-500">(added where it falls in the race if the script leaves it out)</span></span></label>
        </div>
        <p className="mt-2 text-xs text-stone-500">{s.mode === 'set' ? 'The film shows this gap for exactly this long; the music fit never changes it.' : s.mode === 'min' ? 'The film shows this gap for at least this long; the music fit may make it longer, never shorter.' : 'The plan sets the length to fit the music (the script may name one).'} {s.kind ? 'The kind you chose is kept.' : 'Left to the planner, the kind follows the land (a big climb or descent gets a flyover).'}</p>
      </Card>
      <Card title="Voice-over">
        {(g.script ?? []).length === 0 ? <p className="text-sm text-stone-500">The newest script draft does not use this gap{s.must ? ' (it is marked must-use, so the plan adds it)' : ''}.</p>
          : <ul className="space-y-1 text-sm">{(g.script ?? []).map(it => (
            <li key={it.n}><span className="mr-2 font-mono text-xs text-stone-500">item {it.n} · {it.type}{it.seconds ? ` · ${it.seconds} s` : ''}</span>{it.text || <span className="text-stone-500">picture only</span>}</li>))}</ul>}
        <p className="mt-2 text-xs text-stone-500">Narration you want spoken inside this gap goes in “Voice-over MUST INCLUDE” below.</p>
      </Card>
      <PhotoStrip folder={folder} photos={photos} tz={tz} kind="gap" id={g.id} onChanged={onPhotosChanged} />
      <NoteBox folder={folder} clip={g.id} title="Notes for this gap" placeholder="What was this stretch? Where were you, how did it feel, what to mention or avoid…" />
    </div>
  )
}
