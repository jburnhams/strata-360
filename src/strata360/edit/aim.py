"""Where the camera looks when it follows a person: a steady, debounced follower (the same algorithm runs in the browser player, web/src/aim.ts).

The detections jitter (one sample a second, a box that changes with the pose), so the camera does not chase them. It HOLDS while the person stays inside a dead band around the view centre, and only moves
when the person has been outside it for a while (`HOLD_S`):
  a small drift   a slow pan (speed-limited, eased in and out) that brings the person back towards the centre and stops when close (hysteresis: the band to start is wider than the one to stop)
  a big move      (further than `JUMP_DEG` for `JUMP_AFTER_S`) one quick eased cut-like move, done once, instead of a long chase
Vertical: the view is aimed so that the head is near the top of the frame and as much of the body as fits is below it (`aim_pitch`), not at the centre of the body box.
Angles are degrees; yaw wraps."""
import math

BAND_YAW = 9.0; BAND_PITCH = 7.0          # half-widths of the dead band (degrees): the person can move this far from the centre before anything happens
SETTLE = 0.3                               # a pan ends when the person is within this fraction of the band
HOLD_S = 0.5                               # outside the band this long before a pan starts (a flicker does nothing)
PAN_DEG_S = 18.0                           # fastest pan
PAN_TAU = 0.35                             # velocity eases towards the wanted one with this time constant (no sudden start)
JUMP_DEG = 28.0; JUMP_AFTER_S = 0.3        # further than this, for this long: move once, fast
JUMP_S = 0.5                               # duration of the jump (smoothstep)
HEAD_MARGIN = 0.42                         # the head's top sits this fraction of the frame height above the frame centre (1.0 would put it at the very top edge... 0.5 is the edge)


def wrap(a): return (a + 180.0) % 360.0 - 180.0


def vfov_deg(hfov_deg, aspect=16 / 9): return math.degrees(2 * math.atan(math.tan(math.radians(hfov_deg) / 2) / aspect))


def aim_pitch(pitch, height, vfov):
    """Pitch (degrees) to aim at so the head is near the top of the frame. `pitch` is the centre of the person's box, `height` its height in degrees (None: 45), `vfov` the frame's vertical field of view.
    Never aims more than half a body above or below the centre of the box."""
    h = 45.0 if not height else float(height); top = pitch + h / 2
    return min(max(top - HEAD_MARGIN * vfov, pitch - h / 2), pitch + h / 2)


class Follower:
    """step(target_yaw, target_pitch, dt) -> (yaw, pitch): the camera's view, one step."""
    def __init__(self, yaw, pitch):
        self.y, self.p = float(yaw), float(pitch); self.vy = self.vp = 0.0; self.mode = 'hold'; self.out_t = 0.0; self.far_t = 0.0; self.j = None

    def step(self, ty, tp, dt):
        ey, ep = wrap(ty - self.y), tp - self.p; n = max(abs(ey) / BAND_YAW, abs(ep) / BAND_PITCH); dist = math.hypot(ey * math.cos(math.radians(self.p)), ep)
        if self.mode == 'jump':
            self.j[0] += dt; s = min(self.j[0] / JUMP_S, 1.0); s = s * s * (3 - 2 * s); y0, p0, dy, dp = self.j[1:]; self.y, self.p = y0 + dy * s, p0 + dp * s; self.vy = self.vp = 0.0
            if s >= 1.0: self.mode = 'hold'; self.out_t = self.far_t = 0.0
            return self.y % 360.0, self.p
        self.far_t = self.far_t + dt if dist > JUMP_DEG else 0.0
        if self.far_t >= JUMP_AFTER_S: self.mode = 'jump'; self.j = [0.0, self.y, self.p, ey, ep]; return self.step(ty, tp, 0.0)      # the target at the moment of the decision
        if self.mode == 'hold':
            self.out_t = self.out_t + dt if n > 1.0 else 0.0
            if self.out_t >= HOLD_S: self.mode = 'pan'
        if self.mode == 'pan':
            if n < SETTLE: self.mode = 'hold'; self.out_t = 0.0
            else:
                wy, wp = ey / 0.8, ep / 0.8; sp = math.hypot(wy, wp)
                if sp > PAN_DEG_S: wy, wp = wy * PAN_DEG_S / sp, wp * PAN_DEG_S / sp
                k = 1 - math.exp(-dt / PAN_TAU); self.vy += (wy - self.vy) * k; self.vp += (wp - self.vp) * k
        if self.mode == 'hold': k = math.exp(-dt / 0.3); self.vy *= k; self.vp *= k           # coasts to a stop
        self.y += self.vy * dt; self.p += self.vp * dt
        return self.y % 360.0, self.p


def follow(times, yaw, pitch, dt=0.1):
    """The camera's yaw and pitch (degrees) at `times` (ascending, seconds) for a target given at those times (yaw may be any unwrapped or wrapped degrees)."""
    f = Follower(yaw[0], pitch[0]); out_y, out_p = [f.y % 360.0], [f.p]
    for i in range(1, len(times)):
        y, p = f.step(yaw[i], pitch[i], times[i] - times[i - 1]); out_y.append(y); out_p.append(p)
    return out_y, out_p
