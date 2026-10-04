import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import L from 'leaflet'
import PanoPlayer from './PanoPlayer'
import TrackMap from './TrackMap'
import StepVideo from './FrameStep'
import { addEnds, addPois, addRoutes, addTiles } from '../mapLayers'
import 'leaflet/dist/leaflet.css'
import { api } from '../api'
import { AimVideoOverlay, useAimPath } from './PointCams'
import type { EndMarkers, PointCam, Poi, StreetView, SvChoice, SvNearClip, SvNearItem, SvNearResult, SvProvider, SvSection, SvSectionInfo, SvStretch, SvVideo, TileStatus, TrackClip } from '../api'
import { usePoll } from '../usePoll'

const COLOUR: Record<SvProvider, string> = { mapillary: '#0891b2', panoramax: '#9333ea', google: '#dc2626' }
const NAME: Record<SvProvider, string> = { mapillary: 'Mapillary', panoramax: 'Panoramax', google: 'Google' }
const LETTER: Record<SvProvider, string> = { mapillary: 'M', panoramax: 'P', google: 'G' }
const PROVIDERS: SvProvider[] = ['mapillary', 'panoramax', 'google']
const DIRECTIONS = ['forward', 'right', 'back', 'left']
/** Colours for a duration on a log scale between the shortest and the longest, light yellow (short) through green and blue to dark purple (long), the same for the clips and the street view sections so they can be compared. */
const RAMP = ['#fde725', '#7ad151', '#22a884', '#2a788e', '#414487', '#440154']
export function rampColour(d: number, lo: number, hi: number) {
  const t = hi > lo ? Math.min(1, Math.max(0, (Math.log(Math.max(d, lo)) - Math.log(lo)) / (Math.log(hi) - Math.log(lo)))) : 0.5, x = t * (RAMP.length - 1), i = Math.min(RAMP.length - 2, Math.floor(x)), f = x - i
  const c = (h: string) => [1, 3, 5].map(k => parseInt(h.slice(k, k + 2), 16)), a = c(RAMP[i]), b = c(RAMP[i + 1])
  return '#' + a.map((v, k) => Math.round(v + (b[k] - v) * f).toString(16).padStart(2, '0')).join('')
}
export const dur = (sec: number) => (sec < 90 ? `${Math.round(sec)} s` : sec < 5400 ? `${Math.round(sec / 60)} min` : `${(sec / 3600).toFixed(1)} h`)
/** A time of day in the race's time zone: "Thu 7 Mar 2024 18:44". */
export const when = (t: number | null | undefined, tz: string) => {
  if (t == null) return '–'
  try { return new Intl.DateTimeFormat('en-GB', { timeZone: tz, weekday: 'short', day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false }).format(new Date(t * 1000)).replace(/,/g, '') } catch { return new Date(t * 1000).toISOString().slice(0, 16).replace('T', ' ') }
}

/** The quality filters: each key is a box in the Filters menu (true: sections like that are shown). */
export const FILTERS: { title: string; items: [string, string][] }[] = [
  { title: 'Quality of the clip', items: [['q:good', 'Good'], ['q:fair', 'Fair'], ['q:poor', 'Poor'], ['q:none', 'Not checked']] },
  { title: 'How steady the camera is kept', items: [['s:exact', 'Exact (360°, true rotation)'], ['s:estimated', 'Estimated (360°, levelled from the picture)'], ['s:by matching only', 'By matching only (flat camera)']] },
  { title: 'Light', items: [['l:fits', 'Light fits the race'], ['l:warn', 'Daytime view for a night stretch (or the reverse)']] },
  { title: 'Position among the footage', items: [['p:gap', 'In a gap (fills a gap in the footage)'], ['p:clip', 'Overlaps a camera clip']] },
  { title: 'Usable', items: [['plausible', 'Only sections with enough pictures to make a clip']] },
]
export const SHOW_ALL: Record<string, boolean> = Object.fromEntries(FILTERS.flatMap(g => g.items.map(([k]) => [k, k !== 'plausible'])))
/** What is shown to start with: only sections that could be used (enough pictures, not poor, the light fits, not over a camera clip); the user shows more. */
export const DEFAULT_FILTERS: Record<string, boolean> = { ...SHOW_ALL, plausible: true, 'q:poor': false, 'l:warn': false, 'p:clip': false }
export const passes = (s: SvSectionInfo, f: Record<string, boolean>) =>
  !!f[`q:${s.quality?.grade ?? 'none'}`] && !!f[`s:${s.steadied}`] && !!f[`l:${s.light?.warning ? 'warn' : 'fits'}`] && !!f[s.near?.overlaps.length ? 'p:clip' : 'p:gap'] && !(f.plausible && !s.plausible)
const away = (c: SvNearClip) => `${c.km} km / ${dur(c.seconds)}`
/** How far the nearest footage is each way along the run, as "0021 3.2 km / 4 min before · 0023 1.1 km / 2 min after"; or where the section overlaps footage. */
export const nearText = (n: SvSectionInfo['near']) => !n ? '' : n.overlaps.length ? `Overlaps clip ${n.overlaps.join(', ')}` : [n.before && `${n.before.label} ${away(n.before)} before`, n.after && `${n.after.label} ${away(n.after)} after`].filter(Boolean).join(' · ') || 'no footage near'
const kindLabel2 = (it: { kind: '360' | '2d' }) => (it.kind === '360' ? '360°' : '2D')
const km = (v: number) => v.toFixed(2).replace(/\.?0+$/, '')
const span = (s: { km0: number; km1: number }) => `km ${km(s.km0)} to ${km(s.km1)}`
const metres = (m: number) => (m >= 1000 ? `${(m / 1000).toFixed(1)} km` : `${m} m`)
const kindLabel = (s: SvSection) => (s.kind === '360' ? '360°' : '2D')

/** What a section's pictures face (flat cameras only), like "forward 12 · back 3". */
const facing = (s: SvSection) => (s.angles ? DIRECTIONS.filter(d => s.angles![d]).map(d => `${d} ${s.angles![d]}`).join(' · ') : 'every way')
/** The frames to show for a section: for a flat camera one for each way it faced (the middle one of each), for a 360 camera four spread along the section. */
function previews(s: SvSection) {
  const pick = (xs: SvSection['items'], n: number) => Array.from({ length: Math.min(n, xs.length) }, (_, i) => xs[Math.floor(((i + 0.5) * xs.length) / Math.min(n, xs.length))])
  if (s.kind === '360' || !s.angles) return pick(s.items, 4).map(it => ({ it, label: `km ${km(it.km)}` }))
  const dir = (a: number | undefined) => { const r = Math.abs(a ?? 0); return r <= 45 ? 'forward' : r >= 135 ? 'back' : (a ?? 0) > 0 ? 'right' : 'left' }
  return DIRECTIONS.flatMap(d => { const xs = s.items.filter(i => dir(i.a) === d); return xs.length ? [{ it: xs[Math.floor(xs.length / 2)], label: `${d} (${xs.length})` }] : [] })
}

// The street view page: the stages that find the road parts of the run and the street-level imagery on them (Mapillary, Panoramax, Google), a map of the road parts (click one) with a marker for each
// stretch of imagery found (click for its pictures), and the same sections as a list underneath.
export default function StreetViewPage({ folder, tz = 'Europe/Brussels', initialFilters = DEFAULT_FILTERS }: { folder: string; tz?: string; initialFilters?: Record<string, boolean> }) {
  const [tick, setTick] = useState(0)
  const data = usePoll(() => api.streetview(folder), 5000, [folder, tick])
  const [tiles, setTiles] = useState<TileStatus>()
  const [sel, setSel] = useState<{ kind: 'section' | 'stretch'; id: string }>()
  const [shown, setShown] = useState<Record<string, boolean>>({ mapillary: true, panoramax: true, google: true, '360': true, '2d': true, clips: true })
  const choose = async (key: string, c: SvChoice | 'none') => { await api.setStreetviewChoice(folder, key, c).catch(e => setErr((e as Error).message)); setTick(t => t + 1) }
  const hires = async (key: string, on: boolean) => { await api.setSvHires(folder, key, on).catch(e => setErr((e as Error).message)); setTick(t => t + 1) }
  const [probe, setProbe] = useState<{ lat: number; lon: number }>(), [near, setNear] = useState<SvNearResult>(), [nearBusy, setNearBusy] = useState(false), [nearErr, setNearErr] = useState<string>(), [nearLog, setNearLog] = useState<string[]>([])
  const [nearGen, setNearGen] = useState(0)                                                       // changes with each click, so an old answer is not shown for a new point
  const look = async (lat: number, lon: number, gen: number) => {
    const r = await api.svNear(folder, lat, lon); if (gen !== nearGenRef.current) return false
    if (r.cached && r.result) { setNear(r.result); setNearBusy(false); return true }
    const mine = r.job && Math.abs(r.job.lat - lat) < 1e-9 && Math.abs(r.job.lon - lon) < 1e-9 ? r.job : undefined
    if (mine) { setNearLog(mine.log); if (mine.error) { setNearErr(mine.error); setNearBusy(false); return true } }
    return false
  }
  const nearGenRef = useRef(0)
  const pick = async (lat: number, lon: number) => {
    const gen = ++nearGenRef.current; setNearGen(gen); setProbe({ lat, lon }); setNear(undefined); setNearErr(undefined); setNearBusy(false); setNearLog([])
    try { await look(lat, lon, gen) } catch (e) { setNearErr((e as Error).message) }
  }
  const search = async () => {
    if (!probe) return; const gen = nearGenRef.current, { lat, lon } = probe; setNearErr(undefined); setNearBusy(true); setNearLog(['starting…'])
    try {
      const r = await api.searchSvNear(folder, lat, lon); if (!r.started && r.reason) { setNearErr(r.reason); setNearBusy(false); return }
      for (let i = 0; i < 400; i++) { await new Promise(res => setTimeout(res, 800)); if (gen !== nearGenRef.current) return; if (await look(lat, lon, gen)) return }
      setNearErr('the search is taking too long'); setNearBusy(false)
    } catch (e) { setNearErr((e as Error).message); setNearBusy(false) }
  }
  const [pois, setPois] = useState<Poi[]>([]), [ends, setEnds] = useState<EndMarkers | null>(null)
  const [routes, setRoutes] = useState<{ id: string; name: string; pts: [number, number][] }[]>([])
  useEffect(() => {                                                                              // the route tracks (the planned course), drawn in blue
    let live = true; setRoutes([]); setPois([]); setEnds(null)
    api.tracks(folder).then(l => { if (live) { setPois(l.pois ?? []); setEnds(l.markers ?? null) } return l }).then(l => Promise.all(l.tracks.filter(t => t.kind === 'route' && !t.error).map(t => api.tracksLine(folder, t.id).then(x => ({ id: t.id, name: t.name, pts: x.lat.map((la, i) => [la, x.lon[i]] as [number, number]) })).catch(() => null))))
      .then(r => { if (live) setRoutes(r.filter((x): x is { id: string; name: string; pts: [number, number][] } => !!x)) }).catch(() => {})
    return () => { live = false }
  }, [folder])
  const [err, setErr] = useState<string>(), [clips, setClips] = useState<TrackClip[]>([]), [filters, setFilters] = useState<Record<string, boolean>>(initialFilters)
  useEffect(() => { api.trackClips(folder).then(r => setClips(r.clips.filter(c => c.covered && c.stretch?.length))).catch(() => setClips([])) }, [folder])
  useEffect(() => { api.tilesStatus().then(setTiles).catch(() => setTiles({ ok: false, style: 'tf-landscape', error: 'no map background' })) }, [])
  useEffect(() => { setSel(undefined) }, [folder])
  const roads = useMemo(() => data?.roads, [data?.roads?.id])                                // (a new copy comes with every poll: the map is only rebuilt when the road parts really change)
  const sections = useMemo(() => data?.sections ?? [], [data])
  const visible = sections.filter(s => shown[s.provider] && shown[s.kind] && passes(s, filters))
  const scale = useMemo(() => { const d = [...clips.map(c => c.duration_s), ...sections.map(x => x.max_s)].filter(v => v > 0); return d.length ? { lo: Math.min(...d), hi: Math.max(...d) } : { lo: 1, hi: 60 } }, [clips, sections])
  const stretch = (id: string) => roads?.stretches.find(s => s.id === id)
  const run = async (stages?: string[], force = false) => {
    setErr(undefined)
    try { const r = await api.runStreetview(folder, { stages, force }); if (!r.started) setErr(r.reason ?? 'could not start'); setTick(t => t + 1) } catch (e) { setErr((e as Error).message) }
  }
  const section = sel?.kind === 'section' ? sections.find(s => s.id === sel.id) : undefined
  const chosenStretch = sel?.kind === 'stretch' ? stretch(sel.id) : section ? stretch(section.stretch) : undefined
  return (
    <section className="space-y-4" aria-label="Street view">
      <div className="rounded-lg bg-white p-4 shadow-sm dark:bg-stone-900">
        <h2 className="text-lg font-semibold">Street view</h2>
        <p className="mb-3 text-sm text-stone-600 dark:text-stone-400">Where the run was on a road, and the street-level pictures there are of those roads: a gap in the film could be shown as the view along the road.</p>
        {!data ? <p className="text-sm text-stone-500">Loading…</p> : <Stages data={data} onRun={run} err={err} />}
      </div>
      {data && roads && sections.length > 0 && <Candidates folder={folder} tz={tz} sections={visible} all={sections} sel={sel} onSel={setSel} onChoose={choose} />}
      {data && roads && (
        <div className="rounded-lg bg-white p-4 shadow-sm dark:bg-stone-900">
          <Filters shown={shown} setShown={setShown} data={data} filters={filters} setFilters={setFilters} total={sections.length} showing={visible.length} />
          <SvMap pois={pois} ends={ends} tz={tz} routes={routes} probe={probe && { ...probe, items: near ? PROVIDERS.flatMap(p => near.providers[p].items) : [] }} onPick={pick} roads={roads.stretches} run={roads.run} sections={visible} clips={shown.clips ? clips : []} scale={scale} sel={sel} onSel={setSel} background={tiles?.ok ? { url: api.tileUrl(tiles.style), tilePx: tiles.tile_px ?? 256 } : undefined} />
          <Legend scale={scale} hasClips={clips.length > 0} />
          <p className="mt-1 flex flex-wrap gap-x-4 text-xs text-stone-600 dark:text-stone-400">
            <span>click anywhere on the map to see the nearest street view there</span>
            <span><span className="mr-1 inline-block h-1 w-4 align-middle" style={{ background: '#dc2626' }} />the run</span>
            {routes.length > 0 && <span><span className="mr-1 inline-block h-1 w-4 align-middle" style={{ background: '#2563eb' }} />route tracks</span>}
            <span><span className="mr-1 inline-block h-1.5 w-4 align-middle" style={{ background: '#f59e0b' }} />road part of the run (click one)</span>
            {PROVIDERS.map(p => <span key={p}><span className="mr-1 inline-block h-2.5 w-2.5 rounded-full align-middle" style={{ background: COLOUR[p] }} />{NAME[p]}</span>)}
            <span>360° = sees every way · 2D = faces one way</span>{tiles?.ok && tiles.credit && <span>{tiles.credit}</span>}
          </p>
        </div>
      )}
      {probe && <NearPanel key={nearGen} folder={folder} tz={tz} probe={probe} result={near} busy={nearBusy} log={nearLog} error={nearErr} onSearch={search} onPromoted={() => setTick(t => t + 1)} onClose={() => { nearGenRef.current++; setProbe(undefined); setNear(undefined); setNearErr(undefined); setNearBusy(false) }} />}
      {(section || chosenStretch) && <Detail folder={folder} tz={tz} section={section} stretch={chosenStretch} sections={sections.filter(s => s.stretch === chosenStretch?.id)} onSel={setSel} onChoose={choose} onHires={hires} />}
      {roads && <List title="Every section found" tz={tz} sections={visible} sel={sel} onSel={setSel} none={sections.length === 0} />}
    </section>
  )
}

function Stages({ data, onRun, err }: { data: StreetView; onRun: (stages?: string[], force?: boolean) => void; err?: string }) {
  const st = data.status, busy = data.job.running
  const line = (k: 'roads' | SvProvider | 'quality') => {
    const s = st[k]
    if (!s.done) return 'not run yet'
    return (k === 'roads' ? `${s.stretches} road parts, ${s.km} km` : k === 'quality' ? `${s.scored} sections scored` : `${s.sections} sections, ${s.frames} pictures, ${s.km} km`) + (s.stale ? ' · out of date: the road parts changed' : '')
  }
  const need = (k: SvProvider) => (k === 'mapillary' && !data.keys.mapillary ? 'needs MAPILLARY_TOKEN in secrets.env' : k === 'google' && !data.keys.google ? 'needs GOOGLE_MAPS_API_KEY in secrets.env' : '')
  return (
    <div>
      <ul className="grid gap-2 md:grid-cols-5">
        {(['roads', ...PROVIDERS, 'quality'] as ('roads' | SvProvider | 'quality')[]).map(k => {
          const s = st[k], why = k === 'roads' || k === 'quality' ? '' : need(k), blocked = busy || !!why || (k !== 'roads' && !st.roads.done)
          return (
            <li key={k} className="rounded-lg border border-stone-200 p-2 text-sm dark:border-stone-700">
              <div className="font-medium">{k === 'roads' ? 'Road parts of the run' : k === 'quality' ? 'Quality check' : NAME[k]}</div>
              <div className="text-xs text-stone-600 dark:text-stone-400">{line(k)}</div>
              {why && <div className="text-xs text-amber-700 dark:text-amber-400">{why}</div>}
              <button disabled={blocked} onClick={() => onRun([k], s.done)} aria-label={`${s.done && !s.stale ? 'Redo' : 'Run'} ${k === 'roads' ? 'road parts' : k === 'quality' ? 'quality check' : NAME[k]}`}
                className="mt-1 rounded bg-emerald-700 px-2 py-0.5 text-xs text-white disabled:opacity-40">{s.done && !s.stale ? 'Redo' : 'Run'}</button>
            </li>
          )
        })}
      </ul>
      <div className="mt-2 flex flex-wrap items-center gap-3 text-sm">
        <button disabled={busy} onClick={() => onRun()} className="rounded bg-emerald-700 px-3 py-1 text-white disabled:opacity-40">Run all that is missing</button>
        {busy && <span role="status" className="text-stone-600 dark:text-stone-400">working… {data.job.log.slice(-1)[0] ?? ''}</span>}
        {!busy && data.job.error && <span role="alert" className="text-red-700 dark:text-red-400">{data.job.error}</span>}
        {err && <span role="alert" className="text-red-700 dark:text-red-400">{err}</span>}
      </div>
    </div>
  )
}

function Filters({ shown, setShown, data, filters, setFilters, total, showing }: { shown: Record<string, boolean>; setShown: (f: Record<string, boolean>) => void; data: StreetView; filters: Record<string, boolean>; setFilters: (f: Record<string, boolean>) => void; total: number; showing: number }) {
  const [open, setOpen] = useState(false)
  const box = (k: string, label: string, colour?: string) => (
    <label key={k} className="flex items-center gap-1 text-sm"><input type="checkbox" checked={shown[k]} onChange={e => setShown({ ...shown, [k]: e.target.checked })} />{colour && <span className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: colour }} />}{label}</label>
  )
  const off = Object.entries(filters).filter(([k, v]) => (k === 'plausible' ? v : !v)).length
  return (
    <div className="relative mb-2 flex flex-wrap items-center gap-4">
      {PROVIDERS.map(p => box(p, `${NAME[p]}${data.providers[p] ? ` (${data.sections.filter(s => s.provider === p).length})` : ''}`, COLOUR[p]))}{box('360', '360° cameras')}{box('2d', '2D cameras')}{box('clips', 'Camera clips')}
      <button type="button" aria-expanded={open} aria-haspopup="true" onClick={() => setOpen(o => !o)} className="rounded border border-stone-300 px-2 py-0.5 text-sm dark:border-stone-600">Filters{off ? ` (${off})` : ''} ▾</button>
      <span className="text-xs text-stone-500" aria-live="polite">{showing} of {total} sections shown</span>
      {open && (
        <div role="group" aria-label="Filters" className="absolute left-0 top-full z-[1000] mt-1 w-96 max-w-full space-y-2 rounded-lg border border-stone-300 bg-white p-3 text-sm shadow-lg dark:border-stone-600 dark:bg-stone-900">
          {FILTERS.map(g => (
            <fieldset key={g.title}><legend className="text-xs font-semibold uppercase tracking-wide text-stone-500">{g.title}</legend>
              {g.items.map(([k, label]) => <label key={k} className="flex items-center gap-1"><input type="checkbox" checked={!!filters[k]} onChange={e => setFilters({ ...filters, [k]: e.target.checked })} />{label}</label>)}</fieldset>
          ))}
          <div className="flex gap-3"><button type="button" className="text-xs underline" onClick={() => setFilters(DEFAULT_FILTERS)}>Usable only</button><button type="button" className="text-xs underline" onClick={() => setFilters(SHOW_ALL)}>Show everything</button></div>
        </div>
      )}
    </div>
  )
}

function SvMap({ pois = [], ends = null, tz = 'Europe/Brussels', routes, probe, onPick, roads, run, sections, clips, scale, sel, onSel, background }: { pois?: Poi[]; ends?: EndMarkers | null; tz?: string; probe?: { lat: number; lon: number; items: SvNearItem[] }; onPick: (lat: number, lon: number) => void; routes: { id: string; name: string; pts: [number, number][] }[]; roads: SvStretch[]; run: [number, number][]; sections: SvSectionInfo[]; clips: TrackClip[]; scale: { lo: number; hi: number }; sel?: { kind: string; id: string }; onSel: (s: { kind: 'section' | 'stretch'; id: string }) => void; background?: { url: string; tilePx: number } }) {
  const onSelRef = useRef(onSel), onPickRef = useRef(onPick); onSelRef.current = onSel; onPickRef.current = onPick
  const base = useMemo(() => ({ lat: run.map(p => p[0]), lon: run.map(p => p[1]), t: [] as number[] }), [run])
  const decorate = useCallback((_m: L.Map, g: L.LayerGroup) => {                                // the road parts, the run in red over them, the sections, the clips and what was clicked, over the race map
    addRoutes(g, routes, { weight: 5 })                                                           // the route tracks in blue, under everything
    for (const c of clips) {                                                                      // the stretch of the run each camera clip covers, coloured by how long the clip is, with a marker numbered like the clip
      const col = rampColour(c.duration_s, scale.lo, scale.hi)
      L.polyline(c.stretch!, { color: '#fff', weight: 9, opacity: 0.9, interactive: false }).addTo(g); L.polyline(c.stretch!, { color: col, weight: 6, opacity: 1, interactive: false }).addTo(g)
      if (c.lat != null && c.lon != null) L.marker([c.lat, c.lon], { title: `Clip ${c.label} · ${dur(c.duration_s)}`, keyboard: false, icon: L.divIcon({ className: '', iconSize: [30, 16], html: `<div data-clip-marker style="background:${col};color:#fff;text-shadow:0 0 2px #000;font:600 10px/16px sans-serif;border-radius:8px;text-align:center;border:1.5px solid #fff">${c.label}</div>` }) }).addTo(g)
    }
    for (const r of roads) {
      const on = sel?.kind === 'stretch' && sel.id === r.id
      L.polyline(r.line, { color: '#f59e0b', weight: on ? 9 : 6, opacity: on ? 1 : 0.8, bubblingMouseEvents: false }).bindTooltip(`${r.names.join(', ') || r.highways.join(', ')} · ${span(r)} · ${metres(r.length_m)}`).on('click', () => onSelRef.current({ kind: 'stretch', id: r.id })).addTo(g)
    }
    L.polyline(run, { color: '#dc2626', weight: 4, opacity: 0.95, interactive: false }).addTo(g)                                // the run in red, over the road parts (their orange shows either side)
    for (const s of sections) {
      const on = sel?.kind === 'section' && sel.id === s.id, pts = s.items.map(i => [i.lat, i.lon] as [number, number])
      L.polyline(pts, { color: '#fff', weight: on ? 10 : 8, opacity: 0.9, interactive: false }).addTo(g); L.polyline(pts, { color: rampColour(s.max_s, scale.lo, scale.hi), weight: on ? 7 : 5, opacity: 1, dashArray: s.kind === '2d' ? undefined : '3 5', interactive: false }).addTo(g)
      const mid = s.items[Math.floor(s.items.length / 2)]
      const icon = L.divIcon({ className: '', iconSize: [34, 20], html: `<div style="background:${COLOUR[s.provider]};color:#fff;font:600 11px/20px sans-serif;border-radius:10px;text-align:center;border:${on ? '2px solid #000' : s.choice ? '2px solid #f59e0b' : '1.5px solid #fff'}">${LETTER[s.provider]} ${kindLabel(s)}</div>` })
      L.marker([mid.lat, mid.lon], { icon, title: `${NAME[s.provider]} ${kindLabel(s)} ${span(s)}`, keyboard: true, zIndexOffset: on ? 1000 : 0, bubblingMouseEvents: false }).on('click', () => onSelRef.current({ kind: 'section', id: s.id })).addTo(g)
    }
    if (probe) {                                                                                  // the clicked point and the nearest street view found there
      L.circleMarker([probe.lat, probe.lon], { radius: 7, color: '#000', weight: 2, fillColor: '#fff', fillOpacity: 1, interactive: false }).addTo(g)
      for (const it of probe.items) L.circleMarker([it.lat, it.lon], { radius: 5, color: '#fff', weight: 1.5, fillColor: COLOUR[it.provider], fillOpacity: 1, bubblingMouseEvents: false }).bindTooltip(`${NAME[it.provider]} ${kindLabel2(it)} · ${it.distance_m} m away`).addTo(g)
    }
  }, [roads, run, routes, sections, clips, scale, sel, probe])
  const pts = sel?.kind === 'stretch' ? roads.find(r => r.id === sel.id)?.line : sel?.kind === 'section' ? sections.find(s => s.id === sel.id)?.items.map(i => [i.lat, i.lon] as [number, number]) : undefined
  return <TrackMap base={base} height="h-[480px]" label="Map of the road parts and street view coverage" tz={tz} background={background} pois={pois} ends={ends} runColor="#dc2626" runWeight={4} svg decorate={decorate} onMapClick={(la: number, lo: number) => onPickRef.current(la, lo)} fitTo={pts?.length ? { pts, key: `${sel?.kind}:${sel?.id}` } : undefined} />
}

/** What is known about when a section was filmed and passed and where it sits among the footage: the light warning, the times, the nearest footage each way and the sections over the same road. Shared by the candidates and the section's page in the film list. */
export function SectionFacts({ s, tz, by }: { s: SvSectionInfo; tz: string; by: Map<string, SvSectionInfo> }) {
  return (
    <>
      {s.light?.warning && <p className="text-xs font-medium text-red-700 dark:text-red-400" role="note" data-light>⚠ {s.light.warning}</p>}
      <p className="text-xs text-stone-600 dark:text-stone-400" data-times>Filmed {when(s.filmed?.[0], tz)} · you pass it {when(s.passed?.[0], tz)}{s.has_video && <span className="ml-2 rounded bg-sky-700 px-1.5 text-white">preview video ready</span>}</p>
      {s.near && <p className={`text-xs ${s.near.overlaps.length ? 'text-amber-700 dark:text-amber-400' : 'text-stone-600 dark:text-stone-400'}`} data-near>{s.near.in_gap ? `Fills gap ${s.near.in_gap}. ` : ''}Nearest footage: {nearText(s.near)}</p>}
      {s.overlaps.length > 0 && <p className="text-xs text-amber-700 dark:text-amber-400" role="note">Overlaps the same road as {s.overlaps.map(id => { const o = by.get(id); return o ? `${NAME[o.provider]} ${o.id} (${span(o)})` : id }).join(', ')}: choose the one you prefer, or both and let the writer pick.</p>}
    </>
  )
}

/** Not used / Possible / Must include for a section (any section: one that is not a candidate can still be used). */
export function ChoiceRadios({ section, onChoose }: { section: SvSectionInfo; onChoose: (key: string, c: SvChoice | 'none') => void }) {
  return (
    <fieldset className="mt-1 flex flex-wrap items-center gap-3 text-sm" aria-label={`Use ${NAME[section.provider]} ${section.id} in the film (details)`}>
      {CHOICES.map(c => <label key={c.v} className="flex items-center gap-1"><input type="radio" name={`use-detail-${section.key}`} checked={(section.choice ?? 'none') === c.v} onChange={() => onChoose(section.key, c.v)} />{c.label}</label>)}
      {!section.plausible && <span className="text-xs text-amber-700 dark:text-amber-400">Not a candidate ({section.why_not}), but you can still use it.</span>}
    </fieldset>
  )
}

/** The higher resolution of a Google section: the look-around video, the preview and the clip in the final film are made from views twice as close (about four times the requests to Google, asked for when they are made, and kept). */
export function HiresTick({ section, onHires }: { section: SvSectionInfo; onHires: (key: string, on: boolean) => void }) {
  return (
    <label className="mt-1 flex items-center gap-1 text-xs" title="Google gives flat views only, so a 360 picture is stitched from zoomed-in ones: closer views mean more detail, and more requests (60 a panorama instead of 16)">
      <input type="checkbox" aria-label="Higher resolution" checked={!!section.hires} onChange={e => onHires(section.key, e.target.checked)} /> Higher resolution, everywhere this section is used (the videos here and the clip in the final film): about 4 times the requests to Google, asked for when the video or the film is made
    </label>
  )
}

/** One section as the street view page shows it: what it is, when it was filmed and passed, its camera, the choice for the film, the preview video and its pictures. The section's page in the film list reuses it. */
export function SectionContent({ folder, tz, section, onChoose, onHires, showChoice = true, aimCam }: { folder: string; tz: string; section: SvSectionInfo; onChoose: (key: string, c: SvChoice | 'none') => void; onHires?: (key: string, on: boolean) => void; showChoice?: boolean; aimCam?: PointCam }) {
  const [big, setBig] = useState<{ provider: SvProvider; id: string }>()
  useEffect(() => { setBig(undefined) }, [section.id])
  return (
        <div className="mt-2">
          <div className="text-sm"><span className="mr-1 inline-block h-2.5 w-2.5 rounded-full align-middle" style={{ background: COLOUR[section.provider] }} /><span className="font-medium">{NAME[section.provider]} · {kindLabel(section)}</span> · {span(section)} · {metres(section.length_m)} · {section.frames} pictures{section.spacing_m != null ? `, one every ${section.spacing_m} m` : ''}
            {section.years.length > 0 && ` · ${section.years.join(', ')}`}{section.camera && ` · ${section.camera}`}{section.size && ` · ${section.size[0]}×${section.size[1]}`}</div>
          <div className="text-xs text-stone-600 dark:text-stone-400" data-times>Filmed {when(section.filmed?.[0], tz)}{section.filmed && section.filmed[1] - section.filmed[0] > 60 ? ` to ${when(section.filmed[1], tz)}` : ''} · you pass it {when(section.passed?.[0], tz)}{section.passed ? ` to ${when(section.passed[1], tz).split(' ').slice(-1)[0]}` : ''}</div>
          <div className="text-xs text-stone-600 dark:text-stone-400">{section.kind === '360' ? 'A 360° camera: the view can be turned to face along the road.' : `A flat camera, facing: ${facing(section)} (relative to the way the runner went).`}</div>
          {showChoice && <ChoiceRadios section={section} onChoose={onChoose} />}
          {onHires && section.provider === 'google' && section.kind === '360' && <HiresTick section={section} onHires={onHires} />}
          <SectionVideo folder={folder} section={section} aimCam={aimCam} />
          {section.kind === '360' && <SectionVideo folder={folder} section={section} pano aimCam={aimCam} />}
          <ul className="mt-2 grid grid-cols-2 gap-2 md:grid-cols-4">
            {previews(section).map(({ it, label }) => (
              <li key={it.id}><button onClick={() => setBig({ provider: section.provider, id: it.id })} className="block w-full text-left" aria-label={`Picture at ${label}`}>
                <img loading="lazy" src={api.streetviewImage(folder, section.provider, it.id, 256)} alt={`${NAME[section.provider]} ${label}`} className="aspect-[3/2] w-full rounded object-cover" /><span className="text-xs text-stone-600 dark:text-stone-400">{label}</span></button></li>
            ))}
          </ul>
          {big && <div className="mt-2"><img src={api.streetviewImage(folder, big.provider, big.id, 1024)} alt="Larger picture" className="max-h-[480px] rounded" /><button className="block text-xs underline" onClick={() => setBig(undefined)}>Close the larger picture</button></div>}
        </div>
  )
}

function Detail({ folder, tz, section, stretch, sections, onSel, onChoose, onHires }: { folder: string; tz: string; section?: SvSectionInfo; stretch?: SvStretch; sections: SvSectionInfo[]; onChoose: (key: string, c: SvChoice | 'none') => void; onHires: (key: string, on: boolean) => void; onSel: (s: { kind: 'section' | 'stretch'; id: string }) => void }) {
  return (
    <div className="rounded-lg bg-white p-4 shadow-sm dark:bg-stone-900">
      {stretch && <div className="text-sm"><span className="font-medium">{stretch.names.join(', ') || 'Unnamed road'}</span> · {stretch.highways.join(', ')} · {span(stretch)} · {metres(stretch.length_m)} of the run on this road
        {!section && <span className="text-stone-600 dark:text-stone-400"> · {sections.length ? `${sections.length} section${sections.length === 1 ? '' : 's'} of street view` : 'no street view found'}</span>}</div>}
      {!section && sections.length > 0 && <ul className="mt-2 flex flex-wrap gap-2">{sections.map(s => <li key={s.id}><button onClick={() => onSel({ kind: 'section', id: s.id })} className="rounded border border-stone-300 px-2 py-0.5 text-xs dark:border-stone-600">{NAME[s.provider]} {kindLabel(s)} · {metres(s.length_m)}</button></li>)}</ul>}
      {section && <SectionContent folder={folder} tz={tz} section={section} onChoose={onChoose} onHires={onHires} />}
    </div>
  )
}

function List({ title, tz, sections, sel, onSel, none }: { title: string; tz: string; sections: SvSectionInfo[]; sel?: { kind: string; id: string }; onSel: (s: { kind: 'section' | 'stretch'; id: string }) => void; none: boolean }) {
  if (!sections.length) return <p className="rounded-lg bg-white p-4 text-sm text-stone-600 shadow-sm dark:bg-stone-900 dark:text-stone-400">{none ? 'No street view sections yet: run a provider above.' : 'Nothing matches the filters.'}</p>
  return (
    <div className="overflow-x-auto rounded-lg bg-white p-4 shadow-sm dark:bg-stone-900">
      <h3 className="mb-1 text-sm font-semibold">{title}</h3>
      <table className="w-full text-left text-sm">
        <thead className="text-xs text-stone-500"><tr><th className="pr-3">Source</th><th className="pr-3">Camera</th><th className="pr-3">Where</th><th className="pr-3">Length</th><th className="pr-3">Pictures</th><th className="pr-3">Spacing</th><th className="pr-3">Year</th><th className="pr-3">Facing</th><th className="pr-3">Size</th><th className="pr-3">Quality</th><th className="pr-3">Nearest footage</th><th className="pr-3">Filmed</th><th className="pr-3">You passed</th><th>Overlaps</th></tr></thead>
        <tbody>
          {sections.map(s => (
            <tr key={s.id} onClick={() => onSel({ kind: 'section', id: s.id })} className={`cursor-pointer border-t border-stone-200 dark:border-stone-700 ${sel?.kind === 'section' && sel.id === s.id ? 'bg-emerald-100 dark:bg-emerald-950' : 'hover:bg-stone-100 dark:hover:bg-stone-800'}`}>
              <td className="pr-3"><button className="underline" onClick={e => { e.stopPropagation(); onSel({ kind: 'section', id: s.id }) }}>{NAME[s.provider]} {s.id}</button></td><td className="pr-3">{kindLabel(s)}</td><td className="pr-3">{span(s)} <span className="text-stone-500">({s.stretch})</span></td>
              <td className="pr-3">{metres(s.length_m)}</td><td className="pr-3">{s.frames}</td><td className="pr-3">{s.spacing_m != null ? `${s.spacing_m} m` : '–'}</td><td className="pr-3">{s.years.join(', ') || '–'}</td><td className="pr-3">{facing(s)}</td><td className="pr-3">{s.size ? `${s.size[0]}×${s.size[1]}` : '–'}</td><td className="pr-3">{s.quality?.score != null ? `${s.quality.grade} (${s.quality.score})` : '–'}</td><td className="pr-3">{s.near ? `${s.near.in_gap ? s.near.in_gap + ': ' : ''}${nearText(s.near)}` : '–'}</td><td className="pr-3">{when(s.filmed?.[0], tz)}</td><td className="pr-3">{when(s.passed?.[0], tz)}</td><td>{s.overlaps.length ? <span className="text-amber-700 dark:text-amber-400">{s.overlaps.join(', ')}</span> : '–'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

const SLOWEST = 4
const CHOICES: { v: SvChoice | 'none'; label: string }[] = [{ v: 'none', label: 'Not used' }, { v: 'possible', label: 'Possible' }, { v: 'must', label: 'Must include' }]

/** The sections that could make a clip, each with its pictures and a choice for the film: not used, possible (the writer may use it) or must include. Sections over the same road say so. */
function Candidates({ folder, tz, sections, all, sel, onSel, onChoose }: { folder: string; tz: string; sections: SvSectionInfo[]; all: SvSectionInfo[]; sel?: { kind: string; id: string }; onSel: (s: { kind: 'section'; id: string }) => void; onChoose: (key: string, c: SvChoice | 'none') => void }) {
  const [order, setOrder] = useState<'quality' | 'route'>('quality')
  const by = new Map(all.map(s => [s.id, s])), chosen = all.filter(s => s.choice)
  const ok = sections.filter(s => s.plausible).sort((a, b) => order === 'route' ? a.km0 - b.km0 : (b.quality?.score ?? -1) - (a.quality?.score ?? -1) || a.km0 - b.km0)                 // best first; the ones not scored yet last
  return (
    <div className="rounded-lg bg-white p-4 shadow-sm dark:bg-stone-900" aria-label="Sections that could be used">
      <div className="flex flex-wrap items-center justify-between gap-2"><h3 className="text-sm font-semibold">Sections that could be used in the film</h3>
        <label className="flex items-center gap-1 text-xs">Order <select value={order} onChange={e => setOrder(e.target.value as 'quality' | 'route')} className="rounded border border-stone-300 bg-white px-1 py-0.5 dark:border-stone-600 dark:bg-stone-900"><option value="quality">best quality first</option><option value="route">along the route</option></select></label></div>
      <p className="mb-2 text-xs text-stone-600 dark:text-stone-400">{all.filter(s => s.plausible).length} of {all.length} sections have enough pictures, close enough together, to make a clip. Mark the ones the film may use: only those are shown to the script writer, and the plan makes a clip of any it picks.
        {chosen.length > 0 && ` Chosen: ${chosen.length} (${chosen.filter(s => s.choice === 'must').length} must include).`} Pictures are credited CC BY-SA to Mapillary and Panoramax contributors.</p>
      {ok.length === 0 && <p className="text-sm text-stone-600 dark:text-stone-400">{all.some(s => s.plausible) ? 'No candidate matches the filters.' : 'None of the sections found has enough pictures yet.'}</p>}
      <ul className="space-y-2">
        {ok.map(s => (
          <li key={s.key} data-section={s.id} className={`rounded-lg border p-2 ${sel?.id === s.id ? 'border-emerald-600' : 'border-stone-200 dark:border-stone-700'}`}>
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
              <button className="font-medium underline" onClick={() => onSel({ kind: 'section', id: s.id })}><span className="mr-1 inline-block h-2.5 w-2.5 rounded-full align-middle" style={{ background: COLOUR[s.provider] }} />{NAME[s.provider]} {s.id} · {kindLabel(s)}</button>
              <span>{span(s)} · {metres(s.length_m)} of road that matches the run · {s.frames} pictures, one every {s.spacing_m} m{s.years.length ? ` · ${s.years.join(', ')}` : ''}{s.size ? ` · ${s.size[0]}×${s.size[1]}` : ''}</span>
              <span className="text-stone-600 dark:text-stone-400">clip of {s.min_s} to {s.max_s} s (the longest is {SLOWEST} pictures a second blended up to 30 frames a second; a shorter one is the same road played faster){s.kind === '2d' ? ` · faces ${facing(s)}` : ''}</span>
              <span className={s.steadied === 'by matching only' ? 'text-amber-700 dark:text-amber-400' : 'text-stone-600 dark:text-stone-400'}>steadied: {s.steadied}{s.steadied === 'by matching only' ? ' (may still wobble)' : ''}</span>
              <Quality q={s.quality} />
              {s.label && <span className="rounded bg-emerald-700 px-1.5 text-xs text-white">called {s.label} in the script</span>}
            </div>
            <SectionFacts s={s} tz={tz} by={by} />
            <div className="mt-1 flex flex-wrap items-center gap-3">
              <ul className="flex gap-1">{previews(s).filter((_, i, a) => a.length <= 3 || i % Math.ceil(a.length / 3) === 0).slice(0, 3).map(({ it, label }) => <li key={it.id}><img loading="lazy" src={api.streetviewImage(folder, s.provider, it.id, 256)} alt={`${NAME[s.provider]} ${s.id} ${label}`} className="h-16 w-24 rounded object-cover" /></li>)}</ul>
              <fieldset className="flex gap-3 text-sm" aria-label={`Use ${NAME[s.provider]} ${s.id} in the film`}>
                {CHOICES.map(c => <label key={c.v} className="flex items-center gap-1"><input type="radio" name={`use-${s.key}`} checked={(s.choice ?? 'none') === c.v} onChange={() => onChoose(s.key, c.v)} />{c.label}</label>)}
              </fieldset>
            </div>
          </li>
        ))}
      </ul>
      {all.length > all.filter(s => s.plausible).length && <p className="mt-2 text-xs text-stone-500">{all.length - all.filter(s => s.plausible).length} more sections are too short or too sparse to use; they are in the list below.</p>}
    </div>
  )
}

const GRADE = { good: 'bg-emerald-700 text-white', fair: 'bg-amber-500 text-black', poor: 'bg-red-700 text-white' }

/** How good a clip of the section will look (0 to 100, from the quality check): good, fair or poor, with the measurements on hover. */
function Quality({ q }: { q: SvSectionInfo['quality'] }) {
  if (!q) return <span className="text-xs text-stone-500">quality not checked yet</span>
  if (q.score == null || !q.grade) return <span className="text-xs text-stone-500" title={q.error}>quality could not be measured</span>
  return <span className={`rounded px-1.5 text-xs ${GRADE[q.grade]}`} title={`in-between pictures ${q.psnr} dB · unsteadiness ${q.jerk}° · turning ${q.roll}°`}>quality: {q.grade} ({q.score})</span>
}


/** The key to the colours: the clips' stretches and the street view sections are coloured by duration, on one scale. */
function Legend({ scale, hasClips }: { scale: { lo: number; hi: number }; hasClips: boolean }) {
  return (
    <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-stone-600 dark:text-stone-400" aria-label="Duration colours">
      <span>Colour = duration:</span><span>{dur(scale.lo)}</span><span className="h-2.5 w-40 rounded" style={{ background: `linear-gradient(to right, ${RAMP.join(',')})` }} /><span>{dur(scale.hi)}</span>
      <span>· {hasClips ? 'numbered stretches are the camera clips (their length); ' : ''}the coloured lines with a letter badge are street view sections (the longest clip each can make)</span>
    </div>
  )
}

/** The preview video of a section: shown when it has been made, else a button to make it (in the background; kept, so it is made once). */
function SectionVideo({ folder, section, pano = false, aimCam }: { folder: string; section: SvSectionInfo; pano?: boolean; aimCam?: PointCam }) {
  const flat = useRef<HTMLVideoElement>(null), aim = useAimPath(folder, aimCam, pano ? 'pano' : 'flat')                         // (a point camera picked on the page: its aim is drawn over the video while it plays)
  const [st, setSt] = useState<SvVideo>(), [err, setErr] = useState<string>(), [starting, setStarting] = useState(false), running = !!st?.running || starting
  useEffect(() => { setSt(undefined); setErr(undefined); setStarting(false) }, [folder, section.key, pano, section.hires])              // (only a different video starts from nothing: asking again as it runs does not blank the page)
  useEffect(() => {
    let live = true; const tick = () => api.svVideo(folder, section.key, pano).then(v => { if (!live) return; setSt(v); if (v.running || v.exists || v.error) setStarting(false) }).catch(e => live && setErr((e as Error).message))
    tick(); const id = setInterval(tick, running ? 1500 : 30000); return () => { live = false; clearInterval(id) }
  }, [folder, section.key, pano, section.hires, running])
  const make = async () => { setErr(undefined); setStarting(true); try { const r = await api.makeSvVideo(folder, section.key, pano); if (!r.started && r.reason) { setErr(r.reason); setStarting(false); return } const v = await api.svVideo(folder, section.key, pano); setSt(v); if (v.running || v.exists || v.error) setStarting(false) } catch (e) { setErr((e as Error).message); setStarting(false) } }
  const pr = st?.progress, google = section.provider === 'google', hi = section.hires && google
  return (
    <div className="mt-2" aria-label={pano ? 'Look around' : 'Preview video'}>
      {pano && <div className="text-xs font-medium text-stone-600 dark:text-stone-400">Look around: the original 360° pictures, one at a time, with the camera held level along the road, which you can pan</div>}
      {st?.exists && (pano ? <PanoPlayer src={api.svVideoUrl(folder, section.key, true, hi)} label={`${NAME[section.provider]} ${section.id}`} maxPitch={google ? 24 : undefined} fps={st.fps} aimPath={aim.path} />
        : <div className="relative inline-block"><StepVideo videoRef={flat} preload="metadata" src={api.svVideoUrl(folder, section.key, false, hi)} className="max-h-[360px] rounded" aria-label="Preview video of this section" /><AimVideoOverlay video={flat} path={aim.path} /></div>)}
      {st?.exists && aimCam && aim.err && <p role="note" className="text-xs text-amber-700 dark:text-amber-400">{aimCam.label} cannot be drawn on this video: {aim.err}</p>}
      {st && !st.exists && !running && <button onClick={make} className="rounded bg-emerald-700 px-3 py-1 text-sm text-white">{pano ? 'Make a 360° video to look around in' : 'Make a preview video'}</button>}
      {st && !st.exists && !running && <span className="ml-2 text-xs text-stone-500">about {st.seconds} s long, made in the background and kept{pano && google ? `. Google gives flat views only, so this asks it for ${section.frames * (hi ? 60 : 16)} zoomed-in views (${hi ? 60 : 16} for each of the ${section.frames} panoramas, the ones nearest your track first) and stitches them; each is kept, nothing is asked twice` : ''}</span>}
      {running && (
        <div role="status" aria-label="Making the video" className="max-w-xl space-y-1 text-sm text-stone-600 dark:text-stone-400">
          <div className="flex items-center justify-between text-xs"><span>{pr ? `${pr.phase}: ${pr.done} of ${pr.total}` : 'starting…'}</span><span>{pr ? `${pr.pct}%` : ''}</span></div>
          <div role="progressbar" aria-label="Progress" aria-valuemin={0} aria-valuemax={100} aria-valuenow={pr?.pct} className="h-2 w-full overflow-hidden rounded bg-stone-200 dark:bg-stone-700">
            <div className={`h-full rounded bg-emerald-600 transition-[width] duration-500 ${pr ? '' : 'w-1/4 animate-pulse'}`} style={pr ? { width: `${pr.pct}%` } : undefined} /></div>
          <ul aria-label="What it is doing" className="max-h-32 overflow-auto rounded bg-stone-100 p-1.5 font-mono text-[11px] leading-snug text-stone-600 dark:bg-stone-800 dark:text-stone-300">{(st?.log ?? []).map((l, i) => <li key={i}>{l}</li>)}{!st?.log?.length && <li>waiting for the job to report…</li>}</ul>
        </div>
      )}
      {(err || (st && !st.exists && !running && st.error)) && <p role="alert" className="text-sm text-red-700 dark:text-red-400">{err || st?.error}</p>}
    </div>
  )
}

const RULE_ICON = { true: '✓', false: '✗', null: '?' } as const

/** The nearest street view to a clicked point, from each provider, with every rule that would rule each one out (no filters): the nearest capture runs first. */
function NearPanel({ folder, tz, probe, result, busy, log, error, onSearch, onPromoted, onClose }: { folder: string; tz: string; probe: { lat: number; lon: number }; result?: SvNearResult; busy: boolean; log: string[]; error?: string; onSearch: () => void; onPromoted: () => void; onClose: () => void }) {
  const [made, setMade] = useState<Record<string, string>>({}), [promoErr, setPromoErr] = useState<string>(), [big, setBig] = useState<{ provider: SvProvider; id: string }>()
  useEffect(() => { if (!big) return; const k = (e: KeyboardEvent) => { if (e.key === 'Escape') setBig(undefined) }; window.addEventListener('keydown', k); return () => window.removeEventListener('keydown', k) }, [big])
  const promote = async (it: SvNearItem) => { setPromoErr(undefined); try { const r = await api.promoteSv(folder, it, probe.lat, probe.lon); setMade(m => ({ ...m, [it.id]: r.id })); onPromoted() } catch (e) { setPromoErr((e as Error).message) } }
  return (
    <div className="rounded-lg bg-white p-4 shadow-sm dark:bg-stone-900" aria-label="Nearest street view to the clicked point">
      <div className="flex flex-wrap items-center justify-between gap-2"><h3 className="text-sm font-semibold">Nearest street view to {probe.lat.toFixed(5)}, {probe.lon.toFixed(5)}</h3><button onClick={onClose} className="text-xs underline">Close</button></div>
      <p className="mb-2 text-xs text-stone-600 dark:text-stone-400">As the crow flies, whatever the run did there. Each shows what would rule it out of the film: how far it is from the run, whether the run was on a road, which way it faces, how many pictures, the light and the footage.</p>
      {!result && !busy && <div className="flex flex-wrap items-center gap-3 text-sm"><button type="button" onClick={onSearch} className="rounded bg-emerald-700 px-3 py-1 text-white">Search for street view here</button><span className="text-xs text-stone-500">Nothing has been searched within 100 m of this point yet: asking Mapillary, Panoramax and Google takes a little while.</span></div>}
      {busy && <div role="status" className="text-sm text-stone-600 dark:text-stone-400"><div className="flex items-center gap-2"><span aria-hidden="true" className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-emerald-700 border-t-transparent" />Searching…</div><ul className="mt-1 space-y-0.5 font-mono text-xs text-stone-500" aria-label="Search log">{log.map((l, i) => <li key={i}>{l}</li>)}</ul></div>}
      {result && (Math.abs(result.lat - probe.lat) > 1e-6 || Math.abs(result.lon - probe.lon) > 1e-6) && <p className="mb-1 text-xs text-stone-500">From the search made at {result.lat.toFixed(5)}, {result.lon.toFixed(5)}, less than 100 m from here; distances are from there.</p>}
      {error && <p role="alert" className="text-sm text-red-700 dark:text-red-400">{error}</p>}
      {big && (
        <div role="dialog" aria-label="Larger picture" onClick={() => setBig(undefined)} className="fixed inset-0 z-[2000] flex cursor-zoom-out items-center justify-center bg-black/80 p-4">
          <img src={api.svNearImage(folder, big.provider, big.id, 1024)} alt={`${NAME[big.provider]} ${big.id}, larger`} className="max-h-full max-w-full rounded" />
          <button type="button" aria-label="Close the larger picture" className="absolute right-4 top-4 rounded bg-white/90 px-2 py-1 text-sm text-stone-900" onClick={() => setBig(undefined)}>Close</button>
        </div>
      )}
      {promoErr && <p role="alert" className="text-sm text-red-700 dark:text-red-400">{promoErr}</p>}
      {result && (
        <div className="grid gap-3 lg:grid-cols-3">
          {PROVIDERS.map(p => {
            const b = result.providers[p]
            return (
              <section key={p} aria-label={`${NAME[p]} near the point`} className="min-w-0">
                <h4 className="text-sm font-medium"><span className="mr-1 inline-block h-2.5 w-2.5 rounded-full align-middle" style={{ background: COLOUR[p] }} />{NAME[p]}{b.radius_m ? <span className="font-normal text-stone-500"> · searched {b.radius_m} m round</span> : ''}</h4>
                {b.error && <p className="text-xs text-amber-700 dark:text-amber-400">{b.error}</p>}
                {!b.error && b.items.length === 0 && <p className="text-xs text-stone-500">Nothing within {b.radius_m} m.</p>}
                <ul className="space-y-2">
                  {b.items.map(it => (
                    <li key={it.id} data-near-item={it.id} className="rounded border border-stone-200 p-2 text-xs dark:border-stone-700">
                      <div className="flex gap-2">
                        <button type="button" aria-label={`Show ${NAME[p]} ${it.id} larger`} title="Click to show larger" onClick={() => setBig({ provider: p, id: it.id })} className="shrink-0 cursor-zoom-in">
                          <img loading="lazy" src={api.svNearImage(folder, p, it.id, 256)} alt={`${NAME[p]} ${it.id}`} className="h-16 w-24 rounded object-cover" /></button>
                        <div className="min-w-0"><div className="font-medium">{it.distance_m} m away · {kindLabel2(it)}{it.section ? ` · section ${it.section}` : ''}</div>
                          <div className="text-stone-600 dark:text-stone-400">{[it.camera, it.size && `${it.size[0]}×${it.size[1]}`].filter(Boolean).join(' · ') || 'camera not known'}</div>
                          <div className="text-stone-600 dark:text-stone-400">Filmed {when(it.captured, tz)}{it.passed ? ` · you passed ${when(it.passed, tz)}` : ''}</div></div>
                      </div>
                      <div className={`mt-1 font-medium ${it.usable ? 'text-emerald-700 dark:text-emerald-400' : 'text-red-700 dark:text-red-400'}`}>{it.usable ? 'Nothing rules it out' : `Ruled out: ${it.ruled_out.length} reason${it.ruled_out.length === 1 ? '' : 's'}`}</div>
                      {it.section || made[it.id]
                        ? <div className="mt-1 text-stone-600 dark:text-stone-400">Already a candidate: section {it.section ?? made[it.id]}</div>
                        : <button type="button" onClick={() => promote(it)} className="mt-1 rounded border border-stone-300 px-2 py-0.5 dark:border-stone-600">Make this a candidate</button>}
                      <ul className="mt-0.5 space-y-0.5">{it.rules.map(r => <li key={r.key} data-rule={r.key} className={r.ok === false ? 'text-red-700 dark:text-red-400' : r.ok === null ? 'text-stone-500' : ''}><span aria-label={r.ok === false ? 'rules it out' : r.ok === null ? 'not known' : 'fine'} className="mr-1 inline-block w-3">{RULE_ICON[String(r.ok) as 'true' | 'false' | 'null']}</span>{r.text}</li>)}</ul>
                    </li>
                  ))}
                </ul>
              </section>
            )
          })}
        </div>
      )}
    </div>
  )
}
