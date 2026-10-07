"""The camera list of a clip (implementation plan K, the design's "virtual cameras in order of quality"): for one clip, every camera the cutter could use, best first.

  build(v, seed, ...) -> [camera]     v is `clip_views.load(clip_dir, osv)`: the quality grid, the heading, the people boxes and the direction prior

A camera has a start and an end (clip seconds; it need not cover the clip), a `score` (0..1, the mean look of its view from the quality grid, scaled by how much of the clip it covers: a guardrail and a ranking among the clip's own cameras, never a measure of beauty) and a `kind`:
  * trackings, the whole clip by default and shortened where the picture is bad at either end (under `TRIM` of the clip's median look): `heading` (where the runner goes, fov 100), `you` (the wearer, wherever the identity samples find them, fov 85), `person` (another
    person, fov 70) and `scenery` (edit/scenery.py: avoids every person, holds, pans slowly, cuts within its budget). A `you` or `person` camera is one per stretch where the subject is seen (gaps of up to `GAP_S` bridged); a stretch under `MIN_S` is dropped.
  * `free` cameras, a fixed pose or a slow pan between two poses (framing.free_path), about one per `FREE_EVERY_S` of clip and at most `MAX_FREE`, each in its own stretch of the clip; the poses are drawn from the best few at random (seeded: the same seed gives the same
    cameras, another seed other poses).
Each camera carries what the renderer needs: `aim` is a `track` ('heading' | 'you' | 'person' | 'scenery' with `yaw` keyframes for the last) or the `free` keyframes (`ref: world`, as framing.free_path)."""
import math

import numpy as np

from strata360.edit import framing as FR, scenery as SC, view_quality as VQ

TRIM = 0.4            # a second at either end whose look is under this share of the clip's median look is cut off
MIN_S = 3.0           # the shortest camera
GAP_S = 3.0           # a subject missing for no more than this does not end a tracking
FREE_EVERY_S = 15.0
MAX_FREE = 12
FOV = dict(heading=100.0, you=85.0, person=70.0, scenery=100.0)
ASPECT = 16 / 9


def _ranges(mask, gap):
    """[(a, b)] seconds (b exclusive) of the runs of True in `mask`, joining runs separated by up to `gap` seconds."""
    idx = np.flatnonzero(mask)
    if not len(idx): return []
    cuts = np.flatnonzero(np.diff(idx) > gap + 1) + 1
    return [(int(g[0]), int(g[-1]) + 1) for g in np.split(idx, cuts)]


def _looks(g, yaws, pitches, fov, n):
    """The view's look (0..1) for each second 0..n-1: yaws and pitches are functions of the second."""
    hz = float(g['hz']); return np.array([VQ.view_score(g, int(round((t + 0.5) * hz)), yaws(t + 0.5), pitches(t + 0.5), fov, ASPECT)['score'] for t in range(n)])


def _trim(look, a, b):
    """(a, b) shortened where the look is bad at either end; None when nothing of at least MIN_S is left."""
    med = float(np.median(look[a:b])) if b > a else 0.0
    if med > 1e-6:
        while b - a > MIN_S and look[a] < TRIM * med: a += 1
        while b - a > MIN_S and look[b - 1] < TRIM * med: b -= 1
    return (a, b) if b - a >= MIN_S else None


def _camera(cid, kind, a, b, look, dur, aim, why):
    seg = look[int(a):int(b)]; cover = (b - a) / max(dur, 1e-6)
    return dict(id=cid, kind=kind, start_s=float(a), end_s=float(b), score=round(float(seg.mean() * (0.5 + 0.5 * min(cover, 1.0))), 3), look=round(float(seg.mean()), 3), aim=aim, why=why)


def _subject_samples(identity_samples, heading):
    """{second: (yaw, pitch)} for the wearer and for the nearest other person, from identity samples (yaws are relative to the heading)."""
    me, other = {}, {}
    for r in identity_samples or []:
        t = float(r['t_s']); hd = heading(t); s = int(t)
        if r.get('me'): me[s] = (float(SC.wrap(hd + r['me']['yaw'])), float(r['me']['pitch']))
        o = sorted(r.get('others') or [], key=lambda p: -float(p.get('height_deg') or 0.0))
        if o: other[s] = (float(SC.wrap(hd + o[0]['yaw'])), float(o[0]['pitch']))
    return me, other


def build(v, seed=0, max_free=MAX_FREE):
    """The clip's cameras, best score first. `v` is clip_views.load's dict; without a quality grid there is nothing to score and the list is empty."""
    g = v.get('grid')
    if g is None: return []
    hz = float(g['hz']); dur = len(g['tex']) / hz; n = int(math.floor(dur))
    if n < MIN_S: return []
    heading, boxes, prior = v['heading'], v['boxes'], v['prior']; cams = []
    ys = lambda t: float(SC.wrap(heading(t))); zero = lambda t: 0.0                                                      # heading: straight ahead
    look = _looks(g, ys, zero, FOV['heading'], n); r = _trim(look, 0, n)
    if r: cams.append(_camera('H', 'heading', *r, look, dur, dict(track='heading', fov=FOV['heading']), 'follows where the runner goes'))
    me, other = _subject_samples(v.get('identity'), heading)
    for kind, found in (('you', me), ('person', other)):
        mask = np.array([s in found for s in range(n)])
        for k, (a, b) in enumerate(_ranges(mask, GAP_S)):
            def near(t, d=found, i=0):
                s = min(max(int(t), 0), n - 1); ks = sorted(d, key=lambda x: abs(x - s)); return d[ks[0]][i]
            look = _looks(g, lambda t, d=found: near(t, d, 0), lambda t, d=found: near(t, d, 1), FOV[kind], n); r = _trim(look, a, b)
            if r: cams.append(_camera(f"{'Y' if kind == 'you' else 'P'}{k + 1}", kind, *r, look, dur, dict(track=kind, fov=FOV[kind]), f"keeps {'the wearer' if kind == 'you' else 'another person'} in view while they are seen"))
    st = SC.Settings(); rng = np.random.default_rng([seed, 1]); path = SC.track(g, 0.0, float(n), heading, prior, boxes, st, rng)
    yaw_at = lambda t: float(np.interp(t, path['times'], np.unwrap(np.radians(path['yaw'])) * 180 / np.pi))
    look = _looks(g, yaw_at, lambda t: st.pitch, st.hfov, n); r = _trim(look, 0, n)
    if r: cams.append(_camera('S', 'scenery', *r, look, dur, dict(track='scenery', t0=0.0, fov=st.hfov, pitch=st.pitch, keyframes=SC.keyframes(path, path['times'][-1] - path['times'][0], st.pitch, st.hfov)), f"scenery with nobody in it ({len(path['jumps'])} cuts)"))
    k = int(min(max_free, max(1, math.ceil(dur / FREE_EVERY_S)))); edges = np.linspace(0.0, float(n), k + 1); rng = np.random.default_rng([seed, 2])
    for i in range(k):
        a, b = float(edges[i]), float(edges[i + 1]); T = b - a
        if T < MIN_S: continue
        free = FR.free_path(g, T, a, rng, dict(grid=g))
        if not free: continue
        k0 = free['keyframes'][0]; look = _looks(g, lambda t, k0=k0: k0['yaw'], lambda t, k0=k0: k0['pitch'], k0['fov'], n)
        cams.append(_camera(f'F{i + 1}', 'free', a, b, look, dur, dict(ref='world', t0=a, keyframes=free['keyframes']), free['why']))
    return sorted(cams, key=lambda c: -c['score'])
