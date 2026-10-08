"""What the view-choosing code needs to know about one clip, loaded once (K3): the quality grid (analysis/quality_grid.py), where the people are (identity.json, the wearer included), and how good each direction is rated (the scenes stage, on the
project's own scale: edit/quality_scale.py), all in the frame of the proxy video (yaw 0 is its centre column; the heading is the runner's direction in that frame).

load(clip_dir, osv) -> dict(grid, heading, boxes, prior); any part the clip does not have yet is None or the neutral choice (nobody; every direction rated alike)."""
import json, os

import numpy as np

from strata360.analysis import quality_grid as QG, views
from strata360.edit import quality_scale as QS


def wrap(a): return (np.asarray(a, float) + 180.0) % 360.0 - 180.0


def boxes_fn(identity, heading, people=None):
    """t (clip seconds) -> [(yaw, pitch, height_deg)] of everyone seen within a second and a half of t, the wearer first (yaw in the proxy's frame, degrees in -180..180): the identity samples (the wearer and the others) and every detection of the people stage (`people`:
    a body, or just a face, which counts as a 40 degree person); [] when there is neither. A box has no width of its own: scenery.person_share gives it one from its height."""
    samples = (identity or {}).get('samples') or []; ts = np.array([r['t_s'] for r in samples], float); dets = [(float(d['t_s']), d) for d in (people or {}).get('people') or [] if d.get('t_s') is not None and d.get('yaw') is not None and d.get('pitch') is not None]; dt = np.array([a for a, _ in dets], float)
    def at(t):
        out = []
        for k in np.flatnonzero(np.abs(dt - t) <= 1.5) if len(dt) else []: d = dets[k][1]; out.append((float(wrap(heading(dets[k][0]) + d['yaw'])), float(d['pitch']), float(d.get('height_deg') or 40.0)))
        for k in np.flatnonzero(np.abs(ts - t) <= 1.5) if len(ts) else []:
            r = samples[k]; hd = heading(float(r['t_s']))
            for p in ([r['me']] if r.get('me') else []) + list(r.get('others') or []): out.append((float(wrap(hd + p['yaw'])), float(p['pitch']), float(p.get('height_deg') or 0.0)))
        return out
    return at


def prior_fn(scenes, scale, heading):
    """(t, relative yaw) -> 0..1: how good the scenes stage thinks the direction is, relative yaw measured from straight ahead: the front views' calibrated scenery ahead, the rear views' behind, blended by the angle (cos squared of half of it for ahead);
    0.5 everywhere when there are no ratings."""
    rows = {v: sorted((float(i['t_s']), float(QS.apply(scale, i['scenery'])) / 10.0) for i in (scenes or {}).get('items') or [] if i.get('view') == v and isinstance(i.get('scenery'), (int, float))) for v in ('front', 'rear')}
    def side(v, t): return float(np.interp(t, [a for a, _ in rows[v]], [b for _, b in rows[v]])) if rows[v] else None
    def at(t, rel):
        f, r = side('front', t), side('rear', t)
        if f is None and r is None: return 0.5
        f = 0.5 if f is None else f; r = f if r is None else r; c = float(np.cos(np.radians(rel) / 2.0) ** 2); return f * c + r * (1 - c)
    return at


def load(clip_dir, osv=None):
    grid = QG.load(clip_dir)
    try: heading = views.heading_fn(clip_dir, osv)
    except Exception: heading = lambda t: 0.0                                                                  # no motion record and no telemetry: straight ahead is yaw 0
    def j(n):
        try: return json.load(open(os.path.join(clip_dir, n)))
        except (OSError, ValueError): return None
    scale = QS.project_scale(os.path.dirname(os.path.abspath(clip_dir)))
    idn = j('identity.json')
    return dict(grid=grid, heading=heading, identity=(idn or {}).get('samples') or [], boxes=boxes_fn(idn, heading, j('people.json')), prior=prior_fn(j('scenes.json'), scale, heading))
