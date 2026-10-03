import { useEffect, useState } from 'react'
import { api, type MotionPlan, type MotionSettings, type MotionStyle, type Photo } from '../api'

// The pan and zoom for a photo, so it can be used in the film like a shot: choose the move (or leave it to "auto", which looks at the shape of the photo and what is in it), how long it lasts and a shuffle for another take;
// the start (green) and end (red) windows are drawn on the picture, and "Watch" plays the move. "Use this move" keeps the choice for the photo.
const STYLES: Record<MotionStyle, string> = { push_in: 'push in', pull_out: 'pull out', pan: 'pan across', drift: 'drift', reveal: 'reveal', hold: 'hold' }
export default function PhotoMotion({ folder, p, onChanged }: { folder: string; p: Photo; onChanged: () => void }) {
  const saved: MotionSettings = p.motion ?? { style: 'auto', seconds: null, seed: 0 }
  const [open, setOpen] = useState(false), [s, setS] = useState<MotionSettings>(saved), [plan, setPlan] = useState<MotionPlan>(), [err, setErr] = useState<string>(), [watch, setWatch] = useState(false), [secText, setSecText] = useState(saved.seconds == null ? '' : String(saved.seconds))
  useEffect(() => { const m = p.motion ?? { style: 'auto', seconds: null, seed: 0 }; setS(m); setSecText(m.seconds == null ? '' : String(m.seconds)) }, [p.motion?.style, p.motion?.seconds, p.motion?.seed])           // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!open) return; let live = true; setErr(undefined)
    api.photoMotion(folder, p.id, s).then(r => live && setPlan(r)).catch(e => live && setErr((e as Error).message)); return () => { live = false }
  }, [open, folder, p.id, s.style, s.seconds, s.seed])
  const changed = s.style !== saved.style || s.seconds !== saved.seconds || s.seed !== saved.seed
  const use = async () => { try { await api.saveMotion(folder, p.id, s); onChanged() } catch (e) { setErr((e as Error).message) } }
  const rect = (w: number[] | undefined, colour: string) => w ? <rect x={w[0] * 100} y={w[1] * 100} width={w[2] * 100} height={w[3] * 100} fill="none" stroke={colour} strokeWidth="1.2" vectorEffect="non-scaling-stroke" /> : null
  const [a, b] = plan?.windows ?? []
  return (
    <div data-motion={p.id} className="text-xs">
      <button className="text-emerald-700 underline dark:text-emerald-400" aria-expanded={open} onClick={() => { setOpen(!open); setWatch(false) }}>Pan &amp; zoom{p.motion ? `: ${p.motion.style === 'auto' ? 'auto' : STYLES[p.motion.style]}, ${p.motion.seconds == null ? 'auto length' : `${p.motion.seconds} s`}` : ''}</button>
      {open && (
        <div className="mt-1 space-y-1.5 rounded border border-stone-200 p-2 dark:border-stone-700">
          <div className="flex flex-wrap items-center gap-2">
            <select aria-label={`Move for ${p.name}`} value={s.style} onChange={e => { setWatch(false); setS({ ...s, style: e.target.value as MotionSettings['style'] }) }} className="rounded border border-stone-300 bg-transparent px-1 py-0.5 dark:border-stone-700">
              <option value="auto">auto</option>{(Object.keys(STYLES) as MotionStyle[]).map(k => <option key={k} value={k}>{STYLES[k]}</option>)}
            </select>
            <input aria-label={`Seconds for ${p.name}`} type="number" min={2} max={8} step={0.5} placeholder="auto" title="Leave empty: 2 s for a plain picture up to 3 s for a busy one" value={secText} onChange={e => { setSecText(e.target.value); const v = Number(e.target.value); if (e.target.value.trim() === '') { setWatch(false); setS({ ...s, seconds: null }) } else if (Number.isFinite(v) && v >= 2 && v <= 8) { setWatch(false); setS({ ...s, seconds: v }) } }} className="w-16 rounded border border-stone-300 bg-transparent px-1 py-0.5 dark:border-stone-700" /> s{s.seconds == null && plan ? ` (auto: ${plan.duration_s} s)` : ''}
            <button aria-label={`Another take for ${p.name}`} title="Another take: the same style aimed or ordered differently" className="rounded border border-stone-300 px-1.5 py-0.5 dark:border-stone-700" onClick={() => { setWatch(false); setS({ ...s, seed: s.seed + 1 }) }}>⟳</button>
          </div>
          {err && <p role="alert" className="text-red-600">{err}</p>}
          {plan && (
            <>
              <div className="relative w-56">
                <img src={api.photoThumb(folder, p.id, 480)} alt="" className="w-56 rounded" />
                <svg viewBox="0 0 100 100" preserveAspectRatio="none" className="absolute inset-0 h-full w-full" aria-label="Path of the move">
                  {a && b && <line x1={(a[0] + a[2] / 2) * 100} y1={(a[1] + a[3] / 2) * 100} x2={(b[0] + b[2] / 2) * 100} y2={(b[1] + b[3] / 2) * 100} stroke="#facc15" strokeWidth="1.2" vectorEffect="non-scaling-stroke" strokeDasharray="3 2" />}
                  {rect(a, '#22c55e')}{rect(b, '#ef4444')}
                </svg>
              </div>
              <div className="text-stone-500">{STYLES[plan.style]} · from the green window to the red one · zoom up to {plan.zmax.toFixed(2)}x · aimed at {plan.subjects.slice(0, 2).map(x => x.label).join(', ')}</div>
              <div className="flex items-center gap-3">
                <button className="text-emerald-700 underline dark:text-emerald-400" onClick={() => setWatch(!watch)}>{watch ? 'Hide' : 'Watch'}</button>
                <button disabled={!changed} className="rounded bg-emerald-700 px-2 py-0.5 text-white disabled:opacity-40" onClick={use}>Use this move</button>
              </div>
              {watch && <video aria-label={`Move for ${p.name}`} className="w-72 rounded" controls autoPlay loop src={api.photoMotionVideo(folder, p.id, { style: plan.style, seconds: plan.duration_s, seed: s.seed })} />}
            </>
          )}
        </div>
      )}
    </div>
  )
}
