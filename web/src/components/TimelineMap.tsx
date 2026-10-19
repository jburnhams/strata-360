import { useEffect, useMemo, useState } from 'react'
import { api, type PlanSegment, type TrackLine } from '../api'
import { colour } from './FilmStrip'

const mmss = (s: number) => `${Math.floor(s / 60)}:${(s % 60).toFixed(1).padStart(4, '0')}`
const short = (id: string) => id.replace(/^CAM_/, '').replace(/_D$/, '').slice(-9)

// The map strip under the timeline (implementation plan D1): the race's line, and a dot where each window of the film was filmed (its position from gps/context.py, sent with the plan).
// The selected windows are drawn larger; click a dot to select its window. Nothing is drawn without a race track or positions.
export default function TimelineMap({ folder, segments, range, onSelect }: { folder: string; segments: PlanSegment[]; range: [number, number] | null; onSelect: (k: number, extend: boolean) => void }) {
  const [line, setLine] = useState<TrackLine | null>(null)
  const placed = segments.some(g => g.pos)
  useEffect(() => { if (placed) api.trackLine(folder, undefined, 600).then(setLine).catch(() => setLine(null)) }, [folder, placed])
  const view = useMemo(() => {
    const pts: [number, number][] = [...(line ? line.lat.map((la, i) => [la, line.lon[i]] as [number, number]) : []), ...segments.flatMap(g => (g.pos ? [[g.pos.lat, g.pos.lon] as [number, number]] : []))]
    if (!pts.length) return null
    const lat0 = pts.reduce((a, p) => a + p[0], 0) / pts.length, kx = Math.cos((lat0 * Math.PI) / 180)
    const xy = (la: number, lo: number): [number, number] => [lo * kx, -la]
    const P = pts.map(p => xy(p[0], p[1])), xs = P.map(p => p[0]), ys = P.map(p => p[1])
    const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys), pad = Math.max(x1 - x0, y1 - y0, 1e-4) * 0.06
    return { xy, box: `${x0 - pad} ${y0 - pad} ${x1 - x0 + 2 * pad} ${y1 - y0 + 2 * pad}`, r: Math.max(x1 - x0, y1 - y0, 1e-4) * 0.012 }
  }, [line, segments])
  if (!placed || !view) return null
  const path = line ? line.lat.map((la, i) => view.xy(la, line.lon[i]).join(',')).join(' ') : ''
  return (
    <svg viewBox={view.box} className="h-28 w-full rounded-lg border border-stone-200 bg-stone-50 dark:border-stone-800 dark:bg-stone-950" role="img" aria-label="Where each window of the film was filmed">
      {path && <polyline points={path} fill="none" stroke="currentColor" strokeOpacity={0.35} strokeWidth={1.5} vectorEffect="non-scaling-stroke" />}
      {segments.map((g, k) => {
        if (!g.pos) return null
        const [x, y] = view.xy(g.pos.lat, g.pos.lon), on = !!range && k >= range[0] && k <= range[1]
        return (
          <circle key={g.id} cx={x} cy={y} r={on ? view.r * 1.8 : view.r} fill={colour(g)} stroke={on ? 'currentColor' : 'white'} strokeWidth={view.r * 0.25} className="cursor-pointer" onClick={e => onSelect(k, e.shiftKey)}>
            <title>{`${mmss(g.film_start_s)} ${short(g.clip)}${g.pos.km != null ? ` · km ${g.pos.km}` : ''}`}</title>
          </circle>
        )
      })}
    </svg>
  )
}
