"""Camera clock correction: anchors, automatic suggestion, and fitting (README 6.1).

Camera clocks drift or are simply wrong when they have gone a long time without internet. An **anchor** ties a moment in a clip to a true UTC time. Because the
GPS file shares the wearer's motion, the natural anchors are sudden events both can see: *the running starts* (or stops). So:

  * `gps_events(track)` finds running starts/stops in the GPS/FIT (speed and cadence),
  * `camera_events(motion)` finds the same in a clip's accelerometer step rhythm (`motion.json` steps),
  * `suggest(...)` pairs them across the whole race and votes for the clock offset that most events agree on (no user input),
  * `add_anchor(...)` is what a GUI calls when the user picks a clip and a point on its timeline: the point snaps to the nearest camera event, and the matching GPS event
    is found near the current estimate (or the user gives a UTC / picks among candidates),
  * `fit(...)` turns anchors into an offset (one anchor or a short span) or an offset plus a steady drift (two or more anchors hours apart).

Sign convention: offset = camera clock minus true UTC (the camera is ahead when positive). true UTC = camera time - offset."""
import datetime as dt, glob, json, os
import numpy as np
from scipy.ndimage import gaussian_filter1d, uniform_filter1d


def _ts(s): return dt.datetime.fromisoformat(s.replace('Z', '+00:00')).timestamp()


def _iso(t): return dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'


def _edges(active, t, min_off, min_on):
    """Transitions of a boolean series: 'start' where it has been off for at least `min_off` s and then stays on for at least `min_on` s; 'stop' where it has been on for at
    least `min_on` s and then stays off for at least `min_off` s. Runs touching the ends of the series give no event on the open side. Returns [(time, kind)]."""
    dt_ = float(np.median(np.diff(t))); a = np.asarray(active, bool)
    edges = np.flatnonzero(np.diff(a.astype(int)) != 0) + 1; bounds = np.r_[0, edges, len(a)]; runs = [(bounds[k], bounds[k + 1], bool(a[bounds[k]])) for k in range(len(bounds) - 1)]
    ev = []
    for k, (i0, i1, on) in enumerate(runs):
        n = (i1 - i0) * dt_
        if on and k > 0 and n >= min_on and (runs[k - 1][1] - runs[k - 1][0]) * dt_ >= min_off: ev.append((float(t[i0]), 'start'))
        if not on and k > 0 and n >= min_off and (runs[k - 1][1] - runs[k - 1][0]) * dt_ >= min_on and k < len(runs) - 1 or (not on and k == len(runs) - 1 and k > 0 and n >= min_off and (runs[k - 1][1] - runs[k - 1][0]) * dt_ >= min_on):
            ev.append((float(t[i0]), 'stop'))
    return ev


def gps_events(tr, min_off=10.0, min_on=20.0):
    """Running starts/stops in the GPS track: moving = smoothed speed above 1.2 m/s (a walk or a run). [(utc_seconds, 'start'|'stop')]."""
    t = tr['t']; ok = np.isfinite(tr['speed']); sp = np.where(ok, tr['speed'], 0.0); g = np.arange(t[0], t[-1], 1.0); v = gaussian_filter1d(np.interp(g, t, sp), 2.0)
    pad = 60; g = np.r_[t[0] - np.arange(pad, 0, -1.0), g]; v = np.r_[np.zeros(pad), v]                # the watch was started standing still: the file's start is preceded by "not moving"
    return _edges(v > 1.2, g, min_off, min_on)


def camera_events(motion_doc, min_off=5.0, min_on=8.0):
    """Stepping starts/stops in a clip: step strength above 0.4 in the 1.2-3.5 Hz band. [(clip_seconds, 'start'|'stop')]."""
    s = motion_doc.get('steps')
    if not s: return []
    t = np.array(s['t']); on = (np.array(s['strength']) >= 0.4) & (np.array(s['hz']) >= 1.2)
    if len(t) < 3: return []
    from scipy.ndimage import binary_closing, binary_opening
    on = binary_opening(binary_closing(on, np.ones(5, bool)), np.ones(3, bool))                 # close gaps up to 4 s (a stumble, a hand-off), drop 2 s blips
    return _edges(on, t, min_off, min_on)


def clips_info(race_dir):
    out = []
    for d in sorted(glob.glob(os.path.join(race_dir, 'clips', '*', ''))):
        try: c = json.load(open(d + 'clip.json')); m = json.load(open(d + 'motion.json'))
        except OSError: continue
        cam0 = _ts(c['time'].get('container_creation_time') or c['time']['start_utc'])          # the camera's own clock at the clip start
        crowd = 0.0
        try:
            pp = json.load(open(d + 'people.json')); per = {}
            for p in pp['people']:
                if (p.get('conf') or 0) > 0.5 or p.get('face'): per[p['frame']] = per.get(p['frame'], 0) + 1
            crowd = float(np.median(list(per.values()))) if per else 0.0
        except (OSError, ValueError): pass
        out.append(dict(clip=c['clip_id'], cam0=cam0, duration=float(m['duration_s']), events=camera_events(m), crowd=crowd))
    return out


def race_start_seed(infos, tr, min_crowd=10.0):
    """The mass start is the best natural anchor: the clip with the biggest crowd (people stage) that also has a stepping start is the start area, and the watch was started
    at the gun, so the FIT's first running start is the same moment. Returns (offset_s, clip, camera_t) or None."""
    g = [t for t, k in gps_events(tr) if k == 'start']
    if not g: return None
    for c in sorted(infos, key=lambda c: c['cam0']):                                              # the earliest crowd clip in which the wearer sets off and keeps going
        if c.get('crowd', 0) < min_crowd: continue
        for tc, k in c['events']:
            nxt = [t for t, k2 in c['events'] if k2 == 'stop' and t > tc]
            if k == 'start' and (min(nxt) if nxt else c['duration']) - tc >= 30.0: return (c['cam0'] + tc - g[0], c['clip'], tc)
    return None


def suggest(race_dir, tr, window_s=1800.0, kernel_s=12.0, top=5, sigma_s=900.0, prior_s=0.0):
    """Vote for the offset (camera minus UTC). Every camera event is paired with every GPS event of the same kind within `window_s`; each pairing votes for its implied
    offset with a weight that falls off the further that offset is from `prior_s` (Gaussian, `sigma_s`: a camera clock is out by minutes, rarely by hours), so a near
    match beats an equally good far one. Returns [{offset_s, score, votes, clips, confidence}] best first; `confidence` = the winner's share of the total weight of the top
    candidates (a clear winner is near 1, a toss-up near 0.5)."""
    ge = gps_events(tr); votes = []; infos = clips_info(race_dir); seed = race_start_seed(infos, tr)
    for ci in infos:
        for tc, kind in ci['events']:
            for tg, gk in ge:
                if gk == kind and abs((ci['cam0'] + tc) - tg) <= window_s: votes.append((ci['cam0'] + tc - tg, ci['clip']))
    if seed and abs(seed[0] - prior_s) <= window_s: votes += [(seed[0], seed[1])] * 12                          # the mass start counts as much as a dozen chance matches
    if not votes: return []
    off = np.array([v[0] for v in votes]); w = np.exp(-0.5 * ((off - prior_s) / sigma_s) ** 2); grid = np.arange(prior_s - window_s, prior_s + window_s + 1, 2.0)
    kern = np.exp(-0.5 * ((grid[:, None] - off[None, :]) / kernel_s) ** 2); dens = kern @ w                          # each event pair spreads its vote over +/- kernel_s (event times jitter by seconds)
    res = []; d = dens.copy()
    for _ in range(top):
        k = int(np.argmax(d))
        if d[k] <= 0: break
        m = abs(off - grid[k]) <= 2 * kernel_s
        res.append(dict(offset_s=round(float(grid[k]), 1), score=round(float(dens[k]), 3), votes=int(m.sum()), clips=sorted({votes[i][1][-6:] for i in np.flatnonzero(m)})))
        d[abs(grid - grid[k]) <= 60.0] = 0                                                                            # suppress the neighbourhood, then take the next peak
    tot = sum(r['score'] for r in res) or 1.0
    for r in res: r['confidence'] = round(r['score'] / tot, 2)
    return res


def add_anchor(race_dir, tr, clip_id, t_s, utc=None, kind=None, snap_s=8.0, window_s=1800.0, current_offset_s=0.0):
    """A user picks (clip, t_s) [+ optionally the true UTC]. The clip time snaps to the nearest camera event within `snap_s` (a GUI click is rarely to the second).
    Without `utc`, the matching GPS event of the same kind nearest to (camera time - current offset) is used; the result says how many candidates were in the window,
    so a GUI can ask the user to choose when there is more than one. Returns the anchor dict (or raises ValueError)."""
    ci = next((c for c in clips_info(race_dir) if c['clip'] == clip_id or c['clip'].endswith(clip_id)), None)
    if ci is None: raise ValueError(f'no clip {clip_id}')
    ev = [e for e in ci['events'] if kind in (None, e[1]) and abs(e[0] - t_s) <= snap_s]; snapped = min(ev, key=lambda e: abs(e[0] - t_s)) if ev else None
    t_use = snapped[0] if snapped else float(t_s); k = snapped[1] if snapped else kind; cam = ci['cam0'] + t_use
    cands = []
    if utc is None:
        if k is None: raise ValueError('no camera event near that point and no UTC given: give --utc, or pick a point at a running start/stop')
        cands = sorted([g for g in gps_events(tr) if g[1] == k and abs(g[0] - (cam - current_offset_s)) <= window_s], key=lambda g: abs(g[0] - (cam - current_offset_s)))
        if not cands: raise ValueError('no matching GPS event in the search window: give --utc')
        utc_s = cands[0][0]
    else: utc_s = _ts(utc) if isinstance(utc, str) else float(utc)
    return dict(clip=ci['clip'], t_s=round(t_use, 2), snapped=snapped is not None, kind=k, utc=_iso(utc_s), camera_time=_iso(cam), offset_s=round(cam - utc_s, 2),
                candidates=[_iso(g[0]) for g in cands[:4]], ambiguous=len(cands) > 1 and abs(cands[1][0] - cands[0][0]) < 600)


def fit(anchors, min_span_s=6 * 3600):
    """Anchors -> clock model {offset_seconds, drift_s_per_day, drift_ref_camera_time, residuals}. One anchor (or a short span): constant offset.
    Two or more anchors at least `min_span_s` apart: least-squares offset + steady drift."""
    if not anchors: raise ValueError('no anchors')
    cam = np.array([_ts(a['camera_time']) for a in anchors]); off = np.array([a['offset_s'] for a in anchors], float)
    if len(anchors) == 1 or cam.max() - cam.min() < min_span_s:
        o = float(np.median(off)); return dict(offset_seconds=round(o, 1), drift_s_per_day=0.0, drift_ref_camera_time=None, residual_s=[round(float(x - o), 1) for x in off])
    ref = float(cam.mean()); A = np.c_[np.ones_like(cam), (cam - ref) / 86400.0]; (o, dr), *_ = np.linalg.lstsq(A, off, rcond=None)
    return dict(offset_seconds=round(float(o), 1), drift_s_per_day=round(float(dr), 2), drift_ref_camera_time=_iso(ref), residual_s=[round(float(x), 1) for x in off - A @ np.array([o, dr])])


def apply_to_config(cfg, anchors):
    """Write the fitted clock into cfg['camera_clock'] (the caller saves the config and re-runs ingest, which re-times every clip without recomputing anything else)."""
    m = fit(anchors); c = cfg.setdefault('camera_clock', {}); c['utc_offset_hours'] = 0.0; c['offset_seconds'] = m['offset_seconds']; c['verified'] = True
    c['anchors'] = anchors
    if m['drift_s_per_day']: c['drift_s_per_day'] = m['drift_s_per_day']; c['drift_ref_camera_time'] = m['drift_ref_camera_time']
    else: c.pop('drift_s_per_day', None); c.pop('drift_ref_camera_time', None)
    c['note'] = f"fitted from {len(anchors)} anchor(s); residuals {m['residual_s']} s" + (f"; drift {m['drift_s_per_day']} s/day" if m['drift_s_per_day'] else '')
    return m
