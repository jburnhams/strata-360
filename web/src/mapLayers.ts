import L from 'leaflet'
import type { EndMarkers, Poi, Stop } from './api'

export const ROUTE_BLUE = '#2563eb'

/** The map tiles behind the track (the server fetches and caches them; the key never reaches the browser). */
export function addTiles(m: L.Map, background: { url: string; tilePx: number }) {
  const retina = background.tilePx === 512
  const t = L.tileLayer(background.url, { tileSize: background.tilePx, zoomOffset: retina ? -1 : 0, maxZoom: 19, maxNativeZoom: retina ? 19 : 18, keepBuffer: 2 }).addTo(m); t.setZIndex(0); return t
}

/** The route tracks (planning only), in blue; `dashed` for the thin ones. Returns the lines. */
export function addRoutes(m: L.Map | L.LayerGroup, routes: { id: string; name: string; pts: [number, number][] }[], o: { weight?: number; dashed?: boolean } = {}) {
  return routes.filter(r => r.pts.length > 1).map(r => L.polyline(r.pts, { color: ROUTE_BLUE, weight: o.weight ?? 3, opacity: 0.9, dashArray: o.dashed ? '6 6' : undefined, interactive: false }).bindTooltip(r.name, { sticky: true }).addTo(m))
}

// The markers every map of the race shares: the start, the finish line and where the run ended, the numbered checkpoints (where one route ends and the next begins) and the other points of interest. Used by the race map on the overview and by the little
// maps of the film items.
const dur = (s: number) => { const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), r = Math.round(s % 60); return h ? `${h} h ${String(m).padStart(2, '0')} min` : m ? `${m} min ${String(r).padStart(2, '0')} s` : `${r} s` }
/** The tooltip of a checkpoint: its name and what it joins, and how long the run stood still there (built as DOM so file names are text, not markup). */
function checkpointTip(name: string, desc: string, stop: Stop | undefined, tz: string) {
  const el = document.createElement('div'); const line = (text: string, bold = false) => { const d = document.createElement('div'); d.textContent = text; if (bold) d.style.fontWeight = '600'; el.appendChild(d) }
  const clock = (t: number) => { try { return new Intl.DateTimeFormat('en-GB', { timeZone: tz, hour: '2-digit', minute: '2-digit', hour12: false }).format(new Date(t * 1000)) } catch { return new Date(t * 1000).toISOString().slice(11, 16) } }
  line(name, true); if (desc) line(desc)
  if (stop) {
    if (stop.arrived != null && stop.left != null) line(`Time here ${dur(stop.stopped_s)} (${clock(stop.arrived)} to ${clock(stop.left)})`, true)
    else line(`Did not slow down within ${stop.radius_m} m`)
  }
  return el
}

const dayTime = (t: number, tz: string) => { try { return new Intl.DateTimeFormat('en-GB', { timeZone: tz, weekday: 'short', day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', hour12: false }).format(new Date(t * 1000)).replace(',', '') } catch { return new Date(t * 1000).toISOString().slice(0, 16).replace('T', ' ') } }
/** The facts of a stop away from the checkpoints (the table on the overview and the card on the map show the same): where along the run, when it began and ended, how long, and how small a place it stayed in. */
export function stopFacts(p: Poi, tz: string) {
  const s = p.stop; const km = /km ([\d.]+)/.exec(p.desc)?.[1]
  return { name: p.name, km: km ? Number(km) : null, arrived: s?.arrived != null ? dayTime(s.arrived, tz) : '', left: s?.left != null ? dayTime(s.left, tz) : '', duration: s ? dur(s.stopped_s) : '', area_m: s?.radius_m ?? null }
}

/** The checkpoints (numbered, `highlight` ringed in yellow) and the other points of interest of the tracks, added to the layer `g`. */
export function addPois(g: L.LayerGroup, pois: Poi[], tz: string, highlightCheckpoints: number[] = []) {
    for (const p of pois) {
      if (p.sym === 'checkpoint') {                                                              // where one route ends and the next begins: numbered, in race order
        const on = p.n != null && highlightCheckpoints.includes(p.n); const z = on ? 32 : 22
        const ic = L.divIcon({ className: '', html: `<div data-checkpoint=""${on ? ' data-checkpoint-hl=""' : ''} style="min-width:${z}px;height:${z}px;padding:0 4px;box-sizing:border-box;border-radius:${z / 2}px;background:${on ? '#facc15' : '#1d4ed8'};color:${on ? '#000' : '#fff'};border:${on ? '3px solid #000' : '2px solid #fff'};font:700 ${on ? 15 : 12}px/${z - (on ? 6 : 4)}px ui-sans-serif,sans-serif;text-align:center;box-shadow:0 1px 3px rgba(0,0,0,.55)">${p.n ?? ''}</div>`, iconSize: [z, z], iconAnchor: [z / 2, z / 2] })
        L.marker([p.lat, p.lon], { icon: ic, title: p.name, keyboard: false, zIndexOffset: on ? 900 : 400 }).bindTooltip(checkpointTip(p.name, p.desc, p.stop, tz), { direction: 'top', offset: [0, -10] }).addTo(g); continue
      }
      if (p.sym === 'stop') {                                                                    // a stop away from the checkpoints, the start and the finish: the run stayed in one small place for a good while
        const ic = L.divIcon({ className: '', html: `<div data-stop="" style="width:22px;height:22px;border-radius:50%;background:#b45309;color:#fff;border:2px solid #fff;font:700 11px/18px ui-sans-serif,sans-serif;text-align:center;box-shadow:0 1px 3px rgba(0,0,0,.55)">⏸</div>`, iconSize: [22, 22], iconAnchor: [11, 11] })
        const f = stopFacts(p, tz), tip = document.createElement('div'); for (const [t, bold] of [[f.name, true], [`Stopped ${f.duration}`, true], [`km ${f.km ?? '?'} of the run`, false], [`${f.arrived} to ${f.left}`, false], [`staying within ${f.area_m} m`, false]] as [string, boolean][]) { const d = document.createElement('div'); d.textContent = t; if (bold) d.style.fontWeight = '600'; tip.appendChild(d) }
        L.marker([p.lat, p.lon], { icon: ic, title: p.name, keyboard: false, zIndexOffset: 350 }).bindTooltip(tip, { direction: 'top', offset: [0, -10] }).addTo(g); continue
      }
      const icon = L.divIcon({ className: '', html: `<div data-poi="" style="width:12px;height:12px;border-radius:2px;transform:rotate(45deg);background:#f59e0b;border:1.5px solid #fff;box-shadow:0 1px 3px rgba(0,0,0,.5)"></div>`, iconSize: [12, 12], iconAnchor: [6, 6] })
      const mk = L.marker([p.lat, p.lon], { icon, title: p.name || 'Point of interest', keyboard: false }).addTo(g)
      if (p.name || p.desc) mk.bindTooltip(p.name + (p.ele != null ? ` · ${Math.round(p.ele)} m` : '') + (p.desc ? ` — ${p.desc}` : ''), { direction: 'top', offset: [0, -6] })
    }
}

/** The start (green), the finish line (the end of the last route) and where the run ended (red); `ringEnds` rings the finish line. */
export function addEnds(g: L.LayerGroup, ends: EndMarkers | null | undefined, tz: string, ringEnds = false) {
    if (ends) {                                                                                  // the start (green), the finish line (the end of the last route) and where the run ended (red)
      const ring = ringEnds ? ' data-end-hl="" ' : ''; const glow = ringEnds ? '0 0 0 4px #facc15, 0 0 0 6px #000' : '0 1px 4px rgba(0,0,0,.6)'            // the finish row of the Tracks list is pointed at or picked: the finish line is ringed
      const dot = (kind: string, html: string, bg: string, tip: string, ll: [number, number], title: string, z: number) => L.marker(ll, {
        icon: L.divIcon({ className: '', html: `<div data-end="${kind}" style="width:26px;height:26px;border-radius:50%;background:${bg};color:#fff;border:2.5px solid #fff;font:700 13px/21px ui-sans-serif,sans-serif;text-align:center;box-shadow:0 1px 4px rgba(0,0,0,.6)">${html}</div>`, iconSize: [26, 26], iconAnchor: [13, 13] }), title, keyboard: false, zIndexOffset: z,
      }).bindTooltip(tip, { direction: 'top', offset: [0, -12] }).addTo(g)
      const when = (t: number) => { try { return new Intl.DateTimeFormat('en-GB', { timeZone: tz, weekday: 'short', day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', hour12: false }).format(new Date(t * 1000)).replace(',', '') } catch { return '' } }
      dot('start', '▶', '#16a34a', `Start · ${when(ends.start.t)}`, [ends.start.lat, ends.start.lon], 'Start', 700)
      if (ends.finish) L.marker([ends.finish.lat, ends.finish.lon], { icon: L.divIcon({ className: '', html: `<div data-end="finish"${ring}style="width:26px;height:26px;border-radius:50%;border:2.5px solid #fff;background:conic-gradient(#000 25%, #fff 0 50%, #000 0 75%, #fff 0);box-shadow:${glow}"></div>`, iconSize: [26, 26], iconAnchor: [13, 13] }), title: 'Finish line', keyboard: false, zIndexOffset: 650 + (ringEnds ? 300 : 0) }).bindTooltip('Finish line (the end of the last route)', { direction: 'top', offset: [0, -12] }).addTo(g)
      dot('end', '■', '#dc2626', `End of the run · km ${ends.end.km} · ${when(ends.end.t)}`, [ends.end.lat, ends.end.lon], 'End of the run', 680)
    }
}
