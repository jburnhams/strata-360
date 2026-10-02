import { useMemo, useRef } from 'react'
import type { TrackClip, TrackSeries } from '../api'
import { fmtLocal, fmtPace, hourStep, linear, logScale, nearestIndex, niceTicks, paceRange, paceTicks, range, runs } from '../trackMath'

export type XMode = 'time' | 'km'
const W = 1000, H = 150, ML = 54, MR = 12, MT = 14, MB = 22, PW = W - ML - MR, PH = H - MT - MB

// Two charts on one horizontal axis (elapsed time in clock time, or distance): elevation on a truncated axis, and pace in min/km on a log axis, faster at the top. Stops are shaded; every clip has the same marker on both
// (green = the newest script draft plays it); the cursor is shared with the map; hover a marker for the clip's card, click it to open the clip.
export default function TrackCharts({ series, clips, xMode, tz, cursor, onCursor, onHoverClip, onOpenClip }: {
  series: TrackSeries; clips: TrackClip[]; xMode: XMode; tz: string; cursor: number | null; onCursor: (t: number | null) => void
  onHoverClip: (c: TrackClip | null, x?: number, y?: number) => void; onOpenClip: (id: string) => void
}) {
  const xs = useMemo(() => { let last = 0; return (xMode === 'time' ? series.t : series.km.map(k => (k == null ? last : (last = k)))) as number[] }, [series, xMode])
  const x0 = xs[0] ?? 0, x1 = xs[xs.length - 1] ?? 1, sx = linear(x0, x1, ML, ML + PW)
  const xOfT = (t: number) => sx(xs[nearestIndex(series.t, t)])
  const stops = useMemo(() => {                                                                    // runs of bins spent (nearly) standing still, as x ranges
    const out: [number, number][] = []; let from: number | null = null
    series.moving.forEach((m, i) => { const lo = m < 0.2; if (lo && from == null) from = i; if ((!lo || i === series.moving.length - 1) && from != null) { out.push([from, lo ? i : i - 1]); from = null } })
    return out
  }, [series])
  const placed = clips.filter(c => c.covered && c.t_mid != null)
  const svgs = [useRef<SVGSVGElement>(null), useRef<SVGSVGElement>(null)]
  const move = (e: React.MouseEvent<SVGRectElement>, k: number) => {
    const r = svgs[k].current?.getBoundingClientRect(); if (!r || r.width <= 0) return
    const px = ((e.clientX - r.left) / r.width) * W, v = x0 + ((px - ML) / PW) * (x1 - x0); onCursor(series.t[nearestIndex(xs, v)])
  }
  const ci = cursor == null ? null : nearestIndex(series.t, cursor)
  const alt = range(series.alt_lo.concat(series.alt_hi)), [plo, phi] = paceRange(series.pace)
  const sa = linear(alt[0], alt[1], MT + PH, MT), sp = logScale(plo, phi, MT, MT + PH)               // faster (smaller min/km) at the top
  const hours = (series.duration_s / 3600), step = hourStep(hours), t0 = Date.parse(series.start_utc)
  const xTicks = xMode === 'time' ? Array.from({ length: Math.floor(hours / step) + 1 }, (_, i) => i * step * 3600).map(t => ({ x: xOfT(t), label: fmtLocal(t0 + t * 1000, tz) })) : niceTicks(x0, x1, 8).map(v => ({ x: sx(v), label: `${v} km` }))
  const marker = (c: TrackClip) => {
    const x = xOfT(c.t_mid!), col = c.used ? '#16a34a' : '#78716c'
    return (
      <g key={c.id} role="button" tabIndex={0} aria-label={`Clip ${c.label}`} className="cursor-pointer outline-none" onClick={() => onOpenClip(c.id)} onKeyDown={e => { if (e.key === 'Enter') onOpenClip(c.id) }}
        onMouseEnter={e => onHoverClip(c, e.clientX, e.clientY)} onMouseMove={e => onHoverClip(c, e.clientX, e.clientY)} onMouseLeave={() => onHoverClip(null)}>
        <line x1={x} x2={x} y1={MT} y2={MT + PH} stroke={col} strokeWidth="1" strokeDasharray="3 3" opacity="0.7" />
        <circle cx={x} cy={MT} r="4.5" fill={col} stroke="white" strokeWidth="1" />
        <line x1={x} x2={x} y1={MT} y2={MT + PH} stroke="transparent" strokeWidth="10" />
      </g>)
  }
  const pane = (k: number, title: string, label: string, body: React.ReactNode, yTicks: { y: number; label: string }[], readout: string | null) => (
    <svg ref={svgs[k]} viewBox={`0 0 ${W} ${H}`} className="w-full" role="group" aria-label={label}>
      <text x={ML} y={9} className="fill-stone-500 text-[10px]">{title}</text>
      {readout && <text x={W - MR} y={9} textAnchor="end" className="fill-stone-700 text-[10px] dark:fill-stone-300">{readout}</text>}
      {stops.map(([a, b], i) => <rect key={i} data-stop="" x={sx(xs[a])} width={Math.max(sx(xs[b]) - sx(xs[a]), 1)} y={MT} height={PH} className="fill-stone-300/40 dark:fill-stone-700/40" />)}
      {yTicks.map(t => <g key={t.label}><line x1={ML} x2={ML + PW} y1={t.y} y2={t.y} className="stroke-stone-200 dark:stroke-stone-800" /><text x={ML - 4} y={t.y + 3} textAnchor="end" className="fill-stone-500 text-[10px]">{t.label}</text></g>)}
      {xTicks.map(t => <text key={t.label + t.x} x={t.x} y={H - 6} textAnchor="middle" className="fill-stone-500 text-[10px]">{t.label}</text>)}
      {body}
      {placed.map(marker)}
      {ci != null && <line x1={xOfT(series.t[ci])} x2={xOfT(series.t[ci])} y1={MT} y2={MT + PH} className="stroke-amber-500" strokeWidth="1.2" data-cursor="" />}
      <rect x={ML} y={MT} width={PW} height={PH} fill="transparent" onMouseMove={e => move(e, k)} onMouseLeave={() => onCursor(null)} />
    </svg>
  )
  const line = (pts: [number, number][]) => pts.map((p, i) => `${i ? 'L' : 'M'}${p[0].toFixed(1)},${p[1].toFixed(1)}`).join('')
  const band = (() => { const lo = xs.map((x, i) => [sx(x), sa(series.alt_lo[i] ?? series.alt[i] ?? alt[0])] as [number, number]), hi = xs.map((x, i) => [sx(x), sa(series.alt_hi[i] ?? series.alt[i] ?? alt[0])] as [number, number]); return line(hi) + line(lo.reverse()).replace(/^M/, 'L') + 'Z' })()
  const altPath = line(xs.map((x, i) => series.alt[i] == null ? null : [sx(x), sa(series.alt[i]!)] as [number, number]).filter((p): p is [number, number] => p != null))
  const pacePaths = runs(xs.map(sx), series.pace.map(p => (p == null ? null : sp(Math.min(Math.max(p, plo), phi)))))
  return (
    <div className="space-y-1">
      {pane(0, 'elevation (m)', 'Elevation chart', <><path d={band} className="fill-emerald-600/15" /><path d={altPath} fill="none" className="stroke-emerald-700 dark:stroke-emerald-400" strokeWidth="1.4" /></>,
        niceTicks(alt[0], alt[1], 4).map(v => ({ y: sa(v), label: String(Math.round(v)) })), ci != null && series.alt[ci] != null ? `${Math.round(series.alt[ci]!)} m` : null)}
      {pane(1, 'pace (min/km, log scale, faster is higher)', 'Pace chart', pacePaths.map((r, i) => <path key={i} d={line(r)} fill="none" className="stroke-sky-700 dark:stroke-sky-400" strokeWidth="1.2" />),
        paceTicks(plo, phi).map(v => ({ y: sp(v), label: fmtPace(v) })), ci != null ? (series.pace[ci] != null ? `${fmtPace(series.pace[ci])} /km` : 'stopped') : null)}
    </div>
  )
}
