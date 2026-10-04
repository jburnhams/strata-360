import { useCallback, useEffect, useMemo, useRef, useState, type RefObject } from 'react'
import type L from 'leaflet'
import { api, type AimPath, type PointCam, type PointCams, type PointCamSettings, type PointCamSource, type PointCamUse, type PointCamVideo } from '../api'
import { aimAt, drawAim } from '../aimOverlay'
import { addPointCams } from '../mapLayers'
import StepVideo from './FrameStep'
import { LengthField } from './ItemPage'

// Point cameras: a virtual camera that keeps one place in frame while a clip or a street view section goes past it (src/strata360/edit/pointcam.py). You arm the button, click the map near the path, and the camera looks at that point from wherever the
// path is, panning round and zooming with the distance. The page suggests the stretch (metres before and after the closest approach), lets you change it with the zoom and the height of the point, renders a preview on demand, and offers the shot to
// the planner (possible or must include), where it is a generated clip of its own (C1, C2 ...) in the film list.

export type MapHooks = { decorate: (m: L.Map, g: L.LayerGroup) => void; onMapClick: (lat: number, lon: number) => void; fitTo?: { pts: [number, number][]; key: string } }
export const sourceKey = (s: PointCamSource) => (s.kind === 'clip' ? s.clip : s.key) ?? ''
const sig = (c: PointCam) => [c.lat, c.lon, c.before_m, c.after_m, c.height_m, c.fov_near, c.fov_far, c.smooth_s, c.t_pass].join(',')           // what the preview video is made from (the server names the file by the same things)
const SOURCE_NAME = (s: PointCamSource) => (s.kind === 'clip' ? `clip ${s.clip}` : 'a street view section')

/** The cameras of one clip or section, and what the page needs to add, change and take them away; `hooks` goes to the map (the cameras on it, the click that makes one, the view that moves to the camera picked). */
export function usePointCams(folder: string, source: PointCamSource) {
  const key = sourceKey(source), kind = source.kind
  const [data, setData] = useState<PointCams>(), [picked, setPicked] = useState<string>(), [armed, setArmed] = useState(false), [busy, setBusy] = useState(false), [err, setErr] = useState<string>()
  const reload = useCallback(() => (key ? api.pointcams(folder, kind === 'clip' ? { clip: key } : { key }).then(d => setData(d)).catch(e => setErr((e as Error).message)) : Promise.resolve()), [folder, kind, key])
  useEffect(() => { setData(undefined); setPicked(undefined); setArmed(false); setErr(undefined); reload() }, [reload])
  const cams = useMemo(() => data?.cams ?? [], [data])
  const act = async (fn: () => Promise<unknown>) => { setErr(undefined); try { await fn() } catch (e) { setErr((e as Error).message) } await reload() }
  const add = useCallback(async (lat: number, lon: number) => {
    setArmed(false); setBusy(true); setErr(undefined)
    try { const c = await api.addPointCam(folder, source, lat, lon); setPicked(c.id) } catch (e) { setErr((e as Error).message) }
    setBusy(false); reload()
  }, [folder, kind, key, reload])           // eslint-disable-line react-hooks/exhaustive-deps
  const decorate = useCallback((m: L.Map, g: L.LayerGroup) => { m.getContainer().style.cursor = armed ? 'crosshair' : ''; addPointCams(g, cams, picked, setPicked) }, [cams, picked, armed])
  const p = cams.find(c => c.id === picked), geo = p?.ok ? p.geometry : undefined
  const hooks: MapHooks = { decorate, onMapClick: (lat, lon) => { if (armed) add(lat, lon) }, fitTo: geo ? { pts: [...geo.line, [p!.lat, p!.lon]], key: p!.id } : undefined }
  return { cams, limits: data?.limits, loaded: !!data, picked, setPicked, armed, setArmed, busy, err, hooks, reload,
    update: (id: string, fields: Parameters<typeof api.updatePointCam>[2]) => act(() => api.updatePointCam(folder, id, fields)), remove: (id: string) => act(async () => { await api.deletePointCam(folder, id); if (picked === id) setPicked(undefined) }) }
}
export type PointCamState = ReturnType<typeof usePointCams>

/** The map with the button that arms it, and the cameras below. `map` draws the page's own map with the hooks. */
export function PointCamTool({ folder, source, pc, map, unavailable }: { folder: string; source: PointCamSource; pc: PointCamState; map: (h: MapHooks) => React.ReactNode; unavailable?: string }) {
  return (
    <div aria-label="Point cameras" className="space-y-3">
      {map(pc.hooks)}
      {unavailable && <p className="text-xs text-stone-500">{unavailable}</p>}
      {!unavailable && <div className="flex flex-wrap items-center gap-3 text-sm">
        <button type="button" aria-pressed={pc.armed} disabled={pc.busy} onClick={() => pc.setArmed(a => !a)} className={`rounded px-3 py-1 ${pc.armed ? 'bg-teal-700 text-white' : 'border border-teal-700 text-teal-800 dark:text-teal-300'}`}>{pc.busy ? 'Making the camera…' : pc.armed ? 'Now click the map near the path' : 'Add a point camera'}</button>
        <span className="text-xs text-stone-500">A virtual camera that keeps one place in frame, panning and zooming, while {SOURCE_NAME(source)} goes past it. Arm the button and click the map within 400 m of the path.</span>
      </div>}
      {pc.err && <p role="alert" className="text-sm text-red-700 dark:text-red-400">{pc.err}</p>}
      {pc.loaded && pc.cams.length === 0 && <p className="text-xs text-stone-500">No point cameras here yet.</p>}
      {pc.cams.map(c => <PointCamCard key={c.id} folder={folder} cam={c} pc={pc} />)}
    </div>
  )
}

function NumField({ label, value, min, max, step = 1, unit, onCommit }: { label: string; value: number; min: number; max: number; step?: number; unit: string; onCommit: (v: number) => void }) {
  const [draft, setDraft] = useState<string>(), text = draft ?? String(value)
  const commit = () => { if (draft === undefined) return; const v = Number(draft); const ok = draft.trim() !== '' && Number.isFinite(v); setDraft(undefined); if (ok && v !== value) onCommit(v) }
  return (
    <label className="flex items-center gap-2"><span className="w-44 shrink-0 text-stone-500">{label}</span>
      <input aria-label={label} type="number" min={min} max={max} step={step} value={text} onChange={e => setDraft(e.target.value)} onBlur={commit} onKeyDown={e => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur() }} className="w-20 rounded border border-stone-300 bg-transparent px-1 py-0.5 dark:border-stone-700" /> <span className="text-xs text-stone-500">{unit}</span></label>
  )
}

/** What the camera looks at (a name for the film list and the writer: "the old mill"). */
export function NameField({ cam, onChange }: { cam: PointCam; onChange: (name: string | null) => void }) {
  const [name, setName] = useState<string>()
  return (
    <label className="flex items-center gap-2 sm:col-span-2"><span className="w-44 shrink-0 text-stone-500">What it looks at</span>
      <input aria-label="What it looks at" value={name ?? cam.name ?? ''} placeholder="e.g. the old mill" onChange={e => setName(e.target.value)} onBlur={() => { if (name !== undefined && name !== (cam.name ?? '')) onChange(name || null); setName(undefined) }} className="min-w-0 flex-1 rounded border border-stone-300 bg-transparent px-1 py-0.5 dark:border-stone-700" /></label>
  )
}

/** The look of the shot: how far before and after the closest approach it runs, the zoom (field of view) close to the point and far from it, how high the point is, and how much the pan is smoothed. */
export function PointCamSettingsFields({ cam, limits, onChange }: { cam: PointCam; limits?: PointCams['limits']; onChange: (f: Partial<PointCamSettings> & { name?: string | null }) => void }) {
  const lim = (k: keyof PointCamSettings, d: [number, number]) => limits?.[k] ?? d
  return (<>
    <NumField label="Metres of path before" value={cam.before_m} {...range(lim('before_m', [5, 400]))} unit="m" onCommit={v => onChange({ before_m: v })} />
    <NumField label="Metres of path after" value={cam.after_m} {...range(lim('after_m', [5, 400]))} unit="m" onCommit={v => onChange({ after_m: v })} />
    <NumField label="Zoom close to the point" value={cam.fov_near} {...range(lim('fov_near', [30, 130]))} unit="° wide" onCommit={v => onChange({ fov_near: v })} />
    <NumField label="Zoom far from the point" value={cam.fov_far} {...range(lim('fov_far', [20, 130]))} unit="° wide" onCommit={v => onChange({ fov_far: v })} />
    <NumField label="Height of the point" value={cam.height_m} {...range(lim('height_m', [0, 300]))} unit="m above the ground" onCommit={v => onChange({ height_m: v })} />
    <NumField label="Smoothing of the pan" value={cam.smooth_s} {...range(lim('smooth_s', [0, 4]))} step={0.1} unit="s" onCommit={v => onChange({ smooth_s: v })} />
  </>)
}
const range = ([min, max]: [number, number]) => ({ min, max })

const USES: { v: PointCamUse; label: string }[] = [{ v: '', label: 'Not used' }, { v: 'possible', label: 'Possible' }, { v: 'must', label: 'Must include' }]
/** Whether the planner may use the shot: not at all, as an option the script writer may take, or as a must. */
export function UseRadios({ cam, onChange }: { cam: PointCam; onChange: (u: PointCamUse) => void }) {
  return (
    <fieldset role="group" aria-label={`${cam.label} in the film`} className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm"><legend className="sr-only">{cam.label} in the film</legend>
      <span className="text-stone-500" title="Possible: the planner may cut to the camera inside this clip, and the script writer may give it a shot of its own. Must include: it is always a shot of its own.">In the film</span>
      {USES.map(u => <label key={u.label} className="flex items-center gap-1"><input type="radio" name={`use-${cam.id}`} aria-label={u.label} checked={cam.use === u.v} onChange={() => onChange(u.v)} /> {u.label}</label>)}
    </fieldset>
  )
}

export function PointCamFacts({ cam }: { cam: PointCam }) {
  if (!cam.ok || !cam.facts) return <p role="alert" className="text-sm text-amber-700 dark:text-amber-400">This camera cannot give its shot: {cam.error ?? 'unknown'}</p>
  const f = cam.facts
  return (<>
    <p className="text-sm text-stone-600 dark:text-stone-400">{f.seconds} s of {cam.source.kind === 'clip' ? 'footage' : 'road'} · the point is {f.min_dist_m} m from the path at the closest, {f.max_dist_m} m at the furthest · the view turns {f.swing_deg}° (up to {f.max_pan_deg_s}° a second) · zoom {f.fov_min}° to {f.fov_max}°{cam.range ? ` · plays ${cam.range[0]} to ${cam.range[1]} s in the film` : ''}</p>
    {f.warnings.map(w => <p key={w} role="note" className="text-xs text-amber-700 dark:text-amber-400">⚠ {w}</p>)}
  </>)
}

/** The preview video of a camera: made in the background on demand (with its progress and log), kept, and made again when the camera changes. */
export function PointCamPreview({ folder, cam }: { folder: string; cam: PointCam }) {
  const [st, setSt] = useState<PointCamVideo>(), [err, setErr] = useState<string>(), [starting, setStarting] = useState(false), running = !!st?.running || starting, s = sig(cam)
  useEffect(() => { setSt(undefined); setErr(undefined); setStarting(false) }, [folder, cam.id, s])
  useEffect(() => {
    let live = true; const tick = () => api.pointCamVideo(folder, cam.id).then(v => { if (!live) return; setSt(v); if (v.running || v.exists || v.error) setStarting(false) }).catch(e => live && setErr((e as Error).message))
    tick(); const id = setInterval(tick, running ? 1500 : 30000); return () => { live = false; clearInterval(id) }
  }, [folder, cam.id, s, running])
  const make = async () => { setErr(undefined); setStarting(true); try { const r = await api.makePointCamVideo(folder, cam.id); if (!r.started && r.reason && !/already/.test(r.reason)) { setErr(r.reason); setStarting(false); return } const v = await api.pointCamVideo(folder, cam.id); setSt(v); if (v.running || v.exists || v.error) setStarting(false) } catch (e) { setErr((e as Error).message); setStarting(false) } }
  const pr = st?.progress
  return (
    <div aria-label={`Preview of ${cam.label}`} className="space-y-1">
      {st?.exists && <StepVideo preload="metadata" src={api.pointCamVideoUrl(folder, cam.id, s)} className="max-h-[360px] rounded" aria-label={`Preview video of ${cam.label}`} />}
      {st && !st.exists && !running && cam.ok && <div className="flex flex-wrap items-center gap-2"><button type="button" onClick={make} className="rounded bg-teal-700 px-3 py-1 text-sm text-white">Render a preview</button><span className="text-xs text-stone-500">made in the background and kept; {cam.source.kind === 'clip' ? 'from the clip’s preview video' : 'from the section’s pictures (360 sections only)'}</span></div>}
      {running && (
        <div role="status" aria-label="Making the video" className="max-w-xl space-y-1 text-sm text-stone-600 dark:text-stone-400">
          <div className="flex items-center justify-between text-xs"><span>{pr ? `${pr.phase}: ${pr.done} of ${pr.total}` : 'starting…'}</span><span>{pr ? `${pr.pct}%` : ''}</span></div>
          <div role="progressbar" aria-label="Progress" aria-valuemin={0} aria-valuemax={100} aria-valuenow={pr?.pct} className="h-2 w-full overflow-hidden rounded bg-stone-200 dark:bg-stone-700">
            <div className={`h-full rounded bg-teal-600 transition-[width] duration-500 ${pr ? '' : 'w-1/4 animate-pulse'}`} style={pr ? { width: `${pr.pct}%` } : undefined} /></div>
          <ul aria-label="What it is doing" className="max-h-32 overflow-auto rounded bg-stone-100 p-1.5 font-mono text-[11px] leading-snug text-stone-600 dark:bg-stone-800 dark:text-stone-300">{(st?.log ?? []).map((l, i) => <li key={i}>{l}</li>)}{!st?.log?.length && <li>waiting for the job to report…</li>}</ul>
        </div>)}
      {(err || (st && !st.exists && !running && st.error)) && <p role="alert" className="text-sm text-red-700 dark:text-red-400">{err || st?.error}</p>}
    </div>
  )
}

/** One camera on a clip or street view page: its facts, its settings, whether the planner may use it, and its preview. */
function PointCamCard({ folder, cam, pc }: { folder: string; cam: PointCam; pc: PointCamState }) {
  const on = pc.picked === cam.id
  return (
    <section aria-label={`Point camera ${cam.label}`} data-picked={on ? '' : undefined} className={`space-y-2 rounded-lg border-2 p-3 ${on ? 'border-teal-600' : 'border-stone-200 dark:border-stone-700'}`}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <button type="button" onClick={() => pc.setPicked(cam.id)} className="text-left text-sm font-semibold">Point camera {cam.label}{cam.name ? ` · ${cam.name}` : ''} <span className="text-xs font-normal text-stone-500">at {cam.lat.toFixed(5)}, {cam.lon.toFixed(5)}</span></button>
        <button type="button" onClick={() => { if (window.confirm(`Remove point camera ${cam.label}?`)) pc.remove(cam.id) }} className="text-xs text-red-700 underline dark:text-red-400">Remove</button>
      </div>
      <PointCamFacts cam={cam} />
      <div className="grid gap-2 text-sm sm:grid-cols-2">
        <NameField cam={cam} onChange={name => pc.update(cam.id, { name })} />
        <PointCamSettingsFields cam={cam} limits={pc.limits} onChange={f => pc.update(cam.id, f)} />
      </div>
      <UseRadios cam={cam} onChange={u => pc.update(cam.id, { use: u })} />
      {cam.ok && <PointCamPreview folder={folder} cam={cam} />}
    </section>
  )
}

/** The length of the shot in the film: the plan decides, or exactly so many seconds (a shorter shot is the part nearest the point). */
export function PointCamLength({ cam, onChange }: { cam: PointCam; onChange: (seconds: number | null) => void }) {
  const [lo, hi] = cam.range ?? [2, 30]
  return <LengthField id={cam.id} mode={cam.seconds == null ? '' : 'set'} seconds={cam.seconds ?? null} modes={['set']} min={lo} max={hi} fallback={Math.min(Math.max(cam.facts?.seconds ?? 8, lo), hi)} onChange={(_, s) => onChange(s)} />
}

/** Where the camera `cam` looks over time, for drawing over a video of its source ('clip': the clip's preview; 'pano': a street view look-around; 'flat': its flat preview). `path` is null until it arrives or when there is no camera; `err` says why a video cannot be aimed over. Fetched again when the camera changes. */
export function useAimPath(folder: string, cam: PointCam | undefined, view: 'clip' | 'pano' | 'flat') {
  const [path, setPath] = useState<AimPath | null>(null), [err, setErr] = useState<string>(), id = cam?.id, s = cam ? sig(cam) : ''
  useEffect(() => {
    setPath(null); setErr(undefined); if (!id) return; let live = true
    api.pointCamPath(folder, id, view).then(p => live && setPath(p)).catch(e => live && setErr((e as Error).message)); return () => { live = false }
  }, [folder, id, s, view])
  return { path, err }
}

/** Under a player: the cameras of what it shows, one of which can be picked so the player draws its aim (a dot) and the edge of its frame while the video plays; it follows the view as you pan or as an aim follows someone. `onGo` jumps to where the camera begins. */
export function CamAimPicker({ pc, picked, onPick, onGo, note }: { pc: PointCamState; picked?: string; onPick: (id: string | undefined) => void; onGo?: (cam: PointCam) => void; note?: string }) {
  const cams = pc.cams.filter(c => c.ok)
  if (cams.length === 0) return null
  const cur = cams.find(c => c.id === picked)
  return (
    <div role="group" aria-label="Show a point camera on the video" className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
      <span className="text-stone-500">Show on the video</span>
      <label className="flex items-center gap-1"><input type="radio" name="aim-cam" aria-label="No camera" checked={!cur} onChange={() => onPick(undefined)} /> none</label>
      {cams.map(c => <label key={c.id} className="flex items-center gap-1"><input type="radio" name="aim-cam" aria-label={`Show ${c.label}`} checked={picked === c.id} onChange={() => onPick(c.id)} /> {c.label}{c.name ? ` · ${c.name}` : ''} <span className="text-xs text-stone-500">{c.facts?.seconds} s</span></label>)}
      {cur && onGo && <button type="button" onClick={() => onGo(cur)} className="rounded border border-teal-700 px-2 py-0.5 text-xs text-teal-800 dark:text-teal-300">Go to {cur.label}</button>}
      {cur && <span className="text-xs text-stone-500">● where it aims · the outline is the edge of its frame, while the video is inside its stretch</span>}
      {note && <span role="note" className="text-xs text-amber-700 dark:text-amber-400">{note}</span>}
    </div>
  )
}

/** Draws a camera's aim over a plain video element (the section's flat preview, whose view never changes): put it in a relatively positioned box with the video. */
export function AimVideoOverlay({ video, path }: { video: RefObject<HTMLVideoElement | null>; path: AimPath | null }) {
  const cv = useRef<HTMLCanvasElement>(null)
  useEffect(() => {
    if (!path) { const c = cv.current, g = c?.getContext('2d'); if (c && g) g.clearRect(0, 0, c.width, c.height); return }
    let raf = 0; const v = path.viewer ?? { yaw: 0, pitch: 0, fov: 90 }
    const tick = () => {
      const c = cv.current, vid = video.current, g = c?.getContext('2d')
      if (c && g && vid) { const w = vid.clientWidth, h = vid.clientHeight; if (c.width !== w || c.height !== h) { c.width = w; c.height = h } drawAim(g, w, h, { ...v, aspect: w / Math.max(h, 1) }, aimAt(path, vid.currentTime)) }
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick); return () => cancelAnimationFrame(raf)
  }, [path, video])
  return <canvas ref={cv} aria-hidden="true" data-aim-overlay="" className="pointer-events-none absolute left-0 top-0" />
}
