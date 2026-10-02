import { useState } from 'react'
import { api, type Gap, type GapClip } from '../api'
import { usePoll } from '../usePoll'

// The stretches of the race with no camera clip, and the animated map clip that can fill each one: choose how long it is in the film, generate it (the map follows the runner at a speed-up with the race
// overlay on top), watch it, and use it in the script as a clip labelled with the gap's name (G01 ...).
export default function GapsPanel({ folder }: { folder: string }) {
  const [tick, setTick] = useState(0)
  const data = usePoll(() => api.gaps(folder), 4000, [folder, tick])
  const [seconds, setSeconds] = useState<Record<string, string>>({})
  const [err, setErr] = useState<string>()
  const [open, setOpen] = useState<string>()
  if (!data) return null
  if (!data.gaps.length) return <p className="mt-3 text-sm text-stone-500">No gaps of 20 minutes or more between the clips on the track.</p>
  const run = async (fn: () => Promise<unknown>) => { setErr(undefined); try { await fn() } catch (e) { setErr((e as Error).message) } setTick(t => t + 1) }
  const generate = (g: Gap) => run(async () => {
    const s = Number(seconds[g.id] ?? g.default_seconds)
    const c = await api.planGapClip(folder, g.id, s)
    const r = await api.renderGapClip(folder, c.id)
    if (!r.started) throw new Error(r.reason || 'could not start')
  })
  const hours = (g: Gap) => `${(g.duration_s / 3600).toFixed(1)} h`
  const state = (c: GapClip) => c.rendering ? (c.progress || 'rendering…') : c.exists ? `ready · ${c.seconds} s for ${(c.duration_s / 3600).toFixed(1)} h (x${c.speedup})` : 'planned'
  return (
    <div className="mt-4">
      <div className="mb-1 flex items-baseline gap-2"><b>Gaps in the footage</b><span className="text-xs text-stone-500">{data.gaps.length} · a map clip can fill each one</span></div>
      {err && <p role="alert" className="mb-1 text-sm text-red-600">{err}</p>}
      <ul className="divide-y divide-stone-200 rounded-lg border border-stone-200 text-sm dark:divide-stone-800 dark:border-stone-800">
        {data.gaps.map(g => {
          const c = g.clips.find(x => x.id === g.id)
          return (
            <li key={g.id} className="p-2">
              <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                <b className="w-10">{g.id}</b>
                <span>{g.local_start} → {g.local_end}</span>
                <span className="text-stone-500">{hours(g)} · km {g.km_start}–{g.km_end} · +{g.ascent_m} m{g.daylight ? ` · ${g.daylight}` : ''}</span>
                <span className="ml-auto flex items-center gap-2">
                  {c && <span className="text-xs text-stone-500" aria-label={`${g.id} state`}>{state(c)}</span>}
                  <label className="flex items-center gap-1 text-xs text-stone-500">seconds
                    <input aria-label={`Seconds for ${g.id}`} type="number" min={2} step={1} className="w-16 rounded border border-stone-300 bg-transparent px-1 py-0.5 dark:border-stone-700"
                      value={seconds[g.id] ?? String(c?.seconds ?? g.default_seconds)} onChange={e => setSeconds({ ...seconds, [g.id]: e.target.value })} />
                  </label>
                  <button disabled={!!c?.rendering} className="rounded bg-emerald-700 px-2 py-1 text-white disabled:opacity-50" onClick={() => generate(g)}>{c?.exists ? 'Regenerate' : 'Generate map clip'}</button>
                  {c?.exists && <button className="text-emerald-700 underline dark:text-emerald-400" onClick={() => setOpen(open === g.id ? undefined : g.id)}>{open === g.id ? 'Hide' : 'Watch'}</button>}
                  {c && !c.rendering && <button aria-label={`Remove ${g.id} clip`} className="text-stone-500 underline" onClick={() => run(() => api.deleteGapClip(folder, c.id))}>Remove</button>}
                </span>
              </div>
              {open === g.id && c?.exists && <video aria-label={`${g.id} map clip`} className="mt-2 w-full max-w-2xl rounded" controls src={api.gapVideoUrl(folder, c.id)} />}
            </li>
          )
        })}
      </ul>
    </div>
  )
}
