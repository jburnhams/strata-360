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
import { Button, NativeSelect, Tooltip } from 'strata-react'

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
  if (!d) return err ? <p className="text-danger">{err}</p> : <PanelSkeleton title="Timeline" rows={8} />
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
  const input = 'w-20 rounded-surface border border-border bg-card px-2 py-1 type-body-sm'
  return (
    <div className="space-y-4">
      <FilmPreview folder={folder} />
      <FinalRender folder={folder} />
      <section className="rounded-overlay border border-border bg-card p-4">
        <h3 className="mb-2 type-body-sm font-semibold">Plan</h3>
        <div className="flex flex-wrap items-end gap-3 type-body-sm">
          <label>Film length (s)<input type="number" min={20} max={900} value={length} onChange={e => setLength(Number(e.target.value))} className={`${input} ml-2`} /></label>
          <label>Tempo (bpm)<input type="number" min={60} max={200} value={bpm} onChange={e => setBpm(Number(e.target.value))} className={`${input} ml-2`} /></label>
          <Button variant="default" disabled={busy} onClick={() => ownPlan(() => api.propose(folder, { length_s: length, bpm, keep: true, replace: true }))}>{plan ? 'Re-plan' : 'Propose a film'}</Button>
          {plan && <Tooltip label="a different arrangement of techniques (same moments)"><Button disabled={busy} onClick={() => ownPlan(() => api.propose(folder, { seed: s.seed + 1, keep: false, replace: true }))}>Another version</Button></Tooltip>}
          {plan && <label className="flex items-center gap-1" title="long quiet running between two windows of a clip is raced through in a fast, stabilised hyperlapse instead of being cut out"><input type="checkbox" disabled={busy} checked={s.hyperlapse !== false} onChange={e => ownPlan(() => api.propose(folder, { hyperlapse: e.target.checked, keep: true, replace: true }))} />Speed ramps</label>}
          {(Object.keys(ov.tech_force).length + Object.keys(ov.transitions ?? {}).length + ov.locked.length + ov.bans_cands.length + ov.bans_techs.length + Object.keys(ov.clip_weight).length) > 0 &&
            <Button variant="link" size="sm" disabled={busy} onClick={() => run(() => api.override(folder, { action: 'reset' }))}>clear my changes</Button>}
          {busy && <span className="text-muted-foreground">planning…</span>}
        </div>
        {plan && <p className="mt-2 type-caption text-muted-foreground">{plan.source === 'script' ? 'from the script draft · ' : ''}{plan.segments.length} segments from {plan.clips_in_plan} clips · {plan.film.length_s} s at {plan.film.bpm} bpm · version {s.seed} · {Object.keys(plan.technique_seconds).length} techniques
          {!!plan.hyperlapse?.length && <span> · {rampSummary(plan.hyperlapse)}</span>}
          {plan.missing_clips.length > 0 && <span className="text-warning"> · {plan.missing_clips.length} clip(s) not in the plan yet (still processing)</span>}</p>}
        {plan?.warnings.map(w => <p key={w} className="mt-1 type-caption text-warning">{w}</p>)}
        {!!plan?.orphaned_overrides.length && <p className="mt-1 type-caption text-warning">{plan.orphaned_overrides.length} of your changes no longer match a window and are not applied.</p>}
        {err && <p className="mt-2 type-body-sm text-danger">{err}</p>}
      </section>

      {plan && (
        <>
          <VoiceTrack folder={folder} plan={plan} onChanged={load}>
          <FilmStrip segments={plan.segments} total={total} bpm={plan.film.bpm} editable={editable} busy={busy} range={range} onSelect={select} onMoveEdge={moveEdge} />
          </VoiceTrack>
          <div className="flex flex-wrap items-center gap-3 type-caption">
            {editable ? <>
              <Tooltip label="other moments and techniques for the selected windows (the locked ones and the rest of the film stay as they are)"><Button disabled={busy || !picked.length || picked.every(g => g.locked)}
               
                onClick={() => run(() => api.override(folder, { action: 'suggest', wids: picked.map(g => g.id) }))}>{picked.length > 1 ? `Suggest again (${picked.length} windows)` : 'Suggest again'}</Button></Tooltip>
              {!!d.edit.history && <Tooltip label="back to the film before the last drag or suggestion"><Button disabled={busy}
                onClick={() => run(() => api.override(folder, { action: 'back' }))}>Step back ({d.edit.history})</Button></Tooltip>}
              <span className="text-muted-foreground">{picked.length ? `${picked.length} selected · shift-click to select a run` : 'click a window to select it, shift-click for a run'} · drag a cut to move it by beats</span>
            </> : <span className="text-muted-foreground">The film is planned from your script: change it in the Film script panel.</span>}
            {note && <span className="text-warning">{note}</span>}
          </div>
          <TimelineMap folder={folder} segments={plan.segments} range={range} onSelect={select} />
          <div className="overflow-x-auto rounded-overlay border border-border bg-card">
            <table className="w-full type-body-sm">
              <thead className="text-left type-caption text-muted-foreground"><tr><th className="p-2">film</th><th className="p-2">clip</th><th className="p-2">window</th><th className="p-2">technique</th><th className="p-2">into it</th><th className="p-2">lock</th><th className="p-2">more / less</th><th className="p-2">script</th></tr></thead>
              <tbody>
                {plan.segments.map(g => {
                  const c = info[g.clip], line = d.script[g.id], w = ov.clip_weight[g.clip] ?? 1, forced = !!ov.tech_force[g.id]
                  return (
                    <tr key={g.id} ref={el => { rows.current[g.id] = el }} className={`border-t border-border align-top ${sel === g.id ? 'bg-primary-3' : ''}`}>
                      <td className="p-2 font-mono type-caption text-muted-foreground">{mmss(g.film_start_s)}<br />{g.dur_s}s</td>
                      <td className="p-2"><div className="flex items-center gap-2">
                        {c?.thumb ? <img loading="lazy" src={api.thumbUrl(folder, g.clip, thumbVersion(c, overlay), overlay)} alt="" className="h-9 w-16 cursor-pointer rounded-control object-cover" onClick={() => setPlay(g)} /> : <div className="h-9 w-16 rounded-control bg-muted" />}
                        <Button variant="link" size="sm" className="font-mono" onClick={() => onOpenClip(g.clip)}>{short(g.clip)}</Button>
                        {g.role && <span className={`rounded-pill px-2 type-caption ${g.role === 'vo' ? 'bg-info-subtle text-info' : g.role === 'clip' ? 'bg-primary-3 text-primary' : 'bg-muted text-foreground'}`} title="what this window is in the script: your own words, narration over the picture, or picture only">{g.role === 'vo' ? 'narration' : g.role === 'clip' ? 'you' : 'b-roll'}</span>}</div></td>
                      <td className="p-2 type-caption"><Tooltip label="play this window"><Button variant="link" onClick={() => setPlay(g)}>▶ {mmss(g.clip_start_s)}–{mmss(g.clip_start_s + g.dur_s)}</Button></Tooltip>{g.ramp && <div className="text-info" title={rampWhy(g)}>⏩ ×{Math.round(g.ramp.speed)} to {mmss(g.clip_start_s + g.ramp.src_dur_s)}</div>}{g.forced && <div className="text-warning">no usable moment</div>}{g.kind && g.kind !== 'span' && <div className="text-muted-foreground" title="the way of seeing this footage the window was cut from">{g.kind === 'speech' ? 'you talk' : g.kind}</div>}{g.speech && <div title="you speak">💬</div>}</td>
                      <td className="p-2"><span className="mr-1 inline-block h-2.5 w-2.5 rounded-control align-middle" style={{ background: colour(g) }} />
                        <select disabled={busy || g.locked} value={g.technique} onChange={e => run(() => api.override(folder, { action: 'technique', wid: g.id, technique: e.target.value }))}
                          className={`rounded-control border bg-transparent px-1 py-0.5 type-caption ${forced ? 'border-primary' : 'border-border'}`} title={forced ? 'set by you' : 'chosen by the planner'}>
                          {g.options.map(o => <option key={o.tech} value={o.tech}>{o.tech.replace(/_/g, ' ')}</option>)}</select>
                        {forced && <Button variant="link" size="sm" className="ml-1" onClick={() => run(() => api.override(folder, { action: 'technique', wid: g.id, technique: null }))}>auto</Button>}</td>
                      <td className="p-2 type-caption"><NativeSelect size="sm" disabled={busy || g.index === 0} value={g.transition?.type ?? 'cut'} onChange={e => run(() => api.override(folder, { action: 'transition', wid: g.id, transition: e.target.value }))}
                          title={g.transition?.why}>{['cut', 'dissolve', 'dip', 'whip'].map(x => <option key={x}>{x}</option>)}</NativeSelect>
                        {ov.transitions?.[g.id] && <Button variant="link" className="ml-1" onClick={() => run(() => api.override(folder, { action: 'transition', wid: g.id, transition: null }))}>auto</Button>}</td>
                      <td className="p-2"><input type="checkbox" checked={g.locked} disabled={busy} title="keep exactly this window and technique when re-planning" onChange={e => run(() => api.override(folder, { action: 'lock', wid: g.id, locked: e.target.checked }))} /></td>
                      <td className="p-2 whitespace-nowrap type-caption">
                        <Tooltip label="less of this clip"><Button size="sm" aria-label="less of this clip" disabled={busy} onClick={() => run(() => api.override(folder, { action: 'weight', clip: g.clip, factor: w / 1.5 }))}>−</Button></Tooltip>
                        <span className="mx-1 text-muted-foreground">{w === 1 ? '' : `×${w.toFixed(1)}`}</span>
                        <Tooltip label="more of this clip"><Button size="sm" aria-label="more of this clip" disabled={busy} onClick={() => run(() => api.override(folder, { action: 'weight', clip: g.clip, factor: w * 1.5 }))}>+</Button></Tooltip>
                        <Tooltip label="never use this footage (whichever way of seeing it)"><Button variant="link" disabled={busy} className="ml-2" onClick={() => run(() => api.override(folder, { action: 'ban', kind: 'moment', key: `win:${g.clip}@${g.clip_start_s}@${+(g.clip_start_s + g.dur_s).toFixed(3)}`, on: true }))}>skip moment</Button></Tooltip></td>
                      <td className="p-2 type-caption">{g.sound && <div className="mb-0.5 text-[11px] text-muted-foreground" title="the sound of this footage as classified, and the level the mix suggests for it">🔊 {g.sound.gain_db} dB · {g.sound.why.join(', ')}</div>}{line?.text ? <span>{line.text}</span> : line?.says?.length ? <span className="italic text-info">💬 “{line.says.join(' … ')}”</span> : <span className="text-muted-foreground">—</span>}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
          <p className="type-caption text-muted-foreground">Techniques used: {Object.entries(plan.technique_seconds).sort((a, b) => b[1] - a[1]).map(([k, v]) => `${k.replace(/_/g, ' ')} ${Math.round(v)}s`).join(' · ')}</p>
        </>
      )}
      {play && <WindowPlayer folder={folder} clip={play.clip} start={play.clip_start_s} end={play.clip_start_s + play.dur_s} title={`${short(play.clip)} ${mmss(play.clip_start_s)}–${mmss(play.clip_start_s + play.dur_s)} · ${play.technique.replace(/_/g, ' ')}`} onClose={() => setPlay(undefined)} />}
    </div>
  )
}
