// Axis maths and formatting for the race charts: linear and log scales, ticks, the data ranges that make the axes truncated, and the nearest point to a mouse position.
export type Scale = (v: number) => number
export const linear = (d0: number, d1: number, r0: number, r1: number): Scale => (v) => r0 + ((v - d0) / ((d1 - d0) || 1)) * (r1 - r0)
export const logScale = (d0: number, d1: number, r0: number, r1: number): Scale => { const a = Math.log(d0), b = Math.log(d1); return (v) => r0 + ((Math.log(v) - a) / ((b - a) || 1)) * (r1 - r0) }

const nums = (v: (number | null | undefined)[]) => v.filter((x): x is number => x != null && Number.isFinite(x))
const quantile = (sorted: number[], q: number) => sorted[Math.min(sorted.length - 1, Math.max(0, Math.round(q * (sorted.length - 1))))]

/** The data's own range with a margin: an axis that does not start at zero. A flat series gets a range of its own so the line is not squashed onto the edge. */
export function range(values: (number | null | undefined)[], pad = 0.05): [number, number] {
  const v = nums(values); if (!v.length) return [0, 1]
  let lo = Math.min(...v), hi = Math.max(...v); if (hi - lo < 1e-9) { lo -= 1; hi += 1 }
  const m = (hi - lo) * pad; return [lo - m, hi + m]
}

/** Pace axis for a log scale: the 2nd to 98th percentile of the paces, kept between `floor` and `cap` min/km, widened a little on both sides (ratios, since the scale is logarithmic). */
export function paceRange(values: (number | null | undefined)[], floor = 2.5, cap = 30): [number, number] {
  const v = nums(values).sort((a, b) => a - b); if (!v.length) return [floor, cap]
  let lo = Math.max(quantile(v, 0.02), floor), hi = Math.min(quantile(v, 0.98), cap); if (hi / lo < 1.2) { lo /= 1.15; hi *= 1.15 }
  return [Math.max(lo / 1.08, floor / 1.2), Math.min(hi * 1.08, cap * 1.2)]
}

/** About `count` round tick values between a and b (1, 2, 5 times a power of ten). */
export function niceTicks(a: number, b: number, count = 5): number[] {
  if (!(b > a)) return [a]
  const raw = (b - a) / Math.max(count, 1), p = Math.pow(10, Math.floor(Math.log10(raw))), f = raw / p, step = (f < 1.5 ? 1 : f < 3.5 ? 2 : f < 7.5 ? 5 : 10) * p, out: number[] = []
  for (let v = Math.ceil(a / step) * step; v <= b + 1e-9; v += step) out.push(Math.round(v / step) * step)
  return out
}

const PACES = [2, 2.5, 3, 3.5, 4, 5, 6, 7, 8, 10, 12, 15, 20, 25, 30, 40, 60]
/** Round paces (min/km) inside a log axis. */
export const paceTicks = (lo: number, hi: number) => PACES.filter(p => p >= lo && p <= hi)
/** Hour steps for a time axis with at most `max` labels. */
export const hourStep = (hours: number, max = 9) => [1, 2, 3, 6, 12, 24, 48].find(s => hours / s <= max) ?? 72

/** Index of the entry of a sorted array closest to x. */
export function nearestIndex(xs: (number | null)[], x: number): number {
  let lo = 0, hi = xs.length - 1
  while (lo < hi) { const mid = (lo + hi) >> 1, v = xs[mid]; if (v == null || v < x) lo = mid + 1; else hi = mid }
  const a = lo, b = Math.max(lo - 1, 0), va = xs[a], vb = xs[b]
  return va != null && vb != null && Math.abs(vb - x) < Math.abs(va - x) ? b : a
}

export const fmtPace = (m: number | null | undefined) => { if (m == null) return '–'; const t = Math.round(m * 60); return `${Math.floor(t / 60)}:${String(t % 60).padStart(2, '0')}` }
export const fmtElapsed = (s: number) => { const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60); return h ? `${h} h ${String(m).padStart(2, '0')} min` : `${m} min` }
/** A clock time in the race's time zone: "Thu 18:00". */
export const fmtLocal = (utcMs: number, tz: string) => new Date(utcMs).toLocaleString('en-GB', { timeZone: tz, weekday: 'short', hour: '2-digit', minute: '2-digit', hour12: false })
/** Line points with gaps: values of null split the line into runs [[x, y], ...]. */
export function runs(xs: number[], ys: (number | null)[]): [number, number][][] {
  const out: [number, number][][] = []; let cur: [number, number][] = []
  ys.forEach((y, i) => { if (y == null) { if (cur.length) out.push(cur); cur = [] } else cur.push([xs[i], y]) })
  if (cur.length) out.push(cur); return out
}
