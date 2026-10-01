"""Parallax warp: moving each lens a little toward the other so the picture they share lines up, from the optical flow between them. A port of the idea in OpenOSV's ParallaxWarp (Apache-2.0,
https://github.com/Kemerd/OpenOSV, include/osv/render/ParallaxWarp.h), written for our renderer.

Why. The two lenses sit about 3 cm apart. Anything nearer than a few metres, and any small error in the calibrated lens orientations (OpenOSV measured about 0.66 degrees of cross-meridian error on its
sample), shows up as a displacement between the two pictures across the overlap: texture on the ground, branches, text on a sign look doubled or soft where the lenses meet. The seam (render/seam.py) hides a
disagreement by choosing one lens; the warp REMOVES it where it can be removed, so the seam has less to hide.

How. (1) Both lenses are sampled into the overlap band (the same strip as the seam: polar-axis equirect, +-9 degrees of latitude). (2) Dense optical flow (DIS) from one to the other and back; a flow vector
is kept only where the two directions agree (forward-backward check) and both lenses see the place. (3) The per-pixel flow becomes a coarse grid (256 columns by 32 rows) of the MEDIAN flow of each cell,
the empty cells filled from their neighbours, clamped to 3 degrees, smoothed (harder across the meridian than along it: a back-to-back pair's parallax runs along meridians), and faded to zero toward the edge of
the band (a correction that stops at the edge would tear it). (4) The benefit gate, "do no harm": each cell keeps its correction only if warping both lenses by it measurably reduces their
disagreement (by 20% or more, smoothstep from 5%); where the lenses see DIFFERENT things (a hand a few centimetres from one lens) no warp reconciles them, and bending real geometry for no gain is worse than
leaving it. (5) The grid is half the disparity: the master lens is sampled at the direction displaced by it, the slave by the opposite. Frame to frame the grid is averaged with the previous one so the
correction does not shimmer."""
import cv2
import numpy as np
from strata360.render import photo as ph, seam as SM

GRID_COLS, GRID_ROWS = 256, 32                 # 8 band columns by 3 band rows per cell
MAX_CORRECTION_DEG = 3.0
NEAR_DEG = 1.0                                 # a cell whose disparity is bigger than this is a NEAR object (a hand at 30 cm has about 6 degrees; calibration error and far parallax are under 1): left to the seam
MIN_CONSISTENT_FRACTION = 0.25
FB_TOL_PX = 1.0                                # forward-backward flow disagreement allowed
REQUIRED_IMPROVEMENT = 0.2
MIN_RESIDUAL = 0.0015                          # below this (luma 0..1) there is nothing measurable to fix
CROSS_SMOOTH, ALONG_SMOOTH = 5.0, 2.0          # grid cells: the correction applied is the smooth, far-field part only
FADE_FROM_DEG = 6.0                            # the correction fades to zero between this latitude and the band edge
TEMPORAL = 0.5                                 # weight of the new grid against the previous frame's
MIN_COVERAGE = 0.5


def _smoothstep(x):
    x = np.clip(x, 0.0, 1.0); return x * x * (3.0 - 2.0 * x)


def _blur_wrap(a, sy, sx):
    """Gaussian blur of a (rows, cols) grid that wraps in longitude (the columns) and clamps in latitude."""
    k = int(np.ceil(3 * max(sx, 1e-3))); p = np.concatenate([a[:, -k:], a, a[:, :k]], 1); return cv2.GaussianBlur(p.astype(np.float32), (0, 0), sigmaX=sx, sigmaY=sy, borderType=cv2.BORDER_REPLICATE)[:, k:-k]


class Warp:
    """The correction grid: for each cell of the overlap band the displacement (radians) of the MASTER lens's sampling direction, dlon and dlat (+ = toward the master lens's pole); the slave takes the negation."""
    def __init__(self, dlon, dlat, info=None): self.dlon, self.dlat, self.info = np.asarray(dlon, np.float32), np.asarray(dlat, np.float32), info or {}

    def _sample(self, g, lat_deg, lon):
        rows, cols = g.shape; u = (lon + np.pi) / (2 * np.pi) * cols - 0.5; i0 = np.floor(u).astype(int); f = (u - i0).astype(np.float32); a = i0 % cols; b = (i0 + 1) % cols
        v = (SM.BAND_DEG - lat_deg) / (2 * SM.BAND_DEG) * rows - 0.5; inside = (v > -1.0) & (v < rows)            # between the cell centres of the first / last row and the band edge the grid is zero
        j0 = np.clip(np.floor(v).astype(int), 0, rows - 1); j1 = np.clip(j0 + 1, 0, rows - 1); g_ = np.clip(v - np.floor(v), 0, 1).astype(np.float32)
        top = g[j0, a] * (1 - f) + g[j0, b] * f; bot = g[j1, a] * (1 - f) + g[j1, b] * f
        return np.where(inside, top * (1 - g_) + bot * g_, 0.0)

    def apply(self, d, sign):
        """Body-frame unit directions (N, 3) as the master (sign +1) or the slave (sign -1) lens should sample them: displaced by the grid inside the band, unchanged outside it."""
        lat = np.arcsin(np.clip(d[:, 1], -1.0, 1.0)); lon = np.arctan2(d[:, 2], d[:, 0]); latd = np.degrees(lat); near = np.abs(latd) < SM.BAND_DEG
        if not near.any(): return d
        dl = np.zeros(len(d), np.float32); dt = np.zeros(len(d), np.float32)
        dl[near] = self._sample(self.dlon, latd[near], lon[near]); dt[near] = self._sample(self.dlat, latd[near], lon[near])
        la = lat + sign * dt; lo = lon + sign * dl
        return np.stack([np.cos(la) * np.cos(lo), np.sin(la), np.cos(la) * np.sin(lo)], -1)


def _flow(a8, b8):
    dis = cv2.DISOpticalFlow_create(cv2.DISOPTICAL_FLOW_PRESET_MEDIUM); return dis.calc(a8, b8, None)


def measure(A, B, covA, covB, prior=None):
    """The warp from two bands (luma 0..1 each, shape (BAND_ROWS, BAND_COLS)) and their coverage. Returns a Warp, or None when too little can be measured (open sky, flat ground)."""
    R, W = A.shape; a8 = (np.clip(A, 0, 1) * 255).astype(np.uint8); b8 = (np.clip(B, 0, 1) * 255).astype(np.uint8)
    # context on all sides: the flow needs texture around the overlap to lock onto, and the longitude wraps
    pad = 32; ap = np.concatenate([a8[:, -pad:], a8, a8[:, :pad]], 1); bp = np.concatenate([b8[:, -pad:], b8, b8[:, :pad]], 1)
    fab = _flow(ap, bp)[:, pad:-pad]; fba = _flow(bp, ap)[:, pad:-pad]
    yy, xx = np.mgrid[0:R, 0:W].astype(np.float32); bx = (xx + fab[..., 0]) % W; by = np.clip(yy + fab[..., 1], 0, R - 1)
    back = cv2.remap(fba, bx.astype(np.float32), by.astype(np.float32), cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    consistent = np.hypot(fab[..., 0] + back[..., 0], fab[..., 1] + back[..., 1]) <= FB_TOL_PX
    cov = (covA >= MIN_COVERAGE) & (covB >= MIN_COVERAGE); valid = consistent & cov
    if cov.sum() == 0 or valid.sum() / cov.sum() < MIN_CONSISTENT_FRACTION: return None
    # half of the disparity, as the master lens's displacement in band pixels: master sampled at p - F/2, slave at p + F/2
    hx = np.where(valid, -fab[..., 0] / 2, np.nan).astype(np.float32); hy = np.where(valid, -fab[..., 1] / 2, np.nan).astype(np.float32)
    cr, cw = R // GRID_ROWS, W // GRID_COLS
    def cells(h):
        c = h.reshape(GRID_ROWS, cr, GRID_COLS, cw).transpose(0, 2, 1, 3).reshape(GRID_ROWS, GRID_COLS, cr * cw)
        n = np.sum(~np.isnan(c), 2); m = np.full((GRID_ROWS, GRID_COLS), np.nan, np.float32)
        ok = n >= 6
        if ok.any(): m[ok] = np.nanmedian(c[ok], axis=1)
        return m
    gx, gy = cells(hx), cells(hy); known = ~np.isnan(gx)
    rowdeg = 2 * SM.BAND_DEG / R; full_deg = 2 * np.hypot(gx * (360.0 / W), gy * rowdeg); near = known & (full_deg > NEAR_DEG)           # near objects: their cells are unknown, filled from the far-field around them
    known = known & ~near; gx = np.where(known, gx, np.nan); gy = np.where(known, gy, np.nan)
    # fill the cells nothing was measured in from their neighbours (normalised blur), then smooth anisotropically
    def fill(g):
        v = np.where(known, g, 0.0).astype(np.float32); w = known.astype(np.float32); num = _blur_wrap(v, 2.5, 4.0); den = _blur_wrap(w, 2.5, 4.0)
        return np.where(known, g, np.where(den > 1e-3, num / np.maximum(den, 1e-3), 0.0)).astype(np.float32)
    gx, gy = fill(gx), fill(gy)
    lim_x = MAX_CORRECTION_DEG / (360.0 / W); lim_y = MAX_CORRECTION_DEG / rowdeg
    gx = np.clip(gx, -lim_x / 2, lim_x / 2); gy = np.clip(gy, -lim_y / 2, lim_y / 2)            # half corrections: the full disparity is capped at 3 degrees
    gx = _blur_wrap(gx, CROSS_SMOOTH, CROSS_SMOOTH); gy = _blur_wrap(gy, ALONG_SMOOTH, ALONG_SMOOTH)      # more smoothing across the meridian (longitude) than along it
    lat_c = SM.BAND_DEG - (np.arange(GRID_ROWS) + 0.5) * (2 * SM.BAND_DEG / GRID_ROWS); fade = _smoothstep((SM.BAND_DEG - np.abs(lat_c)) / (SM.BAND_DEG - FADE_FROM_DEG))[:, None].astype(np.float32)
    gx, gy = gx * fade, gy * fade
    # the benefit gate: does warping both lenses by this reduce their disagreement here?
    up = lambda g: cv2.resize(g, (W, R), interpolation=cv2.INTER_LINEAR)
    ux, uy = up(gx), up(gy); Af, Bf = A.astype(np.float32), B.astype(np.float32)
    mA = cv2.remap(Af, (xx + ux).astype(np.float32), (yy + uy).astype(np.float32), cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    mB = cv2.remap(Bf, (xx - ux).astype(np.float32), (yy - uy).astype(np.float32), cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    cm = cov.astype(np.float32); pool = lambda x: cv2.boxFilter(x * cm, -1, (cw * 3, cr * 3), borderType=cv2.BORDER_REPLICATE) / np.maximum(cv2.boxFilter(cm, -1, (cw * 3, cr * 3), borderType=cv2.BORDER_REPLICATE), 1e-3)
    before = pool(np.abs(Af - Bf)); after = pool(np.abs(mA - mB)); ratio = after / np.maximum(before, 1e-6)
    gate = _smoothstep((1 - REQUIRED_IMPROVEMENT / 4 - ratio) / (REQUIRED_IMPROVEMENT * 3 / 4)) * (before > MIN_RESIDUAL)                    # ratio <= 1 - improvement: full; >= 1 - improvement / 4: none
    g_cells = cv2.resize(gate.astype(np.float32), (GRID_COLS, GRID_ROWS), interpolation=cv2.INTER_AREA); g_cells = _blur_wrap(g_cells, 1.0, 1.5)
    gx, gy = gx * g_cells, gy * g_cells
    colrad, rowrad = 2 * np.pi / W, np.radians(rowdeg)
    dlon, dlat = gx * colrad, -gy * rowrad                                                          # band pixels to radians; rows run toward the slave, latitude toward the master
    info = dict(consistent=float(valid.sum() / cov.sum()), gated_off=float((g_cells < 0.05).mean()), mean_abs_deg=float(np.degrees(np.abs(dlon)).mean() * 2), max_abs_deg=float(max(np.degrees(np.abs(dlon)).max(), np.degrees(np.abs(dlat)).max()) * 2),
                residual_before=float(before[cov].mean()), residual_after=float(after[cov].mean()))
    new = Warp(dlon, dlat, info)
    if prior is not None and prior.dlon.shape == new.dlon.shape:                                    # steady between frames
        new = Warp(prior.dlon * (1 - TEMPORAL) + new.dlon * TEMPORAL, prior.dlat * (1 - TEMPORAL) + new.dlat * TEMPORAL, info)
    return new
