"""A seam CARVED through the overlap of the two lenses, and the narrow blend that follows it. A port of the idea in OpenOSV's SeamCarve (Apache-2.0, https://github.com/Kemerd/OpenOSV,
include/osv/render/SeamCarve.h), written for our renderer.

Why. The default blend fades each lens over the last few degrees of its field of view, so across the middle of the overlap both lenses sit at 50%. That is harmless where they agree and wrong where they do
not: something a few centimetres from the camera (a hand, the stick's grip, a pole) is seen from two viewpoints about 3 cm apart, each lens sees a different side of it, and averaging shows BOTH copies
(a ghost, a doubled finger) or cuts it. A seam does it the way production stitchers do: at any direction use ONE lens, put the boundary where the two lenses agree, and mix them only in a narrow
feather along it.

How. (1) Both lenses are sampled into the overlap band: a strip of the polar-axis equirect (the lens axes at the poles, the geometric seam on the equator), +-9 degrees of latitude, 2048 columns.
(2) A cost for putting the seam at each (row, column): the lenses' disagreement in a small window around it, a prohibitive cost where a lens cannot see (the stick, past its field of view) and a cost
for showing a lens where it only partly sees, a gentle pull to the geometric seam, and, from the previous frame's seam, a hold on how far it may move. (3) Dynamic programming along longitude (the
optimal seam of Avidan and Shamir), one seam row per column, a bounded step between columns, on a closed ring. (4) Per column a feather: wide where the lenses agree (it hides their colour
difference), narrow where they do not (two copies of a near object are never mixed). The result is a small table (seam latitude and feather half width per longitude column) that the renderer reads
per ray."""
import cv2
import numpy as np
from strata360.render import camera as cam, photo as ph

COLS = 1024                 # seam columns (0.35 degrees each)
BAND_COLS = 2048            # band columns (2 per seam column)
BAND_DEG = 9.0              # the band covers latitude +-9 degrees
BAND_ROWS = 96              # 0.1875 degrees a row
NARROW_DEG = 0.35           # feather half width where the lenses disagree
WIDE_DEG = 1.5              # ... and where they agree
COST_WINDOW_DEG = 0.35      # window the cost and the disagreement are measured over
AGREE, DISAGREE = 0.004, 0.012   # structural disagreement (gradient difference per band pixel) at or below / above which the feather is wide / narrow
DIFF_W, CENTRE_W, TEMPORAL_W, TEMPORAL_NORM_DEG, TEMPORAL_CLAMP_DEG = 1.0, 0.15, 0.5, 0.5, 2.0
COVERAGE_MIN, COVERAGE_W, COVERAGE_BLOCKED, FORBIDDEN = 0.5, 6.0, 0.02, 1.0e6
MAX_STEP, STEP_PENALTY, SMOOTH_COLS, WIDTH_SMOOTH_COLS = 2, 0.03, 1.5, 3.0
PERSON_W, PERSON_SIDE_W, PERSON_MARGIN_DEG = 8.0, 0.4, 1.5      # cost of a seam through a person (and 1.5 degrees round them: the feather), and the small cost of leaving a person on the lens that sees them more obliquely
PERSON_WIDTH = 0.3                                              # a person's width as a share of their height
EDGE_RAMP_DEG = 0.5         # validity ramp of a lens below its field-of-view limit where the seam decides the mix


def _smoothstep(x):
    x = np.clip(x, 0.0, 1.0); return x * x * (3.0 - 2.0 * x)


def _gauss_circular(x, sigma):
    """Gaussian smoothing of a periodic sequence."""
    if sigma <= 0: return x
    k = int(np.ceil(3 * sigma)); w = np.exp(-0.5 * (np.arange(-k, k + 1) / sigma) ** 2); w /= w.sum()
    return np.convolve(np.concatenate([x[-k:], x, x[:k]]), w, 'valid')


def solve_dp(cost, max_step=MAX_STEP, step_penalty=STEP_PENALTY):
    """One row per column through `cost` (rows x cols) minimising the cells' cost plus step_penalty * |move| between neighbouring columns, a move of at most `max_step` rows, on a CLOSED ring (the last
    column connects to the first): the path is solved over two laps and the second lap is kept, so the seam has no start and no end. Returns the row of each column (int array)."""
    R, C = cost.shape; big = np.float32(FORBIDDEN * 10); c2 = np.concatenate([cost, cost], 1).astype(np.float32); c2 = np.where(np.isfinite(c2), c2, big)
    acc = c2[:, 0].copy(); back = np.zeros((R, 2 * C), np.int8); shifts = list(range(-max_step, max_step + 1))
    for c in range(1, 2 * C):
        best = np.full(R, np.inf, np.float32); arg = np.zeros(R, np.int8)
        for d in shifts:                                                                  # arriving from row r + d of the previous column
            prev = np.full(R, np.inf, np.float32)
            if d >= 0: prev[:R - d] = acc[d:]
            else: prev[-d:] = acc[:R + d]
            v = prev + np.float32(step_penalty * abs(d)); m = v < best; best = np.where(m, v, best); arg = np.where(m, d, arg).astype(np.int8)
        acc = best + c2[:, c]; back[:, c] = arg
    r = int(np.argmin(acc)); path = np.zeros(2 * C, int); path[-1] = r
    for c in range(2 * C - 1, 0, -1): r = int(np.clip(r + back[r, c], 0, R - 1)); path[c - 1] = r
    return path[C:]


def person_cost(people, lat_rows, cols=COLS):
    """The extra cost, (len(lat_rows), cols), of putting the seam at each boundary row (latitude `lat_rows`, degrees) in each column for the people in the band. `people` is [(lat, lon, height)] in degrees: where each is in the seam layout (latitude from the seam circle toward the master lens, longitude
    around the lens axis) and how tall (their width follows). A seam through a person (or within the feather's reach of them) costs PERSON_W, so it goes round them where the +-9 degree band allows; and the side matters a little: a person nearer the master lens is better left to it (the seam on the slave
    side of them) and the other way round, as a lens sees them less obliquely near its axis. Never blended: a seam inside the feather would show both copies of a person seen from two viewpoints."""
    out = np.zeros((len(lat_rows), cols), np.float32); lon_of = (np.arange(cols) + 0.5) / cols * 360.0 - 180.0
    for lat, lon, h in people or []:
        hw = max(PERSON_WIDTH * h / 2.0, 2.0) + PERSON_MARGIN_DEG; lat_lim = BAND_DEG + hw
        if abs(lat) > lat_lim: continue
        near = np.abs((lon_of - lon + 180.0) % 360.0 - 180.0) <= max(h / 2.0, 5.0)
        if not near.any(): continue
        inside = np.abs(lat_rows - lat) <= hw; beyond = (lat_rows > lat + hw) if lat > 0 else (lat_rows < lat - hw)
        out[np.ix_(inside, near)] += PERSON_W; out[np.ix_(beyond, near)] += PERSON_SIDE_W
    return out


def people_in_layout(boxes, body_of):
    """[(lat, lon, height)] in degrees for world-frame boxes [(yaw, pitch, height_deg)] (render/final.py hands them over): `body_of` turns a world direction (x east, y ahead, z up) into the body frame; the layout is the polar-axis one (`Seam.master_share`)."""
    out = []
    for yaw, pitch, h in boxes:
        d = cam.direction(np.radians(yaw), np.radians(pitch)); b = np.asarray(body_of(d), float)
        out.append((float(np.degrees(np.arcsin(np.clip(b[1], -1, 1)))), float(np.degrees(np.arctan2(b[2], b[0]))), float(h or 40.0)))
    return out


class Seam:
    """The carved seam: latitude (radians, + = the master lens's side) and feather half width (radians) per longitude column of the polar-axis layout, plus what was measured."""
    def __init__(self, lat, hw, info=None): self.lat, self.hw, self.info = np.asarray(lat, np.float32), np.asarray(hw, np.float32), info or {}

    def master_share(self, d):
        """Share of the MASTER lens (0..1) for body-frame unit directions d (N, 3): 1 on its side of the seam, 0 on the other, a smooth ramp across the feather."""
        n = len(self.lat); lat = np.pi / 2 - np.arccos(np.clip(d[:, 1], -1.0, 1.0)); lon = np.arctan2(d[:, 2], d[:, 0])
        u = (lon + np.pi) / (2 * np.pi) * n - 0.5; i0 = np.floor(u).astype(int); f = (u - i0).astype(np.float32); a = i0 % n; b = (i0 + 1) % n
        s = self.lat[a] * (1 - f) + self.lat[b] * f; h = np.maximum(self.hw[a] * (1 - f) + self.hw[b] * f, 1e-5)
        return _smoothstep((lat - s) / (2 * h) + 0.5).astype(np.float32)


def glide(a, b, t):
    """From seam a to seam b by t in [0, 1] (the seam moves between measurements instead of jumping)."""
    return Seam(a.lat + (b.lat - a.lat) * t, a.hw + (b.hw - a.hw) * t, b.info)


class SeamCarver:
    """Carves the seam for one camera: needs the two lenses and their stick occlusion maps (render/flat.py builds them)."""
    def __init__(self, master, slave, occl_m, occl_s):
        self.master, self.slave, self.occl_m, self.occl_s = master, slave, occl_m, occl_s
        T = np.radians(90.0 - BAND_DEG + (np.arange(BAND_ROWS) + 0.5) * (2 * BAND_DEG / BAND_ROWS))      # angle from the master axis (+Y), growing with the row: row 0 = the master's side (latitude +9)
        P = (np.arange(BAND_COLS) + 0.5) / BAND_COLS * 2 * np.pi - np.pi; TT, PP = np.meshgrid(T, P, indexing='ij')
        self.dirs = np.stack([np.sin(TT) * np.cos(PP), np.cos(TT), np.sin(TT) * np.sin(PP)], -1).reshape(-1, 3)
        self.row_deg = 2 * BAND_DEG / BAND_ROWS; self.lat_rows = BAND_DEG - (np.arange(BAND_ROWS + 1)) * self.row_deg      # latitude (degrees) of the boundary above row s
        self._proj = [L.project(self.dirs) for L in (master, slave)]

    def band(self, img_m, img_s, warp=None):
        """Luma and coverage of both lenses in the band: ((A, covA), (B, covB)), each (rows, BAND_COLS). With a parallax `warp` each lens is sampled where the warp moves it (what the renderer will show)."""
        out = []; proj = self._proj if warp is None else [self.master.project(warp.apply(self.dirs, 1)), self.slave.project(warp.apply(self.dirs, -1))]
        for img, (u, v, th), om in ((img_m, proj[0], self.occl_m), (img_s, proj[1], self.occl_s)):
            u2 = u.astype(np.float32).reshape(BAND_ROWS, BAND_COLS); v2 = v.astype(np.float32).reshape(BAND_ROWS, BAND_COLS)
            rgb = cv2.remap(img, u2, v2, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0).astype(np.float32) / 65535.0
            y = rgb[..., 0] * 0.2126 + rgb[..., 1] * 0.7152 + rgb[..., 2] * 0.0722
            cov = ph.lens_weight(np.degrees(th).reshape(BAND_ROWS, BAND_COLS), ph.sample_occl(om, u2, v2), ph.THETA_MAX_DEG, ph.ANALYSIS_FEATHER_DEG)
            out.append((y, cov))
        return out

    def carve(self, img_m, img_s, prior=None, warp=None, people=None):
        """Carve the seam from two decoded lens frames (uint16 RGB code values, 3840 x 3840). `prior` (a Seam from the neighbouring frame) adds the hold and the clamp; `people` ([(lat, lon, height)], see `person_cost`) steers the seam round them (none: as before, which the proxies rely on)."""
        (A, cA), (B, cB) = self.band(img_m, img_s, warp); h = lambda x: x.reshape(BAND_ROWS, COLS, 2).mean(2)             # to seam columns
        a, b, ca, cb = h(A), h(B), h(cA), h(cB); R = BAND_ROWS; S = R + 1; w = max(int(round(COST_WINDOW_DEG / self.row_deg)), 1)
        D = np.abs(a - b); cs = np.concatenate([np.zeros((1, COLS), np.float32), np.cumsum(D, 0)]); s_idx = np.arange(S)
        lo = np.clip(s_idx - w, 0, R); hi = np.clip(s_idx + w, 0, R); diff = (cs[hi] - cs[lo]) / np.maximum(hi - lo, 1)[:, None]
        # a lens may not be shown where it cannot see: master on its side (rows above the seam), slave on its own
        shM = np.maximum(0.0, COVERAGE_MIN - ca); shS = np.maximum(0.0, COVERAGE_MIN - cb)
        cm = np.concatenate([np.zeros((1, COLS), np.float32), np.cumsum(shM, 0)]); csl = np.concatenate([np.zeros((1, COLS), np.float32), np.cumsum(shS, 0)])
        cov = COVERAGE_W * (cm + (csl[R] - csl))
        blind = np.minimum(ca, cb) < COVERAGE_BLOCKED; bs = np.concatenate([np.zeros((1, COLS), np.float32), np.cumsum(blind, 0)]); forb = (bs[hi] - bs[lo]) > 0
        cost = DIFF_W * diff + cov + CENTRE_W * (np.abs(s_idx - R / 2.0) / (R / 2.0))[:, None]; cost = np.where(forb, FORBIDDEN, cost).astype(np.float32)
        pcost = person_cost(people, self.lat_rows, COLS) if people else None
        if pcost is not None: cost = cost + pcost
        used = False
        if prior is not None and len(prior.lat) == COLS:
            p = (BAND_DEG - np.degrees(prior.lat)) / self.row_deg                                               # prior seam in boundary rows
            dev = np.abs(s_idx[:, None] - p[None, :]) * self.row_deg; cost += (TEMPORAL_W * np.minimum(dev / TEMPORAL_NORM_DEG, 1.0)).astype(np.float32); cost[dev > TEMPORAL_CLAMP_DEG] = FORBIDDEN; used = True
        path = solve_dp(cost); forced = int((cost[path, np.arange(COLS)] >= FORBIDDEN).sum())
        lat = _gauss_circular(BAND_DEG - path * self.row_deg, SMOOTH_COLS)                                      # degrees
        if used: lat = np.clip(lat, np.degrees(prior.lat) - TEMPORAL_CLAMP_DEG, np.degrees(prior.lat) + TEMPORAL_CLAMP_DEG)
        # feather: how much the lenses still disagree structurally along the seam (gradients: a colour offset is not a disagreement)
        gA = np.abs(np.diff(a, axis=0, prepend=a[:1])) + np.abs(np.diff(a, axis=1, prepend=a[:, -1:])); gB = np.abs(np.diff(b, axis=0, prepend=b[:1])) + np.abs(np.diff(b, axis=1, prepend=b[:, -1:]))
        G = np.abs(gA - gB) * 0.5; gcs = np.concatenate([np.zeros((1, COLS), np.float32), np.cumsum(G, 0)]); s_c = np.clip(np.round((BAND_DEG - lat) / self.row_deg).astype(int), 0, R)
        lo_c = np.clip(s_c - w, 0, R); hi_c = np.clip(s_c + w, 0, R); resid = (gcs[hi_c, np.arange(COLS)] - gcs[lo_c, np.arange(COLS)]) / np.maximum(hi_c - lo_c, 1)
        t = _smoothstep((resid - AGREE) / (DISAGREE - AGREE))
        if pcost is not None: t = np.maximum(t, (pcost[s_c, np.arange(COLS)] >= PERSON_W).astype(np.float32))                # a seam that has to cross a person (too big to go round) is a hard narrow one: never two viewpoints of a person mixed
        width = _gauss_circular(WIDE_DEG + (NARROW_DEG - WIDE_DEG) * t, WIDTH_SMOOTH_COLS)
        info = dict(mean_lat_deg=float(lat.mean()), max_abs_lat_deg=float(np.abs(lat).max()), mean_half_width_deg=float(width.mean()), narrow_columns=int((t > 0.5).sum()), forced_columns=forced, used_prior=used,
                    mean_residual=float(resid.mean()))
        return Seam(np.radians(lat), np.radians(width), info)

    def geometric(self):
        """The seam of no information: on the equator with the wide feather."""
        return Seam(np.zeros(COLS), np.full(COLS, np.radians(WIDE_DEG)))
