import { useEffect, useMemo } from 'react'
import { CursorScope, LineChartGroup, useSharedCursor, type ChartMark, type ChartSpan, type GroupedChart } from 'strata-react'
import type { ReactNode } from 'react'
import type { TrackClip, TrackSeries } from '../api'
import { fmtLocal, fmtPace, hourStep, nearestIndex, niceTicks } from '../trackMath'

export type XMode = 'time' | 'km'

// Two charts on one horizontal axis (elapsed time in clock time, or distance): elevation with the lowest and highest of each stretch, and pace in min/km on a log axis, faster at the top. Stops are shaded; every clip has the same marker on both
// (green = the newest script draft plays it); the cursor is shared with the map; hover a marker for the clip's card, click it to open the clip.
// The charts, the shared cursor, the markers and the shading are strata-react's (LineChartGroup); what stays here is the track's own axes, and carrying the cursor to and from the map.

/** Carries the cursor between the charts' scope and the map: the pointer over a chart goes out as a time; the map's time goes in as a position. */
function CursorBridge({ cursor, onCursor, toX, toT }: { cursor: number | null; onCursor: (t: number | null) => void; toX: (t: number) => number; toT: (x: number) => number }) {
  const shared = useSharedCursor('map-bridge')
  const other = shared?.other ?? null
  useEffect(() => { onCursor(other == null ? null : toT(other)) }, [other])                          // eslint-disable-line react-hooks/exhaustive-deps
  const setPlayback = shared?.setPlayback
  useEffect(() => { setPlayback?.(cursor == null ? null : toX(cursor)) }, [cursor, setPlayback])    // eslint-disable-line react-hooks/exhaustive-deps
  return null
}

export default function TrackCharts({ series, clips, xMode, tz, cursor, onCursor, renderClipCard, onOpenClip }: {
  series: TrackSeries; clips: TrackClip[]; xMode: XMode; tz: string; cursor: number | null; onCursor: (t: number | null) => void
  renderClipCard?: (c: TrackClip) => ReactNode; onOpenClip: (id: string) => void
}) {
  const xs = useMemo(() => { let last = 0; return (xMode === 'time' ? series.t : series.km.map(k => (k == null ? last : (last = k)))) as number[] }, [series, xMode])
  const toX = (t: number) => xs[nearestIndex(series.t, t)], toT = (x: number) => series.t[nearestIndex(xs, x)]
  const t0 = Date.parse(series.start_utc)
  const spans = useMemo<ChartSpan[]>(() => {                                                          // runs of bins spent (nearly) standing still
    const out: ChartSpan[] = []; let from: number | null = null
    series.moving.forEach((m, i) => { const lo = m < 0.2; if (lo && from == null) from = i; if ((!lo || i === series.moving.length - 1) && from != null) { out.push({ from: xs[from], to: xs[lo ? i : i - 1], label: 'Stopped', tone: 'neutral' }); from = null } })
    return out
  }, [series, xs])
  const placed = useMemo(() => clips.filter(c => c.covered && c.t_mid != null), [clips])
  const marks = useMemo<ChartMark[]>(() => placed.map(c => ({ x: toX(c.t_mid!), label: `Clip ${c.label}`, colour: c.used ? 'var(--color-success)' : 'var(--color-muted-foreground)' })), [placed, xs])  // eslint-disable-line react-hooks/exhaustive-deps
  const clipOf = (m: ChartMark) => placed.find(c => `Clip ${c.label}` === m.label)
  const charts = useMemo<GroupedChart[]>(() => {
    const mid = (i: number) => series.alt[i] ?? ((series.alt_lo[i] ?? 0) + (series.alt_hi[i] ?? 0)) / 2
    const paced = xs.map((x, i) => ({ x, y: series.pace[i] })).filter((p): p is { x: number; y: number } => p.y != null && p.y > 0)
    return [
      { seriesLabel: 'Elevation', label: 'Elevation', series: xs.map((x, i) => ({ x, y: mid(i) })), formatY: v => `${Math.round(v)} m`, yMin: Math.floor(Math.min(...series.alt_lo.concat(series.alt).filter((v): v is number => v != null)) / 50) * 50,
        range: { low: xs.map((_, i) => series.alt_lo[i] ?? mid(i)), high: xs.map((_, i) => series.alt_hi[i] ?? mid(i)), label: 'Lowest to highest in each stretch' } },
      { seriesLabel: 'Pace', label: 'Pace', series: paced, formatY: v => `${fmtPace(v)} /km`, yScale: 'log', yInvert: true },
    ]
  }, [series, xs])
  const hours = series.duration_s / 3600
  const xTicks = ({ min, max }: { min: number; max: number }) => {
    if (xMode === 'km') return niceTicks(min, max, 8)
    const s = hourStep(hours) * 3600; const out: number[] = []; for (let t = Math.ceil(min / s) * s; t <= max; t += s) out.push(t); return out
  }
  return (
    <CursorScope>
      <LineChartGroup label="Elevation and pace along the track" charts={charts} formatX={x => xMode === 'km' ? `${Math.round(x * 10) / 10} km` : fmtLocal(t0 + x * 1000, tz)} xLabel={xMode === 'km' ? 'Distance' : 'Time'}
        xTicks={xTicks} spans={spans} marks={marks} onMarkSelect={m => { const c = clipOf(m); if (c) onOpenClip(c.id) }} renderMarkCard={m => { const c = clipOf(m); return c && renderClipCard ? renderClipCard(c) : m.label }} />
      <CursorBridge cursor={cursor} onCursor={onCursor} toX={toX} toT={toT} />
    </CursorScope>
  )
}
