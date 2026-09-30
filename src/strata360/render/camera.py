"""Virtual camera paths: heading-follow stabilisation and keyframed moves.

A path gives, for every output frame, a view direction (yaw, pitch), a roll offset and a horizontal field of view.
Directions are relative to one of three references (`ref`):

  world    fixed in the upright, stabilised world frame (E: X right, Y forward, Z up; yaw 0 = the DJI upright datum)
  heading  world frame, but yaw is added to the runner's SMOOTHED HEADING, so the view follows where the camera/runner is
           going, turns gently through bends and ignores arm swing and wrist twist ("heading-follow")
  body     fixed in the camera body frame (X right, Y = front lens, Z up in the body); horizon still levelled by gravity

Conventions: yaw positive to the right (lon = atan2(x, y)); pitch positive up; roll positive clockwise seen from the camera;
angles in radians internally, degrees in files. Keyframe files (JSON):

  {"ref": "heading", "smooth_s": 0.0,
   "heading": {"axis_body": [0, 1, 0], "tau_s": 2.0, "min_horizontal": 0.25},
   "keyframes": [{"t": 0.0, "yaw": 0, "pitch": 0, "roll": 0, "fov": 90},
                 {"t": 3.0, "yaw": 40, "pitch": -5, "fov": 70, "ease": "smooth"}]}

t is clip-relative seconds. Between keyframes: "spline" (default, monotone cubic, continuous velocity, no overshoot),
"smooth" (smoothstep: ease in and out at every key) or "linear". Yaw between keyframes always takes the SHORT way round.
"""
import json
import numpy as np
from scipy.interpolate import PchipInterpolator
from scipy.ndimage import gaussian_filter1d


def wrap(a):
    return (np.asarray(a) + np.pi) % (2 * np.pi) - np.pi


def direction(yaw, pitch):
    """Unit vector in an X-right, Y-forward, Z-up frame."""
    return np.array([np.sin(yaw) * np.cos(pitch), np.cos(yaw) * np.cos(pitch), np.sin(pitch)])


def _smooth_edges(x, sigma):
    """Zero-phase Gaussian smoothing with trend-preserving ends: each end is extended by a straight-line fit of the last
    ~3 sigma samples (instead of repeating the last sample, which would copy the arm-swing phase into the result)."""
    n = len(x); pad = int(3 * sigma) + 1; w = max(int(3.0 * sigma), 3)
    if n < 4: return x.copy()
    w = min(w, n)
    def extend(seg, forward):
        t = np.arange(len(seg)); a, b = np.polyfit(t, seg, 1)
        ext = np.arange(len(seg), len(seg) + pad) if forward else np.arange(-pad, 0)
        return a * ext + b
    right = extend(x[-w:], True); left = extend(x[:w], False)
    ext = np.concatenate([left, x, right])
    return gaussian_filter1d(ext, sigma=max(sigma, 1e-6), mode='nearest')[pad:pad + n]


def heading_series(Ms, axis_body=(0.0, 1.0, 0.0), tau_s=2.0, fps=50.0, min_horizontal=0.25):
    """Smoothed heading (yaw, radians, unwrapped) of a body axis in the upright frame, one value per frame.

    Ms: sequence of 3x3 matrices, d_body = M d_E (see render4k.Renderer.stab_matrix).
    The raw yaw is the horizontal direction of the chosen body axis. Where the axis is nearly vertical (horizontal component
    below `min_horizontal`) the raw heading is undefined; those frames are filled from their neighbours (never spun).
    Smoothing is a zero-phase Gaussian of standard deviation tau_s seconds on the unwrapped angle (offline, so no lag)."""
    axis = np.asarray(axis_body, float); axis = axis / np.linalg.norm(axis)
    raw = np.full(len(Ms), np.nan)
    for i, M in enumerate(Ms):
        d = np.asarray(M).T @ axis                         # the axis expressed in the upright world frame
        if np.hypot(d[0], d[1]) >= min_horizontal:
            raw[i] = np.arctan2(d[0], d[1])
    good = ~np.isnan(raw)
    if not good.any():
        return np.zeros(len(Ms))
    idx = np.arange(len(Ms))
    un = np.unwrap(raw[good])                              # unwrap only over the valid samples, then interpolate across gaps
    filled = np.interp(idx, idx[good], un)
    return _smooth_edges(filled, tau_s * fps) if tau_s > 0 else filled


class CameraPath:
    def __init__(self, keyframes, ref='world', heading=None, smooth_s=0.0):
        assert ref in ('world', 'heading', 'body')
        self.ref, self.smooth_s = ref, smooth_s
        self.heading = dict(axis_body=[0, 1, 0], tau_s=2.0, min_horizontal=0.25); self.heading.update(heading or {})
        kf = sorted(keyframes, key=lambda k: k['t'])
        self.t = np.array([k['t'] for k in kf], float)
        self.yaw = np.unwrap(np.radians([k.get('yaw', 0.0) for k in kf]))       # unwrapped => shortest way between keys
        self.pitch = np.radians([k.get('pitch', 0.0) for k in kf])
        self.roll = np.radians([k.get('roll', 0.0) for k in kf])
        self.fov = np.array([k.get('fov', 90.0) for k in kf], float)
        self.dist = np.array([k.get('dist', 0.0) for k in kf], float)
        self.use_disc = any('disc' in k for k in kf)                              # globe: the whole sphere in a disc of radius `disc` (frame half-widths); on every key if on any
        self.disc = np.array([k.get('disc', 4.0) for k in kf], float)
        self.bg_opts = {}
        self.bg = 'blur'                                                            # globe background: [r, g, b] (0..1) or 'blur'; set from the path file         # projection: 0 rectilinear .. 1 stereographic (little planet / tunnel)
        self.ease = [k.get('ease', 'spline') for k in kf]

    @classmethod
    def from_json(cls, path):
        return cls.from_dict(json.load(open(path)))

    @classmethod
    def from_dict(cls, d):
        p = cls(d['keyframes'], d.get('ref', 'world'), d.get('heading'), d.get('smooth_s', 0.0)); p.bg = d.get('bg', 'blur'); p.bg_opts = {k[3:]: d[k] for k in ('bg_band', 'bg_spread', 'bg_smooth', 'bg_pick', 'bg_inset') if k in d}; return p

    @classmethod
    def static(cls, ref, yaw=0.0, pitch=0.0, roll=0.0, fov=90.0, heading=None, dist=0.0):
        return cls([dict(t=0.0, yaw=yaw, pitch=pitch, roll=roll, fov=fov, dist=dist)], ref, heading)

    def _interp(self, series, times, eases):
        if len(self.t) == 1:
            return np.full(len(times), series[0])
        out = np.empty(len(times)); tt = np.clip(times, self.t[0], self.t[-1])
        spline = PchipInterpolator(self.t, series)(tt)
        seg = np.clip(np.searchsorted(self.t, tt, side='right') - 1, 0, len(self.t) - 2)
        u = (tt - self.t[seg]) / np.maximum(self.t[seg + 1] - self.t[seg], 1e-9)
        for i in range(len(times)):
            e = eases[seg[i]]
            if e == 'linear': out[i] = series[seg[i]] + (series[seg[i] + 1] - series[seg[i]]) * u[i]
            elif e == 'smooth':
                s = u[i] * u[i] * (3 - 2 * u[i]); out[i] = series[seg[i]] + (series[seg[i] + 1] - series[seg[i]]) * s
            else: out[i] = spline[i]
        return out

    def evaluate(self, times, Ms=None, fps=50.0):
        """Dense per-frame path. Returns dict of arrays: yaw, pitch, roll (radians), fov (degrees) and `ref`.
        For ref='heading' the smoothed heading is added to yaw (needs Ms, one stabilisation matrix per frame)."""
        times = np.asarray(times, float)
        yaw = self._interp(self.yaw, times, self.ease); pitch = self._interp(self.pitch, times, self.ease)
        roll = self._interp(self.roll, times, self.ease); fov = self._interp(self.fov, times, self.ease)
        dist = np.clip(self._interp(self.dist, times, self.ease), 0.0, 1.0)
        disc = np.maximum(self._interp(self.disc, times, self.ease), 0.05) if self.use_disc else np.zeros(len(times))
        pitch = np.clip(pitch, -np.pi / 2 + 0.002, np.pi / 2 - 0.002)          # straight down/up is allowed (little planet); just short of the pole keeps the image 'up' defined
        if self.ref == 'heading':
            assert Ms is not None and len(Ms) == len(times)
            h = self.heading
            yaw = yaw + heading_series(Ms, h['axis_body'], h['tau_s'], fps, h['min_horizontal'])
        if self.smooth_s > 0:                       # optional extra zero-phase smoothing of the whole path (limits jerk)
            s = self.smooth_s * fps
            yaw, pitch, roll, fov, dist, disc = (gaussian_filter1d(a, s, mode='nearest') for a in (yaw, pitch, roll, fov, dist, disc))
        return dict(yaw=yaw, pitch=pitch, roll=roll, fov=fov, dist=dist, disc=disc, use_disc=self.use_disc, ref=self.ref)


def limits_report(path, fps=50.0):
    """Peak angular speed and acceleration of the view direction (deg/s, deg/s^2) and of the field of view (deg/s)."""
    yaw = np.unwrap(path['yaw']); pitch = path['pitch']
    dy, dp = np.gradient(yaw) * fps, np.gradient(pitch) * fps
    ang = np.degrees(np.hypot(dy * np.cos(pitch), dp))           # great-circle speed
    acc = np.degrees(np.hypot(np.gradient(dy) * fps * np.cos(pitch), np.gradient(dp) * fps))
    return dict(max_speed_deg_s=float(ang.max()), max_accel_deg_s2=float(acc.max()), max_fov_rate_deg_s=float(np.abs(np.gradient(path['fov']) * fps).max()),
                max_yaw_rate_deg_s=float(np.degrees(np.abs(dy)).max()), max_roll_rate_deg_s=float(np.degrees(np.abs(np.gradient(np.unwrap(path['roll'])) * fps)).max()))   # spin at a pole moves no great-circle distance, so report the raw rates too


def path_warnings(report, vmax=90.0, amax=120.0, fov_rate_max=30.0):
    """Human-readable warnings when a path moves too fast or has abrupt velocity changes (e.g. mixed easing at a key)."""
    w = []
    if report['max_speed_deg_s'] > vmax: w.append(f"peak angular speed {report['max_speed_deg_s']:.0f} deg/s exceeds {vmax:.0f}")
    if report['max_accel_deg_s2'] > amax: w.append(f"peak angular acceleration {report['max_accel_deg_s2']:.0f} deg/s^2 exceeds {amax:.0f} (abrupt velocity change: mixed easing at a keyframe?)")
    if report['max_fov_rate_deg_s'] > fov_rate_max: w.append(f"field of view changes at {report['max_fov_rate_deg_s']:.0f} deg/s, above {fov_rate_max:.0f}")
    return w
