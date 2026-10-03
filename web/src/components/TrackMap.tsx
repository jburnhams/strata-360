import { useEffect, useRef } from 'react'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import type { Divergence, ExtraLine, Poi, Stop, TrackClip, TrackLine } from '../api'
import { nearestIndex } from '../trackMath'

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
const dur = (s: number) => { const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), r = Math.round(s % 60); return h ? `${h} h ${String(m).padStart(2, '0')} min` : m ? `${m} min ${String(r).padStart(2, '0')} s` : `${r} s` }
/** The tooltip of a checkpoint: its name and what it joins, and how long the run stood still there (built as DOM so file names are text, not markup). */
function checkpointTip(name: string, desc: string, stop: Stop | undefined, tz: string) {
  const el = document.createElement('div'); const line = (text: string, bold = false) => { const d = document.createElement('div'); d.textContent = text; if (bold) d.style.fontWeight = '600'; el.appendChild(d) }
  const clock = (t: number) => { try { return new Intl.DateTimeFormat('en-GB', { timeZone: tz, hour: '2-digit', minute: '2-digit', hour12: false }).format(new Date(t * 1000)) } catch { return new Date(t * 1000).toISOString().slice(11, 16) } }
  line(name, true); if (desc) line(desc)
  if (stop) {
    if (stop.arrived != null && stop.left != null) line(`Stood still ${dur(stop.stopped_s)} (${clock(stop.arrived)} to ${clock(stop.left)})`, true)
    else line('Did not stop')
    line(`Within ${stop.radius_m} m for ${dur(stop.zone_s)} (${clock(stop.zone_in)} to ${clock(stop.zone_out)})`)
  }
  return el
}
const DETAIL_ZOOM_STEPS = 1.5          // this far in from the first view the map asks for the track in more detail

// The race on a Leaflet map (the background is the server's map tiles when `background` is given, else the track on a plain ground). Zoom with the buttons, the wheel, a double click or touch; drag to pan; the arrows button resets the view.
// Every clip has a marker at the middle of its stretch of track (the stretch is drawn thick; green = the newest script draft plays it), hover for its card, click to open it. Zooming in fetches the track for the
// part in view in more detail. Hovering the track moves the cursor shared with the charts.
export default function TrackMap({ base, clips, cursor, onCursor, onHoverClip, onOpenClip, fetchDetail, background, extras = [], pois = [], divergences = [], highlight = [], onHoverTrack, onToggleTrack, tz = 'Europe/Brussels' }: {
  tz?: string;   highlight?: ExtraLine[]; onHoverTrack?: (id: string | null) => void; onToggleTrack?: (id: string) => void; divergences?: Divergence[]; extras?: ExtraLine[]; pois?: Poi[]; background?: { url: string; tilePx: number }; base: TrackLine; clips: TrackClip[]; cursor: number | null; onCursor: (t: number | null) => void; onHoverClip: (c: TrackClip | null, x?: number, y?: number) => void
  onOpenClip: (id: string) => void; fetchDetail: (bbox: [number, number, number, number]) => Promise<TrackLine>
}) {
  const el = useRef<HTMLDivElement>(null), marks = useRef<L.Marker[]>([]), map = useRef<L.Map | null>(null), layer = useRef<L.LayerGroup | null>(null), dot = useRef<L.Marker | null>(null), detail = useRef<L.Polyline | null>(null), baseLine = useRef<L.Polyline | null>(null), extra = useRef<L.LayerGroup | null>(null), hl = useRef<L.LayerGroup | null>(null)
  const props = useRef({ base, onCursor, onHoverClip, onOpenClip, fetchDetail, onHoverTrack, onToggleTrack }); props.current = { base, onCursor, onHoverClip, onOpenClip, fetchDetail, onHoverTrack, onToggleTrack }   // handlers read the latest props without rebuilding the map

  useEffect(() => {
    if (!el.current || !base.lat.length) return
    const canvas = canvasOk(); const m = L.map(el.current, { preferCanvas: canvas, ...(canvas ? {} : { renderer: L.svg() }), attributionControl: false, zoomSnap: 0.5, minZoom: 1, scrollWheelZoom: false }); map.current = m
    m.on('click', () => m.scrollWheelZoom.enable()); m.getContainer().addEventListener('mouseleave', () => m.scrollWheelZoom.disable())          // the wheel scrolls the page until you click the map, then it zooms
    const pts = base.lat.map((la, i) => [la, base.lon[i]] as [number, number]); const line = L.polyline(pts, { color: '#15803d', weight: 2.5, opacity: 0.9 }).addTo(m); baseLine.current = line; extra.current = L.layerGroup().addTo(m); hl.current = L.layerGroup().addTo(m)
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
        if (m.getZoom() < z0 + DETAIL_ZOOM_STEPS) { detail.current?.remove(); detail.current = null; return }
        const b = m.getBounds().pad(0.25)
        try {
          const d = await props.current.fetchDetail([b.getSouth(), b.getWest(), b.getNorth(), b.getEast()]); if (!map.current) return
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
    const retina = background.tilePx === 512
    const t = L.tileLayer(background.url, { tileSize: background.tilePx, zoomOffset: retina ? -1 : 0, maxZoom: 19, maxNativeZoom: retina ? 19 : 18, keepBuffer: 2 }).addTo(m); t.setZIndex(0)
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
    for (const p of pois) {
      if (p.sym === 'checkpoint') {                                                              // where one route ends and the next begins: numbered, in race order
        const ic = L.divIcon({ className: '', html: `<div data-checkpoint="" style="min-width:22px;height:22px;padding:0 4px;box-sizing:border-box;border-radius:11px;background:#1d4ed8;color:#fff;border:2px solid #fff;font:700 12px/18px ui-sans-serif,sans-serif;text-align:center;box-shadow:0 1px 3px rgba(0,0,0,.55)">${p.n ?? ''}</div>`, iconSize: [22, 22], iconAnchor: [11, 11] })
        L.marker([p.lat, p.lon], { icon: ic, title: p.name, keyboard: false, zIndexOffset: 400 }).bindTooltip(checkpointTip(p.name, p.desc, p.stop, tz), { direction: 'top', offset: [0, -10] }).addTo(g); continue
      }
      const icon = L.divIcon({ className: '', html: `<div data-poi="" style="width:12px;height:12px;border-radius:2px;transform:rotate(45deg);background:#f59e0b;border:1.5px solid #fff;box-shadow:0 1px 3px rgba(0,0,0,.5)"></div>`, iconSize: [12, 12], iconAnchor: [6, 6] })
      const mk = L.marker([p.lat, p.lon], { icon, title: p.name || 'Point of interest', keyboard: false }).addTo(g)
      if (p.name || p.desc) mk.bindTooltip(p.name + (p.ele != null ? ` · ${Math.round(p.ele)} m` : '') + (p.desc ? ` — ${p.desc}` : ''), { direction: 'top', offset: [0, -6] })
    }
    for (const d of divergences) {                                                                // where the race track leaves the routes: the stretch in red and an exclamation mark at the farthest point
      L.polyline(d.line, { color: '#dc2626', weight: 4, opacity: 0.9, interactive: false }).addTo(g)
      const icon = L.divIcon({ className: '', html: '<div data-divergence="" style="width:20px;height:20px;border-radius:50%;background:#dc2626;color:#fff;border:1.5px solid #fff;font:700 13px/17px ui-sans-serif,sans-serif;text-align:center;box-shadow:0 1px 3px rgba(0,0,0,.5)">!</div>', iconSize: [20, 20], iconAnchor: [10, 10] })
      L.marker([d.lat, d.lon], { icon, title: `${d.peak_m} m off the route`, keyboard: false, zIndexOffset: 500 }).bindTooltip(`${d.peak_m} m off the route at most · ${(d.length_m / 1000).toFixed(2)} km long · km ${d.km} of the run`, { direction: 'top', offset: [0, -8] }).addTo(g)
    }
  }, [extras, pois, divergences, base, tz])

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

  return <div ref={el} className="h-[420px] w-full rounded-lg bg-stone-100 dark:bg-stone-950" role="application" aria-label="Race map" />
}
