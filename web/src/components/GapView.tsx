import { useState } from 'react'
import { api, type Gap, type GapClip, type GapKind, type GapSettings } from '../api'
import { usePoll } from '../usePoll'
import ItemPage, { Card, LengthField } from './ItemPage'
import TrackMap from './TrackMap'
import { PanelSkeleton } from './Skeleton'
import StepVideo from './FrameStep'

// A gap in the footage as a page of its own, like a clip: the preview of its generated clip, how it is drawn (2D map or 3D flyover, or left to the planner) and how long it is (set exactly, or at least),
// whether the film must use it, what the script says over it, and your notes with the voice-over you want inside it (they go to the script writer like a clip's).
const KIND: Record<GapKind, string> = { map: '2D map', flyover: '3D flyover (4K)' }
export default function GapView({ folder, gap, tz }: { folder: string; gap: string; tz?: string }) {
  const [tick, setTick] = useState(0)
  const data = usePoll(() => api.gaps(folder), 4000, [folder, gap, tick])
  const [err, setErr] = useState<string>()
  if (!data) return <div className="space-y-4"><PanelSkeleton title="Gap" rows={4} /></div>
  const g: Gap | undefined = data.gaps.find(x => x.id === gap)
  if (!g) return <p className="text-stone-500">No gap {gap}: the gaps are found from the clips on the race track.</p>
  const c: GapClip | undefined = g.clips.find(x => x.id === g.id)
  const s: GapSettings = g.settings ?? { kind: null, mode: null, seconds: null, must: false }
  const flyover = data.flyover ?? { available: true, note: '' }
  const run = async (fn: () => Promise<unknown>) => { setErr(undefined); try { await fn() } catch (e) { setErr((e as Error).message) } setTick(t => t + 1) }
  const save = (fields: Partial<GapSettings>) => run(() => api.setGapSettings(folder, g.id, fields))
  const kind: GapKind = s.kind ?? (c?.kind === 'flyover' ? 'flyover' : 'map')
  const generate = () => run(async () => {
    const sec = s.mode && s.seconds ? s.seconds : c?.seconds ?? g.default_seconds
    const made = await api.planGapClip(folder, g.id, sec, kind)
    const r = await api.renderGapClip(folder, made.id); if (!r.started) throw new Error(r.reason || 'could not start')
  })
  const state = c ? (c.rendering ? (c.progress || 'rendering…') : c.error ? `failed: ${c.error}` : c.exists ? `ready · ${c.kind === 'flyover' ? '3D · ' : '2D · '}${c.seconds} s for ${(c.duration_s / 3600).toFixed(1)} h (x${c.speedup})` : 'planned, not rendered yet') : 'no clip yet'
  return (
    <ItemPage folder={folder} noun="gap" must={s.must} script={g.script ?? []} err={err} noteClip={g.id} noteTitle="Notes for this gap" notePlaceholder="What was this stretch? Where were you, how did it feel, what to mention or avoid…"
      heading={<>{g.stop ? 'Stop' : 'Gap'} {g.id} <span className="text-sm font-normal text-stone-500">{g.local_start} → {g.local_end}</span></>}
      sub={`${(g.duration_s / 3600).toFixed(1)} h · km ${g.km_start}–${g.km_end} · +${g.ascent_m} m${g.daylight ? ` · ${g.daylight}` : ''} · ${Math.round(100 * g.moving_share)}% moving`}
      more={g.stop ? <StopCard folder={folder} stop={g.stop} tz={tz ?? 'Europe/Brussels'} onChanged={() => setTick(t => t + 1)} /> : undefined}
      where={<TrackMap folder={folder} tz={tz} span={[g.t0, g.t1]} label={`Gap ${g.id}`} />}
      preview={<>
        {c?.exists ? <StepVideo aria-label={`${g.id} ${c.kind === 'flyover' ? 'flyover' : 'map clip'}`} className="w-full max-w-3xl rounded" src={api.gapVideoUrl(folder, c.id)} />
          : <div className="flex aspect-video w-full max-w-3xl items-center justify-center rounded bg-stone-200 text-sm text-stone-500 dark:bg-stone-800">{c?.rendering ? (c.progress || 'rendering…') : 'No clip rendered yet'}</div>}
        <div className="mt-2 flex flex-wrap items-center gap-3 text-sm">
          <span className={c?.error && !c.rendering ? 'text-red-600' : 'text-stone-500'} aria-label="State">{state}</span>
          <button disabled={!!c?.rendering} className="rounded bg-emerald-700 px-3 py-1 text-white disabled:opacity-50" onClick={generate}>{c?.exists ? 'Regenerate' : kind === 'flyover' ? 'Generate 3D flyover' : 'Generate map clip'}</button>
          {c && !c.rendering && <button aria-label={`Remove the ${g.id} clip`} className="text-stone-500 underline" onClick={() => run(() => api.deleteGapClip(folder, c.id))}>Remove clip</button>}
        </div>
</>}
      settings={<>
          <label className="flex items-center gap-2"><span className="w-24 text-stone-500">Drawn as</span>
            <select aria-label="Drawn as" value={s.kind ?? ''} disabled={!!c?.rendering} onChange={e => save({ kind: (e.target.value || null) as GapKind | null })} className="rounded border border-stone-300 bg-transparent px-1 py-0.5 dark:border-stone-700">
              <option value="">the planner chooses</option><option value="map">{KIND.map}</option>
              <option value="flyover" disabled={!flyover.available} title={flyover.note || undefined}>{KIND.flyover}{flyover.available ? '' : ' (not installed)'}</option>
            </select></label>
          <LengthField id={g.id} mode={s.mode ?? ''} seconds={s.seconds} modes={['set', 'min']} min={2} max={45} fallback={c?.seconds ?? g.default_seconds} onChange={(mode, seconds) => save(mode ? { mode, seconds } : { mode: null, seconds: null })} />
          <label className="flex items-center gap-2 sm:col-span-2"><input type="checkbox" aria-label="Must be used in the film" checked={s.must} onChange={e => save({ must: e.target.checked })} /> <span>Must be used in the film <span className="text-xs text-stone-500">(added where it falls in the race if the script leaves it out)</span></span></label>
      </>}
      help={(s.mode === 'set' ? 'The film shows this gap for exactly this long; the music fit never changes it.' : s.mode === 'min' ? 'The film shows this gap for at least this long; the music fit may make it longer, never shorter.' : 'The plan sets the length to fit the music (the script may name one).') + ' ' + (s.kind ? 'The kind you chose is kept.' : 'Left to the planner, the kind follows the land (a big climb or descent gets a flyover).')} />
  )
}

const clock = (t: number, tz: string) => { try { return new Intl.DateTimeFormat('en-GB', { timeZone: tz, weekday: 'short', day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', hour12: false }).format(new Date(t * 1000)).replace(',', '') } catch { return '' } }
const mins = (s: number) => (s >= 3600 ? `${Math.floor(s / 3600)} h ${String(Math.round((s % 3600) / 60)).padStart(2, '0')} min` : `${Math.round(s / 60)} min`)

/** The facts of a stop that was added to the video as this gap: the clip covers the stop and a little of the arriving and the leaving. */
function StopCard({ folder, stop, tz, onChanged }: { folder: string; stop: NonNullable<Gap['stop']>; tz: string; onChanged: () => void }) {
  return (
    <Card title="The stop">
      <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-0.5 text-sm">
        <dt className="text-stone-500">Stopped</dt><dd>{mins(stop.stopped_s)}, within {stop.radius_m} m</dd>
        <dt className="text-stone-500">From</dt><dd>{clock(stop.arrived, tz)}</dd><dt className="text-stone-500">To</dt><dd>{clock(stop.left, tz)}</dd>
        <dt className="text-stone-500">Where</dt><dd>km {stop.km} of the run</dd>
        <dt className="text-stone-500">The clip</dt><dd>starts {mins(stop.pad_s)} before the stop and ends {mins(stop.pad_s)} after it, to show arriving and leaving</dd>
      </dl>
      <button type="button" className="mt-2 text-xs text-stone-500 underline" onClick={async () => { await api.setStop(folder, stop.key, false).catch(() => {}); onChanged() }}>Take this stop out of the video</button>
    </Card>
  )
}
