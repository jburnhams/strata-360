"""Where the camera looks when it follows a person: a steady, debounced follower (the same algorithm runs in the browser player, web/src/aim.ts).

The detections jitter (one sample a second, a box that changes with the pose), so the camera does not chase them. It HOLDS while the person stays inside a dead band around the view centre, and only moves
when the person has been outside it for a while (`HOLD_S`):
  a small drift   a slow pan (speed-limited, eased in and out) that brings the person back towards the centre and stops when close (hysteresis: the band to start is wider than the one to stop)
  a big move      (further than `JUMP_DEG` for `JUMP_AFTER_S`) one quick eased cut-like move, done once, instead of a long chase
Vertical: the view is aimed so that the head is near the top of the frame and as much of the body as fits is below it (`aim_pitch`), not at the centre of the body box.
Angles are degrees; yaw wraps."""
import math

BAND_YAW = 9.0; BAND_PITCH = 3.5          # half-widths of the dead band (degrees): the person can move this far from the centre before anything happens
SETTLE = 0.3                               # a pan ends when the person is within this fraction of the band
HOLD_S = 0.5                               # outside the band this long before a pan starts (a flicker does nothing)
PAN_DEG_S = 18.0                           # fastest pan
PAN_TAU = 0.35                             # velocity eases towards the wanted one with this time constant (no sudden start)
JUMP_DEG = 28.0; JUMP_AFTER_S = 0.3        # further than this, for this long: move once, fast
JUMP_S = 0.5                               # duration of the jump (smoothstep)
FACE_BELOW_TOP = 0.30                      # the face centre is this fraction of the person's height below the top of the detection
HEAD_MARGIN = 0.08                         # the top of the head stays at least this fraction of the frame height below the top edge: a hard requirement


def wrap(a): return (a + 180.0) % 360.0 - 180.0


def vfov_deg(hfov_deg, aspect=16 / 9): return math.degrees(2 * math.atan(math.tan(math.radians(hfov_deg) / 2) / aspect))


def aim_pitch(pitch, height, vfov, head_top=None):
    """Pitch (degrees) to aim at: the whole head is in frame (a hard requirement), then as much of the body as fits. `pitch` is the centre of the person's box, `height` its height in degrees (None: 45),
    `head_top` the pitch of the top of the head (from the face; else the top of the box), `vfov` the frame's vertical field of view.
    The lowest aim that keeps the head in frame puts the top of the head just inside the top edge, with room for the camera to sit anywhere in its dead band (BAND_PITCH) without losing it; that shows the most
    body below. When the whole body fits with room to spare, the box is centred instead."""
    h = 45.0 if not height else float(height); top = head_top if head_top is not None else pitch + h / 2
    lowest = top - (0.5 - HEAD_MARGIN) * vfov + BAND_PITCH
    return max(lowest, pitch)


def aim_face(pitch, height, head_top=None):
    """Pitch (degrees) that centres the FACE in the frame, for the close view of you: the top of the detection (`head_top`, else the top of the box) less 30 percent of the person's apparent height. The detected top sits well above the
    eyes (the hood, the hair and the box margin), found by looking at real frames: 7 percent put the hood at the centre and the eyes on the bottom edge."""
    h = 45.0 if not height else float(height); top = head_top if head_top is not None else pitch + h / 2
    return top - FACE_BELOW_TOP * h


class Follower:
    """step(target_yaw, target_pitch, dt) -> (yaw, pitch): the camera's view, one step."""
    def __init__(self, yaw, pitch, scale=1.0):
        self.by, self.bp = BAND_YAW * scale, BAND_PITCH * scale                                  # the dead band, narrower for a narrower view (a close view must not let you drift out of frame)
        self.y, self.p = float(yaw), float(pitch); self.vy = self.vp = 0.0; self.mode = 'hold'; self.out_t = 0.0; self.far_t = 0.0; self.j = None

    def step(self, ty, tp, dt):
        ey, ep = wrap(ty - self.y), tp - self.p; n = max(abs(ey) / self.by, abs(ep) / self.bp); dist = math.hypot(ey * math.cos(math.radians(self.p)), ep)
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


def follow(times, yaw, pitch, dt=0.1, scale=1.0):
    """The camera's yaw and pitch (degrees) at `times` (ascending, seconds) for a target given at those times (yaw may be any unwrapped or wrapped degrees)."""
    f = Follower(yaw[0], pitch[0], scale); out_y, out_p = [f.y % 360.0], [f.p]
    for i in range(1, len(times)):
        y, p = f.step(yaw[i], pitch[i], times[i] - times[i - 1]); out_y.append(y); out_p.append(p)
    return out_y, out_p
