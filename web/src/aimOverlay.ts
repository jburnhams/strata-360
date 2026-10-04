// What a point camera (src/strata360/edit/pointcam.py) is looking at, drawn over a video that is being played: a dot where it aims and the outline of its frame. The video is shown through a view (yaw, pitch, field of view) that the viewer may be
// moving (dragging, or an aim that follows a person), so the outline is worked out each frame by turning the camera's frame into directions and projecting them through the view the player has at that moment; the same maths as the players' own shaders.
import type { AimPath } from './api'

export interface View { yaw: number; pitch: number; fov: number; aspect: number }          // degrees; `fov` is the horizontal field of view; `aspect` is width over height
export interface Aim { yaw: number; pitch: number; fov: number }
type V3 = [number, number, number]
const RAD = Math.PI / 180
const CAMERA_ASPECT = 16 / 9                                                                // the film is 16:9

const dot = (a: V3, b: V3) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
const cross = (a: V3, b: V3): V3 => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]
/** The direction of a view in the world frame: X right, Y forward (yaw 0), Z up; yaw to the right. */
export const dir = (yaw: number, pitch: number): V3 => [Math.sin(yaw * RAD) * Math.cos(pitch * RAD), Math.cos(yaw * RAD) * Math.cos(pitch * RAD), Math.sin(pitch * RAD)]
const basis = (yaw: number, pitch: number) => { const f = dir(yaw, pitch), r: V3 = [Math.cos(yaw * RAD), -Math.sin(yaw * RAD), 0]; return { f, r, u: cross(r, f) } }

/** Where a direction falls in a view: x and y in -1..1 across the picture (x to the right, y up), or null when it is behind the viewer. */
export function project(view: View, d: V3): { x: number; y: number } | null {
  const { f, r, u } = basis(view.yaw, view.pitch), z = dot(d, f); if (z <= 1e-6) return null
  const tx = Math.tan((view.fov * RAD) / 2); return { x: dot(d, r) / z / tx, y: (dot(d, u) / z) * view.aspect / tx }
}

/** The directions along the edge of the camera's frame (`n` on each side, then round to the start), for projecting. */
export function frameDirections(aim: Aim, n = 12, aspect = CAMERA_ASPECT): V3[] {
  const { f, r, u } = basis(aim.yaw, aim.pitch), tx = Math.tan((aim.fov * RAD) / 2), out: V3[] = []
  const at = (a: number, b: number): V3 => [f[0] + a * tx * r[0] + (b * tx / aspect) * u[0], f[1] + a * tx * r[1] + (b * tx / aspect) * u[1], f[2] + a * tx * r[2] + (b * tx / aspect) * u[2]]
  for (let i = 0; i <= n; i++) out.push(at(-1 + (2 * i) / n, 1))
  for (let i = 1; i <= n; i++) out.push(at(1, 1 - (2 * i) / n))
  for (let i = 1; i <= n; i++) out.push(at(1 - (2 * i) / n, -1))
  for (let i = 1; i <= n; i++) out.push(at(-1, -1 + (2 * i) / n))
  return out
}

/** The camera's aim at time `t` of the video: null when it is not looking at anything then (outside its stretch, or the path is empty). `hold` takes the sample at or before `t` (a video of one picture a frame shows each picture for its whole frame);
 *  otherwise the aim is interpolated between samples, the yaw the short way round. */
export function aimAt(path: AimPath | null | undefined, t: number, hold = path?.kind === 'rel' && !path.viewer): Aim | null {
  if (!path || !path.t.length) return null
  const ts = path.t, n = ts.length, step = n > 1 ? (ts[n - 1] - ts[0]) / (n - 1) : 1
  if (t < ts[0] - 1e-6 || t > ts[n - 1] + (hold ? step : 1e-6)) return null
  let lo = 0, hi = n - 1; while (hi - lo > 1) { const m = (lo + hi) >> 1; if (ts[m] <= t) lo = m; else hi = m }
  if (hold) { const k = t >= ts[hi] ? hi : lo; return path.on[k] ? { yaw: path.yaw[k], pitch: path.pitch[k], fov: path.fov[k] } : null }
  if (!path.on[lo] || !path.on[hi]) return null
  const w = ts[hi] > ts[lo] ? Math.min(Math.max((t - ts[lo]) / (ts[hi] - ts[lo]), 0), 1) : 0; let dy = path.yaw[hi] - path.yaw[lo]; dy = ((dy + 540) % 360) - 180
  return { yaw: path.yaw[lo] + dy * w, pitch: path.pitch[lo] + (path.pitch[hi] - path.pitch[lo]) * w, fov: path.fov[lo] + (path.fov[hi] - path.fov[lo]) * w }
}

/** Draws the aim over a w x h canvas: the outline of the camera's frame (the part in front of the viewer, in line segments) and a dot at the aim point (with a ring, and an arrow at the edge pointing to it when it is out of the picture). */
export function drawAim(ctx: CanvasRenderingContext2D, w: number, h: number, view: View, aim: Aim | null, colour = '#14b8a6') {
  ctx.clearRect(0, 0, w, h); if (!aim) return
  const px = (p: { x: number; y: number }) => [((p.x + 1) / 2) * w, ((1 - p.y) / 2) * h] as const
  ctx.lineWidth = Math.max(2, w / 400); ctx.lineJoin = 'round'
  const pts = frameDirections(aim).map(d => project(view, d)); let open = false
  const stroke = (halo: boolean) => {
    ctx.strokeStyle = halo ? 'rgba(0,0,0,.65)' : colour; ctx.lineWidth = Math.max(2, w / 400) + (halo ? 2 : 0); ctx.beginPath(); open = false
    for (const p of pts) { if (!p) { open = false; continue } const [x, y] = px(p); if (open) ctx.lineTo(x, y); else { ctx.moveTo(x, y); open = true } }
    ctx.stroke()
  }
  stroke(true); stroke(false)
  const c = project(view, dir(aim.yaw, aim.pitch)), r = Math.max(5, w / 120)
  if (c && Math.abs(c.x) <= 1 && Math.abs(c.y) <= 1) {
    const [x, y] = px(c); ctx.fillStyle = colour; ctx.strokeStyle = '#fff'; ctx.lineWidth = 2; ctx.beginPath(); ctx.arc(x, y, r, 0, 2 * Math.PI); ctx.fill(); ctx.stroke(); ctx.beginPath(); ctx.arc(x, y, r * 2, 0, 2 * Math.PI); ctx.strokeStyle = colour; ctx.stroke()
  } else {                                                                                       // the aim is off to one side: a marker on the edge, towards it
    const b = basis(view.yaw, view.pitch), d = dir(aim.yaw, aim.pitch), ax = dot(d, b.r), ay = dot(d, b.u) * view.aspect, m = Math.hypot(ax, ay) || 1, k = 0.9
    const x = ((ax / m) * k + 1) / 2 * w, y = (1 - (ay / m) * k) / 2 * h; ctx.fillStyle = colour; ctx.strokeStyle = '#fff'; ctx.lineWidth = 2; ctx.beginPath(); ctx.arc(x, y, r, 0, 2 * Math.PI); ctx.fill(); ctx.stroke()
  }
}
