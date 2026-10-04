"""When to look at a clip: the moments the picture stages (scene labels, objects) sample, chosen by how far the runner has moved and how much the scene has changed, not by a fixed interval.

A new moment is taken once the runner has moved DIST_M metres since the last one (GPS speed from the race track) or the scene differs from the last moment by CHANGE_X times its usual change over 4 s (the world-locked
luma and detail grids of quality_grid.npz), never later than MAXGAP_S, and never sooner than MINGAP_S. The moment is moved to the sharpest picture of the SHARP_BACK_S before it (the `blur` channel). A running clip so
gets about twice the moments of a fixed 5 s; a runner standing still gets few. Without a track the distance rule is off; without the quality grid the change and sharpness rules are off; with neither there is no
adaptive answer (None) and the caller keeps its fixed interval."""
import datetime
import json
import os

import numpy as np

HZ = 2.0                    # the rate of quality_grid.npz
DIST_M = 5.0
MINGAP_S = 1.0
MAXGAP_S = 10.0
CHANGE_X = 1.5
SHARP_BACK_S = 1.5
START_S = 1.0               # the first moment: the first second is often black or the camera being put on


def adaptive_times(dur_s, speed=None, grid=None, sharp=None, hz=HZ, dist_m=DIST_M, mingap_s=MINGAP_S, maxgap_s=MAXGAP_S, change_x=CHANGE_X, sharp_back_s=SHARP_BACK_S, start_s=START_S):
    """Clip times (seconds) to look at, or None when there is neither a speed nor a grid to decide with. `speed` (m/s), `grid` (n, d) features and `sharp` (n,) are on a common grid of `hz` samples a second."""
    if speed is None and grid is None: return None
    n = int(dur_s * hz)
    for a in (speed, grid, sharp):
        if a is not None: n = min(n, len(a))
    if n <= 1: return [round(min(start_s, max(dur_s - 0.5, 0.0)), 2)]
    dist = None if speed is None else np.cumsum(np.nan_to_num(np.asarray(speed, float)[:n]) / hz); g = None if grid is None else np.asarray(grid, float)[:n]
    sh = None if sharp is None else np.nan_to_num(np.asarray(sharp, float)[:n]); k = int(4 * hz)
    typ = float(np.median([np.abs(g[i + k] - g[i]).mean() for i in range(0, n - k, k)])) if g is not None and n > k else 0.0       # how much the scene usually changes in 4 s
    first = min(int(round(start_s * hz)), n - 1); sel = [first]; gap = lambda a, b: (b - a) / hz
    for i in range(first + 1, n):
        last = sel[-1]
        if gap(last, i) < mingap_s: continue
        moved = dist is not None and dist[i] - dist[last] >= dist_m
        changed = g is not None and typ > 0 and float(np.abs(g[i] - g[last]).mean()) >= change_x * typ
        if not (moved or changed or gap(last, i) >= maxgap_s): continue
        j = i
        if sh is not None:
            lo = max(last + int(round(mingap_s * hz)), i - int(round(sharp_back_s * hz)))
            if lo <= i: j = lo + int(np.argmax(sh[lo:i + 1]))
        sel.append(j if j > last else i)
    return [round(i / hz, 2) for i in sel]


def load_inputs(clip_dir, track_path=None):
    """(duration_s, speed, grid, sharp) of a clip from its folder and, when there is one, the race track; any part that cannot be read is None (the duration is None only when clip.json cannot be read)."""
    try:
        clip = json.load(open(os.path.join(clip_dir, 'clip.json'))); dur = clip['video']['source_frames'] / clip['video']['nominal_fps']
        t0 = datetime.datetime.fromisoformat(clip['time']['start_utc'].replace('Z', '+00:00')).timestamp()
    except (OSError, ValueError, KeyError, TypeError): return None, None, None, None
    grid = sharp = speed = None
    try:
        with np.load(os.path.join(clip_dir, 'quality_grid.npz')) as q:
            if abs(float(q['hz']) - HZ) < 1e-6:
                luma, fine = q['luma'].astype(np.float32), q['fine'].astype(np.float32); n = len(luma)
                grid = np.concatenate([luma.reshape(n, -1) / (float(luma.max()) or 1.0), fine.reshape(n, -1) / (float(fine.max()) or 1.0)], 1); sharp = np.nan_to_num(q['blur'].astype(np.float32).reshape(n, -1).mean(1))
    except (OSError, ValueError, KeyError): pass
    if track_path:
        try:
            from strata360.gps import track
            tr = track.load(track_path); ts = t0 + np.arange(int(dur * HZ)) / HZ; sp = np.interp(ts, tr['t'], np.nan_to_num(tr['speed'], nan=0.0))
            speed = np.where((ts >= np.nanmin(tr['t'])) & (ts <= np.nanmax(tr['t'])), sp, 0.0)                    # outside the track nothing is known: not moving
        except Exception: speed = None
    return dur, speed, grid, sharp


def times_for(clip_dir, track_path=None, **kw):
    """The adaptive moments of a clip from the files in its folder (see the module text), or None when there is nothing to decide with."""
    dur, speed, grid, sharp = load_inputs(clip_dir, track_path)
    return None if dur is None else adaptive_times(dur, speed, grid, sharp, **kw)
