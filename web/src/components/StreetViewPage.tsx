import { useEffect, useMemo, useRef, useState } from 'react'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { api } from '../api'
import type { StreetView, SvChoice, SvProvider, SvSection, SvSectionInfo, SvStretch, TileStatus, TrackClip } from '../api'
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
export default function StreetViewPage({ folder }: { folder: string }) {
  const [tick, setTick] = useState(0)
  const data = usePoll(() => api.streetview(folder), 5000, [folder, tick])
  const [tiles, setTiles] = useState<TileStatus>()
  const [sel, setSel] = useState<{ kind: 'section' | 'stretch'; id: string }>()
  const [shown, setShown] = useState<Record<string, boolean>>({ mapillary: true, panoramax: true, google: true, '360': true, '2d': true, clips: true })
  const [err, setErr] = useState<string>(), [clips, setClips] = useState<TrackClip[]>([])
  useEffect(() => { api.trackClips(folder).then(r => setClips(r.clips.filter(c => c.covered && c.stretch?.length))).catch(() => setClips([])) }, [folder])
  useEffect(() => { api.tilesStatus().then(setTiles).catch(() => setTiles({ ok: false, style: 'tf-landscape', error: 'no map background' })) }, [])
  useEffect(() => { setSel(undefined) }, [folder])
  const roads = useMemo(() => data?.roads, [data?.roads?.id])                                // (a new copy comes with every poll: the map is only rebuilt when the road parts really change)
  const sections = useMemo(() => data?.sections ?? [], [data])
  const visible = sections.filter(s => shown[s.provider] && shown[s.kind])
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
      {data && roads && sections.length > 0 && <Candidates folder={folder} sections={sections} sel={sel} onSel={setSel} onChoose={async (key, c) => { await api.setStreetviewChoice(folder, key, c).catch(e => setErr((e as Error).message)); setTick(t => t + 1) }} />}
      {data && roads && (
        <div className="rounded-lg bg-white p-4 shadow-sm dark:bg-stone-900">
          <Filters shown={shown} setShown={setShown} data={data} />
          <SvMap roads={roads.stretches} run={roads.run} sections={visible} clips={shown.clips ? clips : []} scale={scale} sel={sel} onSel={setSel} background={tiles?.ok ? { url: api.tileUrl(tiles.style), tilePx: tiles.tile_px ?? 256 } : undefined} />
          <Legend scale={scale} hasClips={clips.length > 0} />
          <p className="mt-1 flex flex-wrap gap-x-4 text-xs text-stone-600 dark:text-stone-400">
            <span><span className="mr-1 inline-block h-1.5 w-4 align-middle" style={{ background: '#f59e0b' }} />road part of the run (click one)</span>
            {PROVIDERS.map(p => <span key={p}><span className="mr-1 inline-block h-2.5 w-2.5 rounded-full align-middle" style={{ background: COLOUR[p] }} />{NAME[p]}</span>)}
            <span>360° = sees every way · 2D = faces one way</span>{tiles?.ok && tiles.credit && <span>{tiles.credit}</span>}
          </p>
        </div>
      )}
      {(section || chosenStretch) && <Detail folder={folder} section={section} stretch={chosenStretch} sections={sections.filter(s => s.stretch === chosenStretch?.id)} onSel={setSel} />}
      {roads && <List title="Every section found" sections={visible} sel={sel} onSel={setSel} none={sections.length === 0} />}
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
              {k === 'google' && <div className="text-xs text-stone-500">Google's terms do not allow keeping or re-using its pictures: shown here for looking only, never saved.</div>}
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

function Filters({ shown, setShown, data }: { shown: Record<string, boolean>; setShown: (f: Record<string, boolean>) => void; data: StreetView }) {
  const box = (k: string, label: string, colour?: string) => (
    <label key={k} className="flex items-center gap-1 text-sm"><input type="checkbox" checked={shown[k]} onChange={e => setShown({ ...shown, [k]: e.target.checked })} />{colour && <span className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: colour }} />}{label}</label>
  )
  return <div className="mb-2 flex flex-wrap gap-4">{PROVIDERS.map(p => box(p, `${NAME[p]}${data.providers[p] ? ` (${data.sections.filter(s => s.provider === p).length})` : ''}`, COLOUR[p]))}{box('360', '360° cameras')}{box('2d', '2D cameras')}{box('clips', 'Camera clips')}</div>
}

function SvMap({ roads, run, sections, clips, scale, sel, onSel, background }: { roads: SvStretch[]; run: [number, number][]; sections: SvSectionInfo[]; clips: TrackClip[]; scale: { lo: number; hi: number }; sel?: { kind: string; id: string }; onSel: (s: { kind: 'section' | 'stretch'; id: string }) => void; background?: { url: string; tilePx: number } }) {
  const el = useRef<HTMLDivElement>(null), map = useRef<L.Map | null>(null), layers = useRef<L.LayerGroup | null>(null), onSelRef = useRef(onSel); onSelRef.current = onSel
  useEffect(() => {
    if (!el.current) return
    const m = L.map(el.current, { renderer: L.svg(), attributionControl: false, zoomSnap: 0.5, scrollWheelZoom: false }); map.current = m               // (svg: a few hundred short lines, and no canvas to redraw after the page is left)
    m.on('click', () => m.scrollWheelZoom.enable()); m.getContainer().addEventListener('mouseleave', () => m.scrollWheelZoom.disable())
    const all = L.polyline(run); if (run.length) m.fitBounds(all.getBounds(), { padding: [20, 20] }); else m.setView([50, 5], 8)
    layers.current = L.layerGroup().addTo(m)
    return () => { m.remove(); map.current = null; layers.current = null }
  }, [run])
  useEffect(() => {
    const m = map.current; if (!m || !background) return
    const retina = background.tilePx === 512
    const t = L.tileLayer(background.url, { tileSize: background.tilePx, zoomOffset: retina ? -1 : 0, maxZoom: 19, maxNativeZoom: retina ? 19 : 18 }).addTo(m); t.setZIndex(0); return () => { t.remove() }
  }, [background?.url, background?.tilePx, run]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {                                                                              // redrawn when the data, the filters or the selection change
    const g = layers.current; if (!g) return
    g.clearLayers(); L.polyline(run, { color: '#78716c', weight: 2, opacity: 0.7, interactive: false }).addTo(g)
    for (const c of clips) {                                                                      // the stretch of the run each camera clip covers, coloured by how long the clip is, with a marker numbered like the clip
      const col = rampColour(c.duration_s, scale.lo, scale.hi)
      L.polyline(c.stretch!, { color: '#fff', weight: 9, opacity: 0.9, interactive: false }).addTo(g); L.polyline(c.stretch!, { color: col, weight: 6, opacity: 1, interactive: false }).addTo(g)
      if (c.lat != null && c.lon != null) L.marker([c.lat, c.lon], { title: `Clip ${c.label} · ${dur(c.duration_s)}`, keyboard: false, icon: L.divIcon({ className: '', iconSize: [30, 16], html: `<div data-clip-marker style="background:${col};color:#fff;text-shadow:0 0 2px #000;font:600 10px/16px sans-serif;border-radius:8px;text-align:center;border:1.5px solid #fff">${c.label}</div>` }) }).addTo(g)
    }
    for (const r of roads) {
      const on = sel?.kind === 'stretch' && sel.id === r.id
      L.polyline(r.line, { color: '#f59e0b', weight: on ? 9 : 6, opacity: on ? 1 : 0.8 }).bindTooltip(`${r.names.join(', ') || r.highways.join(', ')} · ${span(r)} · ${metres(r.length_m)}`).on('click', () => onSelRef.current({ kind: 'stretch', id: r.id })).addTo(g)
    }
    for (const s of sections) {
      const on = sel?.kind === 'section' && sel.id === s.id, pts = s.items.map(i => [i.lat, i.lon] as [number, number])
      L.polyline(pts, { color: '#fff', weight: on ? 10 : 8, opacity: 0.9, interactive: false }).addTo(g); L.polyline(pts, { color: rampColour(s.max_s, scale.lo, scale.hi), weight: on ? 7 : 5, opacity: 1, dashArray: s.kind === '2d' ? undefined : '3 5', interactive: false }).addTo(g)
      const mid = s.items[Math.floor(s.items.length / 2)]
      const icon = L.divIcon({ className: '', iconSize: [34, 20], html: `<div style="background:${COLOUR[s.provider]};color:#fff;font:600 11px/20px sans-serif;border-radius:10px;text-align:center;border:${on ? '2px solid #000' : s.choice ? '2px solid #f59e0b' : '1.5px solid #fff'}">${LETTER[s.provider]} ${kindLabel(s)}</div>` })
      L.marker([mid.lat, mid.lon], { icon, title: `${NAME[s.provider]} ${kindLabel(s)} ${span(s)}`, keyboard: true, zIndexOffset: on ? 1000 : 0 }).on('click', () => onSelRef.current({ kind: 'section', id: s.id })).addTo(g)
    }
  }, [roads, run, sections, clips, scale, sel])
  useEffect(() => {                                                                              // the map moves to what was chosen
    const m = map.current; if (!m || !sel) return
    const pts = sel.kind === 'stretch' ? roads.find(r => r.id === sel.id)?.line : sections.find(s => s.id === sel.id)?.items.map(i => [i.lat, i.lon] as [number, number])
    if (pts?.length) m.fitBounds(L.latLngBounds(pts), { padding: [60, 60], maxZoom: 17 })
  }, [sel?.kind, sel?.id]) // eslint-disable-line react-hooks/exhaustive-deps
  return <div ref={el} role="application" aria-label="Map of the road parts and street view coverage" className="h-[480px] w-full overflow-hidden rounded-lg bg-stone-200 dark:bg-stone-800" />
}

function Detail({ folder, section, stretch, sections, onSel }: { folder: string; section?: SvSectionInfo; stretch?: SvStretch; sections: SvSectionInfo[]; onSel: (s: { kind: 'section' | 'stretch'; id: string }) => void }) {
  const [big, setBig] = useState<{ provider: SvProvider; id: string }>()
  useEffect(() => { setBig(undefined) }, [section?.id])
  return (
    <div className="rounded-lg bg-white p-4 shadow-sm dark:bg-stone-900">
      {stretch && <div className="text-sm"><span className="font-medium">{stretch.names.join(', ') || 'Unnamed road'}</span> · {stretch.highways.join(', ')} · {span(stretch)} · {metres(stretch.length_m)} of the run on this road
        {!section && <span className="text-stone-600 dark:text-stone-400"> · {sections.length ? `${sections.length} section${sections.length === 1 ? '' : 's'} of street view` : 'no street view found'}</span>}</div>}
      {!section && sections.length > 0 && <ul className="mt-2 flex flex-wrap gap-2">{sections.map(s => <li key={s.id}><button onClick={() => onSel({ kind: 'section', id: s.id })} className="rounded border border-stone-300 px-2 py-0.5 text-xs dark:border-stone-600">{NAME[s.provider]} {kindLabel(s)} · {metres(s.length_m)}</button></li>)}</ul>}
      {section && (
        <div className="mt-2">
          <div className="text-sm"><span className="mr-1 inline-block h-2.5 w-2.5 rounded-full align-middle" style={{ background: COLOUR[section.provider] }} /><span className="font-medium">{NAME[section.provider]} · {kindLabel(section)}</span> · {span(section)} · {metres(section.length_m)} · {section.frames} pictures{section.spacing_m != null ? `, one every ${section.spacing_m} m` : ''}
            {section.years.length > 0 && ` · ${section.years.join(', ')}`}{section.camera && ` · ${section.camera}`}{section.size && ` · ${section.size[0]}×${section.size[1]}`}</div>
          <div className="text-xs text-stone-600 dark:text-stone-400">{section.kind === '360' ? 'A 360° camera: the view can be turned to face along the road.' : `A flat camera, facing: ${facing(section)} (relative to the way the runner went).`}</div>
          <ul className="mt-2 grid grid-cols-2 gap-2 md:grid-cols-4">
            {previews(section).map(({ it, label }) => (
              <li key={it.id}><button onClick={() => setBig({ provider: section.provider, id: it.id })} className="block w-full text-left" aria-label={`Picture at ${label}`}>
                <img loading="lazy" src={api.streetviewImage(folder, section.provider, it.id, 256)} alt={`${NAME[section.provider]} ${label}`} className="aspect-[3/2] w-full rounded object-cover" /><span className="text-xs text-stone-600 dark:text-stone-400">{label}</span></button></li>
            ))}
          </ul>
          {big && <div className="mt-2"><img src={api.streetviewImage(folder, big.provider, big.id, 1024)} alt="Larger picture" className="max-h-[480px] rounded" /><button className="block text-xs underline" onClick={() => setBig(undefined)}>Close the larger picture</button></div>}
        </div>
      )}
    </div>
  )
}

function List({ title, sections, sel, onSel, none }: { title: string; sections: SvSectionInfo[]; sel?: { kind: string; id: string }; onSel: (s: { kind: 'section' | 'stretch'; id: string }) => void; none: boolean }) {
  if (!sections.length) return <p className="rounded-lg bg-white p-4 text-sm text-stone-600 shadow-sm dark:bg-stone-900 dark:text-stone-400">{none ? 'No street view sections yet: run a provider above.' : 'Nothing matches the filters.'}</p>
  return (
    <div className="overflow-x-auto rounded-lg bg-white p-4 shadow-sm dark:bg-stone-900">
      <h3 className="mb-1 text-sm font-semibold">{title}</h3>
      <table className="w-full text-left text-sm">
        <thead className="text-xs text-stone-500"><tr><th className="pr-3">Source</th><th className="pr-3">Camera</th><th className="pr-3">Where</th><th className="pr-3">Length</th><th className="pr-3">Pictures</th><th className="pr-3">Spacing</th><th className="pr-3">Year</th><th className="pr-3">Facing</th><th className="pr-3">Size</th><th className="pr-3">Quality</th><th>Overlaps</th></tr></thead>
        <tbody>
          {sections.map(s => (
            <tr key={s.id} onClick={() => onSel({ kind: 'section', id: s.id })} className={`cursor-pointer border-t border-stone-200 dark:border-stone-700 ${sel?.kind === 'section' && sel.id === s.id ? 'bg-emerald-100 dark:bg-emerald-950' : 'hover:bg-stone-100 dark:hover:bg-stone-800'}`}>
              <td className="pr-3"><button className="underline" onClick={e => { e.stopPropagation(); onSel({ kind: 'section', id: s.id }) }}>{NAME[s.provider]} {s.id}</button></td><td className="pr-3">{kindLabel(s)}</td><td className="pr-3">{span(s)} <span className="text-stone-500">({s.stretch})</span></td>
              <td className="pr-3">{metres(s.length_m)}</td><td className="pr-3">{s.frames}</td><td className="pr-3">{s.spacing_m != null ? `${s.spacing_m} m` : '–'}</td><td className="pr-3">{s.years.join(', ') || '–'}</td><td className="pr-3">{facing(s)}</td><td className="pr-3">{s.size ? `${s.size[0]}×${s.size[1]}` : '–'}</td><td className="pr-3">{s.quality?.score != null ? `${s.quality.grade} (${s.quality.score})` : '–'}</td><td>{s.overlaps.length ? <span className="text-amber-700 dark:text-amber-400">{s.overlaps.join(', ')}</span> : '–'}</td>
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
function Candidates({ folder, sections, sel, onSel, onChoose }: { folder: string; sections: SvSectionInfo[]; sel?: { kind: string; id: string }; onSel: (s: { kind: 'section'; id: string }) => void; onChoose: (key: string, c: SvChoice | 'none') => void }) {
  const [order, setOrder] = useState<'quality' | 'route'>('quality')
  const by = new Map(sections.map(s => [s.id, s])), chosen = sections.filter(s => s.plausible && s.choice)
  const ok = sections.filter(s => s.plausible).sort((a, b) => order === 'route' ? a.km0 - b.km0 : (b.quality?.score ?? -1) - (a.quality?.score ?? -1) || a.km0 - b.km0)                 // best first; the ones not scored yet last
  return (
    <div className="rounded-lg bg-white p-4 shadow-sm dark:bg-stone-900" aria-label="Sections that could be used">
      <div className="flex flex-wrap items-center justify-between gap-2"><h3 className="text-sm font-semibold">Sections that could be used in the film</h3>
        <label className="flex items-center gap-1 text-xs">Order <select value={order} onChange={e => setOrder(e.target.value as 'quality' | 'route')} className="rounded border border-stone-300 bg-white px-1 py-0.5 dark:border-stone-600 dark:bg-stone-900"><option value="quality">best quality first</option><option value="route">along the route</option></select></label></div>
      <p className="mb-2 text-xs text-stone-600 dark:text-stone-400">{ok.length} of {sections.length} sections have enough pictures, close enough together, to make a clip. Mark the ones the film may use: only those are shown to the script writer, and the plan makes a clip of any it picks.
        {chosen.length > 0 && ` Chosen: ${chosen.length} (${chosen.filter(s => s.choice === 'must').length} must include).`} Pictures are credited CC BY-SA to Mapillary and Panoramax contributors.</p>
      {ok.length === 0 && <p className="text-sm text-stone-600 dark:text-stone-400">None of the sections found has enough pictures yet.</p>}
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
            {s.light?.warning && <p className="text-xs font-medium text-red-700 dark:text-red-400" role="note" data-light>⚠ {s.light.warning}</p>}
            {s.overlaps.length > 0 && <p className="text-xs text-amber-700 dark:text-amber-400" role="note">Overlaps the same road as {s.overlaps.map(id => { const o = by.get(id); return o ? `${NAME[o.provider]} ${o.id} (${span(o)})` : id }).join(', ')}: choose the one you prefer, or both and let the writer pick.</p>}
            <div className="mt-1 flex flex-wrap items-center gap-3">
              <ul className="flex gap-1">{previews(s).filter((_, i, a) => a.length <= 3 || i % Math.ceil(a.length / 3) === 0).slice(0, 3).map(({ it, label }) => <li key={it.id}><img loading="lazy" src={api.streetviewImage(folder, s.provider, it.id, 256)} alt={`${NAME[s.provider]} ${s.id} ${label}`} className="h-16 w-24 rounded object-cover" /></li>)}</ul>
              <fieldset className="flex gap-3 text-sm" aria-label={`Use ${NAME[s.provider]} ${s.id} in the film`}>
                {CHOICES.map(c => <label key={c.v} className="flex items-center gap-1"><input type="radio" name={`use-${s.key}`} checked={(s.choice ?? 'none') === c.v} onChange={() => onChoose(s.key, c.v)} />{c.label}</label>)}
              </fieldset>
            </div>
          </li>
        ))}
      </ul>
      {sections.length > ok.length && <p className="mt-2 text-xs text-stone-500">{sections.length - ok.length} more sections are too short or too sparse to use; they are in the list below.</p>}
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
