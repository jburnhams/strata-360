import { useEffect, useRef, useState } from 'react'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { api, type Divergence, type EndMarkers, type ExtraLine, type Photo, type Poi, type TileStatus, type TrackClip, type TrackLine } from '../api'
import { nearestIndex } from '../trackMath'
import { addEnds, addPois, addTiles } from '../mapLayers'

const GREEN = '#16a34a', GREY = '#78716c', ROUTE = '#2563eb', RUN = '#a3a3a3'
const canvasOk = () => { try { return !!document.createElement('canvas').getContext('2d') } catch { return false } }       // the canvas renderer is quicker for a long line; without a 2D context (some test environments) Leaflet draws SVG
const MARK_W = 42, MARK_H = 22
const FAN: [number, number][] = [[0, 0], [0, -MARK_H], [0, MARK_H], [-MARK_W, 0], [MARK_W, 0], [0, -2 * MARK_H], [0, 2 * MARK_H], [-MARK_W, -MARK_H], [MARK_W, -MARK_H], [-MARK_W, MARK_H], [MARK_W, MARK_H]]
/** Markers that would sit on top of each other at this zoom are moved apart (a small fan around their place); the thick stretch of track still shows where each clip really is. Zooming in lets them settle. */
function spread(m: L.Map, markers: L.Marker[]) {
  const placed: { x: number; y: number }[] = []
  for (const mk of markers) {
    const p = m.latLngToContainerPoint(mk.getLatLng()); const el = mk.getElement(); if (!el) continue
    const [dx, dy] = FAN.find(([ox, oy]) => !placed.some(q => Math.abs(q.x - (p.x + ox)) < MARK_W && Math.abs(q.y - (p.y + oy)) < MARK_H)) ?? FAN[FAN.length - 1]
    placed.push({ x: p.x + dx, y: p.y + dy }); el.style.marginLeft = `${-MARK_W / 2 + 2 + dx}px`; el.style.marginTop = `${-MARK_H / 2 + dy}px`
  }
}
const DETAIL_ZOOM_STEPS = 1.5          // this far in from the first view the map asks for the track in more detail

// The race on a Leaflet map (the background is the server's map tiles when `background` is given, else the track on a plain ground). Zoom with the buttons, the wheel, a double click or touch; drag to pan; the arrows button resets the view.
// Every clip has a marker at the middle of its stretch of track (the stretch is drawn thick; green = the newest script draft plays it), hover for its card, click to open it. Zooming in fetches the track for the
// part in view in more detail. Hovering the track moves the cursor shared with the charts.
function MapView({ base, clips = [], cursor = null, onCursor = () => {}, onHoverClip = () => {}, onOpenClip = () => {}, fetchDetail, background, focus, height = 'h-[420px]', label = 'Race map', decorate, onMapClick, runColor = '#15803d', runWeight = 2.5, fitTo, svg = false, extras = [], pois = [], divergences = [], highlight = [], onHoverTrack, onToggleTrack, tz = 'Europe/Brussels', ends, highlightCheckpoints = [], ringEnds = false, photos = [], photoThumb, onOpenPhoto }: {
  /** A stretch of the run (lat, lon) or a place to pick out in orange and zoom to: the map opens on it (the reset button still goes to the whole race). */ focus?: { line?: [number, number][]; point?: { lat: number; lon: number }; label?: string }; height?: string; label?: string
  /** Extra layers of a page's own, drawn over the race (redrawn when the function changes), a click on the map, the colour of the run, and a place to move the view to when `fitTo.key` changes. */ decorate?: (m: L.Map, g: L.LayerGroup) => void; onMapClick?: (lat: number, lon: number) => void; runColor?: string; runWeight?: number; fitTo?: { pts: [number, number][]; key: string }; svg?: boolean
  photos?: Photo[]; photoThumb?: (id: string) => string; onOpenPhoto?: (p: Photo) => void; ringEnds?: boolean; highlightCheckpoints?: number[]; ends?: EndMarkers | null; tz?: string;   highlight?: ExtraLine[]; onHoverTrack?: (id: string | null) => void; onToggleTrack?: (id: string) => void; divergences?: Divergence[]; extras?: ExtraLine[]; pois?: Poi[]; background?: { url: string; tilePx: number }; base: TrackLine; clips?: TrackClip[]; cursor?: number | null; onCursor?: (t: number | null) => void; onHoverClip?: (c: TrackClip | null, x?: number, y?: number) => void
  onOpenClip?: (id: string) => void; fetchDetail?: (bbox: [number, number, number, number]) => Promise<TrackLine>
}) {
  const el = useRef<HTMLDivElement>(null), marks = useRef<L.Marker[]>([]), map = useRef<L.Map | null>(null), layer = useRef<L.LayerGroup | null>(null), dot = useRef<L.Marker | null>(null), detail = useRef<L.Polyline | null>(null), baseLine = useRef<L.Polyline | null>(null), extra = useRef<L.LayerGroup | null>(null), hl = useRef<L.LayerGroup | null>(null)
  const props = useRef({ onMapClick, base, onCursor, onHoverClip, onOpenClip, fetchDetail, onHoverTrack, onToggleTrack }); props.current = { onMapClick, base, onCursor, onHoverClip, onOpenClip, fetchDetail, onHoverTrack, onToggleTrack }; const fitFocus = useRef<() => void>(() => {})   // handlers read the latest props without rebuilding the map

  useEffect(() => {
    if (!el.current || !base.lat.length) return
    const canvas = canvasOk(); const m = L.map(el.current, { preferCanvas: canvas && !svg, ...(canvas && !svg ? {} : { renderer: L.svg() }), attributionControl: false, zoomSnap: 0.5, minZoom: 1, scrollWheelZoom: false }); map.current = m
    m.on('click', (e: L.LeafletMouseEvent) => { m.scrollWheelZoom.enable(); props.current.onMapClick?.(e.latlng.lat, e.latlng.lng) }); m.getContainer().addEventListener('mouseleave', () => m.scrollWheelZoom.disable())          // the wheel scrolls the page until you click the map, then it zooms
    const pts = base.lat.map((la, i) => [la, base.lon[i]] as [number, number]); const line = L.polyline(pts, { color: runColor, weight: runWeight, opacity: 0.9 }).addTo(m); baseLine.current = line; extra.current = L.layerGroup().addTo(m); hl.current = L.layerGroup().addTo(m)
    m.fitBounds(line.getBounds(), { padding: [20, 20] }); const home = m.getBounds(); const z0 = m.getZoom(); layer.current = L.layerGroup().addTo(m)
    line.on('mousemove', (e: L.LeafletMouseEvent) => {                                         // the nearest point of the track to the mouse
      const b = props.current.base; let best = 0, bd = Infinity
      for (let i = 0; i < b.lat.length; i++) { const d = (b.lat[i] - e.latlng.lat) ** 2 + ((b.lon[i] - e.latlng.lng) * Math.cos((e.latlng.lat * Math.PI) / 180)) ** 2; if (d < bd) { bd = d; best = i } }
      props.current.onCursor(b.t[best])
    }); line.on('mouseout', () => props.current.onCursor(null))
    const Reset = L.Control.extend({ onAdd() { const a = L.DomUtil.create('a', 'leaflet-bar leaflet-control') as HTMLAnchorElement; a.href = '#'; a.title = 'Reset the view'; a.setAttribute('role', 'button'); a.setAttribute('aria-label', 'Reset the view'); a.style.cssText = 'width:30px;height:30px;line-height:30px;text-align:center;background:white;color:#333;font-size:16px;text-decoration:none'; a.textContent = '⤢'
      L.DomEvent.on(a, 'click', (ev: Event) => { L.DomEvent.preventDefault(ev); m.fitBounds(home) }); L.DomEvent.disableClickPropagation(a); return a } })
    new Reset({ position: 'topleft' }).addTo(m)
    let timer: number | undefined
    const more = () => {                                                                        // zoomed in: the track in view in more detail, replacing the coarse line there
      window.clearTimeout(timer)
      timer = window.setTimeout(async () => {
        if (!map.current) return
        if (!props.current.fetchDetail || m.getZoom() < z0 + DETAIL_ZOOM_STEPS) { detail.current?.remove(); detail.current = null; return }
        const b = m.getBounds().pad(0.25)
        try {
          const d = await props.current.fetchDetail!([b.getSouth(), b.getWest(), b.getNorth(), b.getEast()]); if (!map.current) return
          detail.current?.remove(); detail.current = L.polyline(d.lat.map((la, i) => [la, d.lon[i]] as [number, number]), { color: '#15803d', weight: 3, opacity: 1, interactive: false }).addTo(m)
        } catch { /* the coarse line stays */ }
      }, 250)
    }
    m.on('moveend', more); m.on('zoomend', () => spread(m, marks.current))
    return () => { window.clearTimeout(timer); m.remove(); map.current = null; layer.current = null; dot.current = null; detail.current = null; baseLine.current = null; extra.current = null; hl.current = null }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [base])

  useEffect(() => {                                                                             // the map tiles behind the track (the server fetches and caches them; the key never reaches the browser)
    const m = map.current; if (!m || !background) return
    const t = addTiles(m, background)
    return () => { t.remove() }
  }, [background?.url, background?.tilePx, base])         // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {                                                                             // the other tracks (each run and each route) under the race track, and the points of interest of all of them
    const g = extra.current; if (!g) return; g.clearLayers()
    for (const e of extras) {
      const pts = e.lat.map((la, i) => [la, e.lon[i]] as [number, number]); if (pts.length < 2) continue
      const route = e.kind === 'route'
      L.polyline(pts, { color: route ? ROUTE : RUN, weight: route ? 3 : 2, opacity: route ? 0.9 : 0.8, dashArray: route ? '6 6' : undefined, interactive: true })
        .on('mouseover', () => props.current.onHoverTrack?.(e.id)).on('mouseout', () => props.current.onHoverTrack?.(null)).on('click', () => props.current.onToggleTrack?.(e.id)).bindTooltip(e.name, { sticky: true }).addTo(g)
    }
    baseLine.current?.bringToFront()
    addPois(g, pois, tz, highlightCheckpoints)
    addEnds(g, ends, tz, ringEnds)
    for (const p of photos) {                                                                   // a camera icon for each photo, at where it was taken (its own GPS, else the run at that time); hover for the picture and when, click to open it
      if (!p.loc) continue
      const icon = L.divIcon({ className: '', html: `<div data-photo-marker="${p.id}" style="width:24px;height:24px;border-radius:6px;background:#7c3aed;border:2px solid #fff;box-shadow:0 1px 3px rgba(0,0,0,.55);display:flex;align-items:center;justify-content:center"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2.2" stroke-linejoin="round"><path d="M3 8h4l2-3h6l2 3h4v11H3z"/><circle cx="12" cy="13" r="3.5"/></svg></div>`, iconSize: [24, 24], iconAnchor: [12, 12] })
      const tip = document.createElement('div'); tip.style.maxWidth = '180px'
      if (photoThumb) { const im = document.createElement('img'); im.src = photoThumb(p.id); im.alt = p.name; im.style.cssText = 'width:176px;border-radius:4px;display:block'; tip.appendChild(im) }
      const cap = document.createElement('div'); cap.textContent = `${p.name}${p.flag ? ' ⚠' : ''}`; cap.style.fontWeight = '600'; tip.appendChild(cap)
      L.marker([p.loc.lat, p.loc.lon], { icon, title: p.name, keyboard: false, zIndexOffset: 450 }).bindTooltip(tip, { direction: 'top', offset: [0, -10] }).on('click', () => onOpenPhoto?.(p)).addTo(g)
    }
    for (const d of divergences) {                                                                // where the race track leaves the routes: the stretch in red and an exclamation mark at the farthest point
      L.polyline(d.line, { color: '#dc2626', weight: 4, opacity: 0.9, interactive: false }).addTo(g)
      const icon = L.divIcon({ className: '', html: '<div data-divergence="" style="width:20px;height:20px;border-radius:50%;background:#dc2626;color:#fff;border:1.5px solid #fff;font:700 13px/17px ui-sans-serif,sans-serif;text-align:center;box-shadow:0 1px 3px rgba(0,0,0,.5)">!</div>', iconSize: [20, 20], iconAnchor: [10, 10] })
      L.marker([d.lat, d.lon], { icon, title: `${d.peak_m} m off the route`, keyboard: false, zIndexOffset: 500 }).bindTooltip(`${d.peak_m} m off the route at most · ${(d.length_m / 1000).toFixed(2)} km long · km ${d.km} of the run`, { direction: 'top', offset: [0, -8] }).addTo(g)
    }
  }, [extras, pois, divergences, base, tz, ends, ringEnds, highlightCheckpoints.join(','), photos])      // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {                                                                             // the tracks being pointed at or picked in the list: bold yellow with a black outline, on top of everything
    const g = hl.current; if (!g) return; g.clearLayers()
    for (const e of highlight) {
      const pts = e.lat.map((la, i) => [la, e.lon[i]] as [number, number]); if (pts.length < 2) continue
      L.polyline(pts, { color: '#000', weight: 9, opacity: 1, interactive: false }).addTo(g); L.polyline(pts, { color: '#facc15', weight: 5, opacity: 1, interactive: false }).addTo(g)
    }
  }, [highlight, base])

  useEffect(() => {                                                                             // the clips: the stretch each covers, and a marker with the clip number
    const g = layer.current; if (!g) return; g.clearLayers(); marks.current = []
    for (const c of clips) {
      if (!c.covered || c.lat == null || c.lon == null) continue
      const col = c.used ? GREEN : GREY
      if (c.stretch && c.stretch.length > 1) L.polyline(c.stretch, { color: col, weight: 6, opacity: 0.85, interactive: false }).addTo(g)
      const icon = L.divIcon({ className: '', html: `<div style="background:${col};color:#fff;border:1.5px solid #fff;border-radius:10px;font:600 10px/18px ui-monospace,monospace;text-align:center;box-shadow:0 1px 3px rgba(0,0,0,.45)">${c.label}</div>`, iconSize: [38, 20], iconAnchor: [19, 10] })
      const mk = L.marker([c.lat, c.lon], { icon, title: `Clip ${c.label}`, keyboard: true }).addTo(g); marks.current.push(mk)
      mk.on('mouseover', (e: L.LeafletMouseEvent) => props.current.onHoverClip(c, e.originalEvent.clientX, e.originalEvent.clientY)); mk.on('mousemove', (e: L.LeafletMouseEvent) => props.current.onHoverClip(c, e.originalEvent.clientX, e.originalEvent.clientY))
      mk.on('mouseout', () => props.current.onHoverClip(null)); mk.on('click', () => props.current.onOpenClip(c.id))
    }
    if (map.current) spread(map.current, marks.current)
  }, [clips, base])

  useEffect(() => {                                                                             // the cursor shared with the charts
    const m = map.current; if (!m) return
    if (cursor == null) { dot.current?.remove(); dot.current = null; return }
    const i = nearestIndex(base.t, cursor), ll: [number, number] = [base.lat[i], base.lon[i]]
    if (dot.current) dot.current.setLatLng(ll)
    else dot.current = L.marker(ll, { icon: L.divIcon({ className: '', html: '<div data-cursor-dot="" style="width:14px;height:14px;border-radius:50%;background:#f59e0b;border:2px solid #fff;box-shadow:0 0 3px rgba(0,0,0,.6)"></div>', iconSize: [14, 14], iconAnchor: [7, 7] }), interactive: false, keyboard: false, zIndexOffset: 1000 }).addTo(m)
  }, [cursor, base])

  useEffect(() => {                                                                             // a page's own layers over the race (the street view page: road parts, sections, what was clicked)
    const m = map.current; if (!m || !decorate) return
    const g = L.layerGroup().addTo(m); decorate(m, g); return () => { g.remove() }
  }, [decorate, base])         // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {                                                                             // the view moves to what was chosen
    const m = map.current; if (!m || !fitTo?.pts.length) return
    m.fitBounds(L.latLngBounds(fitTo.pts), { padding: [60, 60], maxZoom: 17 })
  }, [fitTo?.key])         // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {                                                                             // the stretch of the run or the place this map is about: orange with a white edge, and the map opens on it
    const m = map.current; if (!m || !focus) return
    const g = L.layerGroup().addTo(m); let b: L.LatLngBounds | null = null
    if (focus.line && focus.line.length > 1) {
      L.polyline(focus.line, { color: '#fff', weight: 10, opacity: 0.95, interactive: false }).addTo(g); const hl = L.polyline(focus.line, { color: '#f97316', weight: 6, opacity: 1, interactive: false }).addTo(g); if (focus.label) hl.bindTooltip(focus.label, { sticky: true })
      for (const p of [focus.line[0], focus.line[focus.line.length - 1]]) L.circleMarker(p, { radius: 5, color: '#fff', weight: 2, fillColor: '#f97316', fillOpacity: 1, interactive: false }).addTo(g)
      b = hl.getBounds()
    } else if (focus.point) {
      L.circleMarker([focus.point.lat, focus.point.lon], { radius: 11, color: '#f97316', weight: 3, fillOpacity: 0, interactive: false }).addTo(g)
      const dot = L.circleMarker([focus.point.lat, focus.point.lon], { radius: 5, color: '#fff', weight: 2, fillColor: '#f97316', fillOpacity: 1 }).addTo(g); if (focus.label) dot.bindTooltip(focus.label); b = L.latLngBounds([[focus.point.lat, focus.point.lon]])
    }
    const go = () => { if (!b || !b.isValid()) return; if (b.getSouthWest().equals(b.getNorthEast())) m.setView(b.getCenter(), 16); else m.fitBounds(b.pad(0.35), { maxZoom: 17 }) }
    const Zoom = L.Control.extend({ onAdd() { const a = L.DomUtil.create('a', 'leaflet-bar leaflet-control') as HTMLAnchorElement; a.href = '#'; a.title = 'Zoom to this'; a.setAttribute('role', 'button'); a.setAttribute('aria-label', 'Zoom to this'); a.style.cssText = 'width:30px;height:30px;line-height:30px;text-align:center;background:white;color:#f97316;font-size:18px;text-decoration:none'; a.textContent = '◎'
      L.DomEvent.on(a, 'click', (ev: Event) => { L.DomEvent.preventDefault(ev); go() }); L.DomEvent.disableClickPropagation(a); return a } })
    const ctl = new Zoom({ position: 'topleft' }).addTo(m); fitFocus.current = go; go(); return () => { g.remove(); ctl.remove(); fitFocus.current = () => {} }
  }, [focus?.line, focus?.point?.lat, focus?.point?.lon, focus?.label, base])         // eslint-disable-line react-hooks/exhaustive-deps

  return <div ref={el} className={`${height} w-full rounded-lg bg-stone-100 dark:bg-stone-950`} role="application" aria-label={label} data-focus={focus ? '' : undefined} />
}

type ViewProps = Parameters<typeof MapView>[0]

/** The race map, the one map of the app. Given the race track (`base`) and what to draw it is the overview map (or the street view page's, with its own layers in `decorate`). Given only a `folder` it fetches the run, the route tracks, the start, the
 *  finish, the checkpoints and the map behind them itself, and with a `span` (a time range, epoch seconds) or a `point` it picks that part of the run or that place out in orange and zooms to it: the map on the page of a clip, a gap, a photo or a
 *  street view section. The arrows button shows the whole race and the ring button comes back to what was picked out. */
export default function TrackMap(props: Omit<ViewProps, 'base'> & { base?: TrackLine; folder?: string; span?: [number, number]; point?: { lat: number; lon: number } }) {
  if (props.base) return <MapView {...(props as ViewProps)} />
  return <FolderMap {...props} />
}

function FolderMap({ folder, span, point, label, tz = 'Europe/Brussels', height = 'h-72', focus: _focus, ...rest }: Omit<ViewProps, 'base'> & { folder?: string; span?: [number, number]; point?: { lat: number; lon: number } }) {
  const [run, setRun] = useState<TrackLine>(), [part, setPart] = useState<TrackLine>(), [tiles, setTiles] = useState<TileStatus>(), [err, setErr] = useState<string>()
  const [routes, setRoutes] = useState<ExtraLine[]>([]), [pois, setPois] = useState<Poi[]>([]), [ends, setEnds] = useState<EndMarkers | null>(null)
  useEffect(() => {
    if (!folder) return; let live = true; setErr(undefined)
    api.tilesStatus().then(t => live && setTiles(t)).catch(e => live && setTiles({ ok: false, style: 'tf-landscape', error: (e as Error).message }))
    api.trackLine(folder, undefined, 2000).then(r => live && setRun(r)).catch(e => live && setErr((e as Error).message))
    api.tracks(folder).then(async l => {
      if (!live) return; setPois(l.pois ?? []); setEnds(l.markers ?? null)
      const rs = await Promise.all(l.tracks.filter(t => t.kind === 'route' && !t.error).map(t => api.tracksLine(folder, t.id).then(x => ({ id: t.id, kind: t.kind, name: t.name, lat: x.lat, lon: x.lon }) as ExtraLine).catch(() => null)))
      if (live) setRoutes(rs.filter((x): x is ExtraLine => !!x))
    }).catch(() => {})
    return () => { live = false }
  }, [folder])
  const key = span ? `${span[0]}-${span[1]}` : ''
  useEffect(() => {
    if (!folder) return; let live = true; setPart(undefined); if (!span) return
    api.trackLine(folder, undefined, 500, span).then(r => live && setPart(r)).catch(() => {}); return () => { live = false }
  }, [folder, key])         // eslint-disable-line react-hooks/exhaustive-deps
  const line = part && part.lat.length > 1 ? part.lat.map((la, i) => [la, part.lon[i]] as [number, number]) : undefined
  if (err) return <p className="text-sm text-amber-700">The map needs the race track: {err}</p>
  if (!run) return <div className={`${height} animate-pulse rounded-lg bg-stone-100 dark:bg-stone-800`} aria-label="Loading the map" />
  return (
    <div aria-label="Where on the route">
      <MapView {...rest} base={run} height={height} label={label ? 'Map of the route with this picked out' : 'Map of the route'} tz={tz} background={tiles?.ok ? { url: api.tileUrl(tiles.style), tilePx: tiles.tile_px ?? 256 } : undefined} extras={routes} pois={pois} ends={ends}
        focus={line || point ? { line, point: line ? undefined : point, label } : undefined} />
      <div className="mt-1 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-stone-600 dark:text-stone-400">
        <span><span className="mr-1 inline-block h-1.5 w-4 align-middle" style={{ background: '#f97316' }} />{span ? 'the part of the run this covers' : point ? 'where it was taken' : 'this'}</span>
        <span><span className="mr-1 inline-block h-1 w-4 align-middle" style={{ background: '#15803d' }} />the run</span>
        {routes.length > 0 && <span><span className="mr-1 inline-block h-0 w-4 border-t-2 border-dashed align-middle" style={{ borderColor: '#2563eb' }} />route tracks</span>}
        <span>⤢ the whole race · ◎ back to this</span>
        {tiles && !tiles.ok && <span className="text-amber-700">map background off</span>}
      </div>
    </div>
  )
}
