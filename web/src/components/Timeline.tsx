import FilmPreview from './FilmPreview'
import FinalRender from './FinalRender'
import { useEffect, useMemo, useRef, useState } from 'react'
import { api, type ClipInfo, type EditResponse, type PlanSegment, type RampReport } from '../api'
import FilmStrip, { colour } from './FilmStrip'
import TimelineMap from './TimelineMap'
import { PanelSkeleton } from './Skeleton'
import VoiceTrack from './VoiceTrack'
import WindowPlayer from './WindowPlayer'
import { thumbVersion, useThumbOverlay } from '../thumbOverlay'

const mmss = (s: number) => `${Math.floor(s / 60)}:${(s % 60).toFixed(1).padStart(4, '0')}`
const short = (id: string) => id.replace(/^CAM_/, '').replace(/_D$/, '').slice(-9)
/** A speed ramp in words (edit/hyperlapse.py): how much running it races through, how fast, and whether it lands on the next window. */
const rampWhy = (g: PlanSegment) => g.ramp ? `a speed ramp: ${g.ramp.lead_s.toFixed(1)} s at real speed, then up to ${Math.round(g.ramp.speed)}x through ${Math.round(g.ramp.src_dur_s - g.dur_s)} s of quiet running${g.ramp.lands ? ', landing where the next window starts' : ''}${g.ramp_from ? ` (was ${g.ramp_from.replace(/_/g, ' ')}: a ramp follows your heading)` : ''}` : ''
const rampSummary = (r: RampReport[]) => `${r.length} speed ramp${r.length === 1 ? '' : 's'} through ${(r.reduce((a, x) => a + x.to_s - x.from_s, 0) / 60).toFixed(1)} min of running`

// The film as a chronological list of segments: what each clip contributes, with the technique that fits best, the script line, and the controls to change it.
export default function Timeline({ folder, clips, onOpenClip }: { folder: string; clips: ClipInfo[]; onOpenClip: (clip: string) => void }) {
  const [overlay] = useThumbOverlay()
  const [d, setD] = useState<EditResponse>()
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string>()
  const [length, setLength] = useState(90)
  const [bpm, setBpm] = useState(120)
  const [play, setPlay] = useState<PlanSegment>()
  const [sel, setSel] = useState<string>()
  const [range, setRange] = useState<[number, number] | null>(null)
  const [anchor, setAnchor] = useState<number>()
  const [note, setNote] = useState<string>()
  const rows = useRef<Record<string, HTMLTableRowElement | null>>({})
  const info = useMemo(() => Object.fromEntries(clips.map(c => [c.id, c])), [clips])
  const load = () => api.editGet(folder).then(r => { setD(r); setLength(r.edit.settings.length_s); setBpm(r.edit.settings.bpm) }).catch(e => setErr(e.message))
  useEffect(() => { load() }, [folder])   // eslint-disable-line react-hooks/exhaustive-deps

  const run = async <R extends { edit: EditResponse['edit'] }>(f: () => Promise<R>) => {
    setBusy(true); setErr(undefined); setNote(undefined)
    try { const r = await f(); setD(x => (x ? { ...x, edit: r.edit } : x)); await api.editGet(folder).then(setD); return r } catch (e) { setErr((e as Error).message) } finally { setBusy(false) }
  }
  if (!d) return err ? <p className="text-red-600">{err}</p> : <PanelSkeleton title="Timeline" rows={8} />
  const plan = d.edit.plan, s = d.edit.settings, ov = d.edit.overrides
  /** The beat planner's film replaces a film planned from the script: ask first (the script plan is rebuilt from the Film script panel). */
  const ownPlan = (f: () => Promise<{ edit: EditResponse['edit'] }>) => {
    if (plan?.source === 'script' && !window.confirm('The film is planned from your script. This replaces it with the beat planner\'s own arrangement of the clips (you can plan the script again from the Film script panel). Continue?')) return
    return run(f)
  }
  const total = plan?.film.length_s ?? 1
  const editable = !!plan && plan.source !== 'script'
  /** Select window k (shift: the run from the last selected window to k), and show its row. */
  const select = (k: number, extend: boolean) => {
    if (!plan) return
    const a = extend && anchor !== undefined && anchor < plan.segments.length ? anchor : k
    setRange([Math.min(a, k), Math.max(a, k)]); if (!extend) setAnchor(k)
    const g = plan.segments[k]; setSel(g.id); rows.current[g.id]?.scrollIntoView({ block: 'center', behavior: 'smooth' })
  }
  const moveEdge = (wid: string, beats: number) => run(() => api.override(folder, { action: 'edge', wid, beats })).then(r => { if (r?.note?.why) setNote(r.note.why) })
  const picked = plan && range ? plan.segments.slice(range[0], range[1] + 1) : []
  const input = 'w-20 rounded-lg border border-stone-300 bg-stone-50 px-2 py-1 text-sm dark:border-stone-700 dark:bg-stone-950'
  return (
    <div className="space-y-4">
      <FilmPreview folder={folder} />
      <FinalRender folder={folder} />
      <section className="rounded-xl border border-stone-200 bg-white p-4 dark:border-stone-800 dark:bg-stone-900">
        <h3 className="mb-2 text-sm font-semibold">Plan</h3>
        <div className="flex flex-wrap items-end gap-3 text-sm">
          <label>Film length (s)<input type="number" min={20} max={900} value={length} onChange={e => setLength(Number(e.target.value))} className={`${input} ml-2`} /></label>
          <label>Tempo (bpm)<input type="number" min={60} max={200} value={bpm} onChange={e => setBpm(Number(e.target.value))} className={`${input} ml-2`} /></label>
          <button disabled={busy} className="rounded-lg bg-emerald-700 px-4 py-2 text-white disabled:opacity-50" onClick={() => ownPlan(() => api.propose(folder, { length_s: length, bpm, keep: true, replace: true }))}>{plan ? 'Re-plan' : 'Propose a film'}</button>
          {plan && <button disabled={busy} className="rounded-lg border border-stone-300 px-3 py-2 disabled:opacity-50 dark:border-stone-700" title="a different arrangement of techniques (same moments)" onClick={() => ownPlan(() => api.propose(folder, { seed: s.seed + 1, keep: false, replace: true }))}>Another version</button>}
          {plan && <label className="flex items-center gap-1" title="long quiet running between two windows of a clip is raced through in a fast, stabilised hyperlapse instead of being cut out"><input type="checkbox" disabled={busy} checked={s.hyperlapse !== false} onChange={e => ownPlan(() => api.propose(folder, { hyperlapse: e.target.checked, keep: true, replace: true }))} />Speed ramps</label>}
          {(Object.keys(ov.tech_force).length + Object.keys(ov.transitions ?? {}).length + ov.locked.length + ov.bans_cands.length + ov.bans_techs.length + Object.keys(ov.clip_weight).length) > 0 &&
            <button disabled={busy} className="text-xs underline" onClick={() => run(() => api.override(folder, { action: 'reset' }))}>clear my changes</button>}
          {busy && <span className="text-stone-500">planning…</span>}
        </div>
        {plan && <p className="mt-2 text-xs text-stone-500">{plan.source === 'script' ? 'from the script draft · ' : ''}{plan.segments.length} segments from {plan.clips_in_plan} clips · {plan.film.length_s} s at {plan.film.bpm} bpm · version {s.seed} · {Object.keys(plan.technique_seconds).length} techniques
          {!!plan.hyperlapse?.length && <span> · {rampSummary(plan.hyperlapse)}</span>}
          {plan.missing_clips.length > 0 && <span className="text-amber-700"> · {plan.missing_clips.length} clip(s) not in the plan yet (still processing)</span>}</p>}
        {plan?.warnings.map(w => <p key={w} className="mt-1 text-xs text-amber-700">{w}</p>)}
        {!!plan?.orphaned_overrides.length && <p className="mt-1 text-xs text-amber-700">{plan.orphaned_overrides.length} of your changes no longer match a window and are not applied.</p>}
        {err && <p className="mt-2 text-sm text-red-600">{err}</p>}
      </section>

      {plan && (
        <>
          <VoiceTrack folder={folder} plan={plan} onChanged={load}>
          <FilmStrip segments={plan.segments} total={total} bpm={plan.film.bpm} editable={editable} busy={busy} range={range} onSelect={select} onMoveEdge={moveEdge} />
          </VoiceTrack>
          <div className="flex flex-wrap items-center gap-3 text-xs">
            {editable ? <>
              <button disabled={busy || !picked.length || picked.every(g => g.locked)} className="rounded-lg border border-stone-300 px-3 py-1.5 disabled:opacity-50 dark:border-stone-700"
                title="other moments and techniques for the selected windows (the locked ones and the rest of the film stay as they are)"
                onClick={() => run(() => api.override(folder, { action: 'suggest', wids: picked.map(g => g.id) }))}>{picked.length > 1 ? `Suggest again (${picked.length} windows)` : 'Suggest again'}</button>
              {!!d.edit.history && <button disabled={busy} className="rounded-lg border border-stone-300 px-3 py-1.5 disabled:opacity-50 dark:border-stone-700" title="back to the film before the last drag or suggestion"
                onClick={() => run(() => api.override(folder, { action: 'back' }))}>Step back ({d.edit.history})</button>}
              <span className="text-stone-500">{picked.length ? `${picked.length} selected · shift-click to select a run` : 'click a window to select it, shift-click for a run'} · drag a cut to move it by beats</span>
            </> : <span className="text-stone-500">The film is planned from your script: change it in the Film script panel.</span>}
            {note && <span className="text-amber-700">{note}</span>}
          </div>
          <TimelineMap folder={folder} segments={plan.segments} range={range} onSelect={select} />
          <div className="overflow-x-auto rounded-xl border border-stone-200 bg-white dark:border-stone-800 dark:bg-stone-900">
            <table className="w-full text-sm">
              <thead className="text-left text-xs text-stone-500"><tr><th className="p-2">film</th><th className="p-2">clip</th><th className="p-2">window</th><th className="p-2">technique</th><th className="p-2">into it</th><th className="p-2">lock</th><th className="p-2">more / less</th><th className="p-2">script</th></tr></thead>
              <tbody>
                {plan.segments.map(g => {
                  const c = info[g.clip], line = d.script[g.id], w = ov.clip_weight[g.clip] ?? 1, forced = !!ov.tech_force[g.id]
                  return (
                    <tr key={g.id} ref={el => { rows.current[g.id] = el }} className={`border-t border-stone-200 align-top dark:border-stone-800 ${sel === g.id ? 'bg-emerald-50 dark:bg-emerald-950/30' : ''}`}>
                      <td className="p-2 font-mono text-xs text-stone-500">{mmss(g.film_start_s)}<br />{g.dur_s}s</td>
                      <td className="p-2"><div className="flex items-center gap-2">
                        {c?.thumb ? <img loading="lazy" src={api.thumbUrl(folder, g.clip, thumbVersion(c, overlay), overlay)} alt="" className="h-9 w-16 cursor-pointer rounded object-cover" onClick={() => setPlay(g)} /> : <div className="h-9 w-16 rounded bg-stone-200 dark:bg-stone-800" />}
                        <button className="font-mono text-xs text-emerald-700 underline dark:text-emerald-400" onClick={() => onOpenClip(g.clip)}>{short(g.clip)}</button>
                        {g.role && <span className={`rounded-full px-2 text-xs ${g.role === 'vo' ? 'bg-sky-100 text-sky-800 dark:bg-sky-950 dark:text-sky-300' : g.role === 'clip' ? 'bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300' : 'bg-stone-200 text-stone-700 dark:bg-stone-800 dark:text-stone-300'}`} title="what this window is in the script: your own words, narration over the picture, or picture only">{g.role === 'vo' ? 'narration' : g.role === 'clip' ? 'you' : 'b-roll'}</span>}</div></td>
                      <td className="p-2 text-xs"><button className="underline" title="play this window" onClick={() => setPlay(g)}>▶ {mmss(g.clip_start_s)}–{mmss(g.clip_start_s + g.dur_s)}</button>{g.ramp && <div className="text-sky-700 dark:text-sky-300" title={rampWhy(g)}>⏩ ×{Math.round(g.ramp.speed)} to {mmss(g.clip_start_s + g.ramp.src_dur_s)}</div>}{g.forced && <div className="text-amber-700">no usable moment</div>}{g.kind && g.kind !== 'span' && <div className="text-stone-500" title="the way of seeing this footage the window was cut from">{g.kind === 'speech' ? 'you talk' : g.kind}</div>}{g.speech && <div title="you speak">💬</div>}</td>
                      <td className="p-2"><span className="mr-1 inline-block h-2.5 w-2.5 rounded-sm align-middle" style={{ background: colour(g) }} />
                        <select disabled={busy || g.locked} value={g.technique} onChange={e => run(() => api.override(folder, { action: 'technique', wid: g.id, technique: e.target.value }))}
                          className={`rounded border bg-transparent px-1 py-0.5 text-xs ${forced ? 'border-emerald-600' : 'border-stone-300 dark:border-stone-700'}`} title={forced ? 'set by you' : 'chosen by the planner'}>
                          {g.options.map(o => <option key={o.tech} value={o.tech}>{o.tech.replace(/_/g, ' ')}</option>)}</select>
                        {forced && <button className="ml-1 text-xs underline" onClick={() => run(() => api.override(folder, { action: 'technique', wid: g.id, technique: null }))}>auto</button>}</td>
                      <td className="p-2 text-xs"><select disabled={busy || g.index === 0} value={g.transition?.type ?? 'cut'} onChange={e => run(() => api.override(folder, { action: 'transition', wid: g.id, transition: e.target.value }))}
                          className="rounded border border-stone-300 bg-transparent px-1 py-0.5 text-xs dark:border-stone-700" title={g.transition?.why}>{['cut', 'dissolve', 'dip', 'whip'].map(x => <option key={x}>{x}</option>)}</select>
                        {ov.transitions?.[g.id] && <button className="ml-1 underline" onClick={() => run(() => api.override(folder, { action: 'transition', wid: g.id, transition: null }))}>auto</button>}</td>
                      <td className="p-2"><input type="checkbox" checked={g.locked} disabled={busy} title="keep exactly this window and technique when re-planning" onChange={e => run(() => api.override(folder, { action: 'lock', wid: g.id, locked: e.target.checked }))} /></td>
                      <td className="p-2 whitespace-nowrap text-xs">
                        <button disabled={busy} className="rounded border border-stone-300 px-1.5 dark:border-stone-700" title="less of this clip" onClick={() => run(() => api.override(folder, { action: 'weight', clip: g.clip, factor: w / 1.5 }))}>−</button>
                        <span className="mx-1 text-stone-500">{w === 1 ? '' : `×${w.toFixed(1)}`}</span>
                        <button disabled={busy} className="rounded border border-stone-300 px-1.5 dark:border-stone-700" title="more of this clip" onClick={() => run(() => api.override(folder, { action: 'weight', clip: g.clip, factor: w * 1.5 }))}>+</button>
                        <button disabled={busy} className="ml-2 text-stone-500 underline" title="never use this footage (whichever way of seeing it)" onClick={() => run(() => api.override(folder, { action: 'ban', kind: 'moment', key: `win:${g.clip}@${g.clip_start_s}@${+(g.clip_start_s + g.dur_s).toFixed(3)}`, on: true }))}>skip moment</button></td>
                      <td className="p-2 text-xs">{g.sound && <div className="mb-0.5 text-[11px] text-stone-500" title="the sound of this footage as classified, and the level the mix suggests for it">🔊 {g.sound.gain_db} dB · {g.sound.why.join(', ')}</div>}{line?.text ? <span>{line.text}</span> : line?.says?.length ? <span className="italic text-sky-700 dark:text-sky-300">💬 “{line.says.join(' … ')}”</span> : <span className="text-stone-400">—</span>}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
          <p className="text-xs text-stone-500">Techniques used: {Object.entries(plan.technique_seconds).sort((a, b) => b[1] - a[1]).map(([k, v]) => `${k.replace(/_/g, ' ')} ${Math.round(v)}s`).join(' · ')}</p>
        </>
      )}
      {play && <WindowPlayer folder={folder} clip={play.clip} start={play.clip_start_s} end={play.clip_start_s + play.dur_s} title={`${short(play.clip)} ${mmss(play.clip_start_s)}–${mmss(play.clip_start_s + play.dur_s)} · ${play.technique.replace(/_/g, ' ')}`} onClose={() => setPlay(undefined)} />}
    </div>
  )
}
