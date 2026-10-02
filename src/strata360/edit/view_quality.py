"""Scoring a view (implementation plan K2): how good a camera pointed at (yaw, pitch) with a field of view looks, from the clip's quality grid (analysis/quality_grid.py), for choosing among views.

  view_score(grid, i, yaw, pitch, hfov, aspect) -> dict(score, detail, flat_share, expo)   one frame i of the grid
  window_score(grid, t0, t1, yaw, pitch, hfov, aspect, step)  -> the same, averaged over a window of the clip
  best_views(grid, i, ...) -> every candidate view of a frame, best first

A view is (yaw, pitch, hfov, aspect); yaw is the equirect longitude of the proxy (the centre column is 0, to the right positive). The view is sampled on a regular grid in its own image plane (so each sample is the same area on the screen) and each
sample is looked up in the 12 x 24 grid. Score = detail x (1 - penalty(the largest continuous flat patch's share of the view)) x exposure. It is a GUARDRAIL: a view that is mostly featureless (sky, fog, a smear on the lens), hazy, black or blown out scores low; a
sharp, varied view scores high; and a wide open landscape is not punished for being open (that is what `flat` measures, as a patch, not as a share of the whole sphere)."""
import numpy as np
from scipy.ndimage import label

GR, GC = 12, 24
FLAT = 3.0                      # mid-scale detail (grey levels) under which a cell is 'flat': sky, fog, smooth ground, a smear
PEN_FROM, PEN_TO = 0.10, 0.50   # the penalty starts at 10% of the view in one flat patch and is full at 50%


def view_dirs(yaw, pitch, hfov, aspect, n=24):
    """Unit vectors (x east, y ahead, z up) of a regular grid over the view's own image plane."""
    a, p = np.radians(yaw), np.radians(pitch); f = np.array([np.sin(a) * np.cos(p), np.cos(a) * np.cos(p), np.sin(p)]); r = np.array([np.cos(a), -np.sin(a), 0.0]); u = np.cross(r, f)
    tx = np.tan(np.radians(hfov) / 2); ty = tx / aspect; ny = max(int(n / aspect), 4); gx = ((np.arange(n) + .5) / n * 2 - 1) * tx; gy = ((np.arange(ny) + .5) / ny * 2 - 1) * ty
    X, Y = np.meshgrid(gx, -gy); d = f + X[..., None] * r + Y[..., None] * u; return (d / np.linalg.norm(d, axis=-1, keepdims=True)).reshape(-1, 3)


def cell_of(d, shift=0):
    """(row, column) of the grid cell each direction falls in; `shift` rolls the columns (to put a view that crosses the wrap-around column in the middle)."""
    lon = np.degrees(np.arctan2(d[:, 0], d[:, 1])); lat = np.degrees(np.arcsin(np.clip(d[:, 2], -1, 1)))
    c = np.clip(((lon + 180) / 360 * GC).astype(int), 0, GC - 1); r = np.clip(((90 - lat) / 180 * GR).astype(int), 0, GR - 1); return r, (c + shift) % GC


def penalty(share): return float(np.clip((share - PEN_FROM) / (PEN_TO - PEN_FROM), 0, 1))


def view_score(g, i, yaw, pitch, hfov=100.0, aspect=1.0):
    """Score the view in frame `i` of grid `g`. `detail` is the mean log detail of what the view covers (0 to about 1), `flat_share` the share of the view in its largest flat patch, `expo` how little of it is blown out or black."""
    i = int(np.clip(i, 0, len(g['tex']) - 1)); d = view_dirs(yaw, pitch, hfov, aspect); r, c = cell_of(d); roll = 0
    if np.ptp(c) >= 12: r, c = cell_of(d, shift=GC // 2); roll = GC // 2                                      # the view spans the wrap-around column: roll the grid so the view is in the middle
    tex, hi, lo = (np.roll(np.asarray(g[k][i], np.float32), roll, axis=1) for k in ('tex', 'clip_hi', 'clip_lo'))
    cnt = np.zeros((GR, GC)); np.add.at(cnt, (r, c), 1); flat = (cnt > 0) & (tex < FLAT); lab, k = label(flat, structure=np.ones((3, 3)))
    big = max([cnt[lab == j].sum() for j in range(1, k + 1)] or [0.0]); share = big / cnt.sum(); detail = float(np.mean(np.log1p(tex[r, c])) / 2.5); expo = float(1 - min(1.0, 4 * np.mean(hi[r, c] + lo[r, c])))
    return dict(score=detail * (1 - penalty(share)) * expo, detail=detail, flat_share=float(share), expo=expo)


def window_score(g, t0, t1, yaw, pitch, hfov=100.0, aspect=1.0, step=1.0):
    """The mean of `view_score` over [t0, t1] seconds of the clip, every `step` seconds (at least one sample)."""
    hz = float(g['hz']); ts = np.arange(t0, max(t1, t0 + 1e-6), step) if t1 > t0 else [t0]; rows = [view_score(g, round(t * hz), yaw, pitch, hfov, aspect) for t in ts]
    return {k: float(np.mean([r[k] for r in rows])) for k in rows[0]}


def best_views(g, i, pitches=(-15, 0, 15), hfovs=(70, 90, 110), aspect=16 / 9, step=15):
    """Every (yaw, pitch, hfov) candidate view of frame `i`, scored, best first (yaw from -180 to 180 by `step` degrees)."""
    out = []
    for yaw in range(-180, 180, step):
        for p in pitches:
            for h in hfovs: s = view_score(g, i, yaw, p, h, aspect); s.update(yaw=yaw, pitch=p, hfov=h); out.append(s)
    return sorted(out, key=lambda s: -s['score'])
