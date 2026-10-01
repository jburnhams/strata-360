// The steady, debounced follower of src/strata360/edit/aim.py (keep the two in step): the camera holds while the person stays near the centre of the view, pans slowly when they drift out of the
// dead band for a while, and moves once, quickly, when they go far. Angles in degrees; yaw wraps.
const BAND_YAW = 9, BAND_PITCH = 3.5, SETTLE = 0.3, HOLD_S = 0.5, PAN_DEG_S = 18, PAN_TAU = 0.35, JUMP_DEG = 28, JUMP_AFTER_S = 0.3, JUMP_S = 0.5, HEAD_MARGIN = 0.08
const rad = (d: number) => (d * Math.PI) / 180
export const wrapDeg = (a: number) => ((((a + 180) % 360) + 360) % 360) - 180
export const vfovDeg = (hfov: number, aspect = 16 / 9) => (2 * Math.atan(Math.tan(rad(hfov) / 2) / aspect) * 180) / Math.PI

/** Pitch (degrees) to aim at: the whole head is in frame (a hard requirement), then as much of the body as fits. `pitch` is the centre of the person's box, `height` its height in degrees, `headTop` the pitch of
 *  the top of the head (from the face, else the top of the box). The lowest aim that keeps the head in frame puts the top of the head just inside the top edge, with room for the camera to sit anywhere in its
 *  dead band; when the whole body fits with room to spare the box is centred instead. */
export function aimPitch(pitch: number, height: number | null | undefined, vfov: number, headTop?: number | null) {
  const h = height || 45, top = headTop ?? pitch + h / 2, lowest = top - (0.5 - HEAD_MARGIN) * vfov + BAND_PITCH
  return Math.max(lowest, pitch)
}

export class Follower {
  y: number; p: number; private vy = 0; private vp = 0; private mode: 'hold' | 'pan' | 'jump' = 'hold'; private outT = 0; private farT = 0; private j: number[] | null = null
  constructor(yaw: number, pitch: number) { this.y = yaw; this.p = pitch }
  step(ty: number, tp: number, dt: number): [number, number] {
    const ey = wrapDeg(ty - this.y), ep = tp - this.p, n = Math.max(Math.abs(ey) / BAND_YAW, Math.abs(ep) / BAND_PITCH), dist = Math.hypot(ey * Math.cos(rad(this.p)), ep)
    if (this.mode === 'jump' && this.j) {
      this.j[0] += dt; let s = Math.min(this.j[0] / JUMP_S, 1); s = s * s * (3 - 2 * s)
      this.y = this.j[1] + this.j[3] * s; this.p = this.j[2] + this.j[4] * s; this.vy = this.vp = 0
      if (s >= 1) { this.mode = 'hold'; this.outT = this.farT = 0 }
      return [this.y, this.p]
    }
    this.farT = dist > JUMP_DEG ? this.farT + dt : 0
    if (this.farT >= JUMP_AFTER_S) { this.mode = 'jump'; this.j = [0, this.y, this.p, ey, ep]; return this.step(ty, tp, 0) }
    if (this.mode === 'hold') { this.outT = n > 1 ? this.outT + dt : 0; if (this.outT >= HOLD_S) this.mode = 'pan' }
    if (this.mode === 'pan') {
      if (n < SETTLE) { this.mode = 'hold'; this.outT = 0 }
      else {
        let wy = ey / 0.8, wp = ep / 0.8; const sp = Math.hypot(wy, wp)
        if (sp > PAN_DEG_S) { wy *= PAN_DEG_S / sp; wp *= PAN_DEG_S / sp }
        const k = 1 - Math.exp(-dt / PAN_TAU); this.vy += (wy - this.vy) * k; this.vp += (wp - this.vp) * k
      }
    }
    if (this.mode === 'hold') { const k = Math.exp(-dt / 0.3); this.vy *= k; this.vp *= k }
    this.y += this.vy * dt; this.p += this.vp * dt
    return [this.y, this.p]
  }
}
