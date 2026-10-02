"""The scenery camera (implementation plan K3): a tracking view that AVOIDS EVERY PERSON and takes the best-looking scenery available, for b-roll when there is nothing to say and as a contrast with the shots of people.

  track(grid, t0, t1, heading, prior, boxes, settings, rng) -> dict(times, yaw, jumps, score)     the camera's yaw over [t0, t1]
  availability(grid, times, heading, prior, boxes, settings) -> per second, how good the best people-free view is (0..1)
  keyframes(path, T, pitch, fov) -> the camera path (world frame) the renderer takes

The view is a fixed field of view and pitch looking along some yaw. At each step (a second) every one of 24 yaw bins (15 degrees) has a score: the view's look from the quality grid (edit/view_quality.py: detail, a penalty for a big flat patch, exposure) weighted
by the direction prior (the scenes stage's scenery rating ahead and behind, on the project's own scale, blended by how far the direction is from straight ahead), minus a heavy cost for any person in the view (a box from the identity samples, the wearer included, a small
share of the view allowed). A dynamic programme over the bins then picks the path: it HOLDS when nothing is clearly better, PANS slowly (at most one bin a step: 15 degrees a second) towards a better direction, and JUMPS (a cut to a far bin) only
when that is worth its cost and the budget allows (default 2 a minute: a window of under half a minute has none, so it is all slow pans). A little seeded noise on the scores gives variety (same seed, same camera)."""
import math
from dataclasses import dataclass

import numpy as np

from strata360.edit import view_quality as VQ

BIN_DEG = 15.0


@dataclass
class Settings:
    step_s: float = 1.0
    pitch: float = 0.0
    hfov: float = 100.0
    aspect: float = 16 / 9
    pan_cost: float = 0.02               # per bin of a pan (a pan of one bin is the most a step allows)
    jump_cost: float = 0.30              # a cut to a far direction; it must gain more than this to be worth it
    budget_per_min: float = 2.0          # jumps a minute
    person_share: float = 0.02           # the share of the view a person may take before the cost starts
    person_cost: float = 4.0             # per unit of the share above that
    prior_floor: float = 0.4             # the weight of a direction the scenes stage rates 0 (a rating of 10 weighs 1)
    noise: float = 0.03                  # seeded noise on the scores: variety, not randomness
    box_width: float = 0.30              # a person's box half-width as a share of their height, and a margin on the height
    box_margin: float = 1.15


def bins(): return np.arange(int(360 / BIN_DEG)) * BIN_DEG - 180.0 + BIN_DEG / 2


def wrap(a): return (np.asarray(a, float) + 180.0) % 360.0 - 180.0


def person_share(yaw, pitch, hfov, aspect, boxes, st):
    """The share of the view (yaw, pitch, hfov) that people cover: `boxes` is [(yaw, pitch, height_deg)] in the grid's frame (the wearer included; a missing height counts as 45 degrees)."""
    if not boxes: return 0.0
    d = VQ.view_dirs(yaw, pitch, hfov, aspect); lon = np.degrees(np.arctan2(d[:, 0], d[:, 1])); lat = np.degrees(np.arcsin(np.clip(d[:, 2], -1, 1))); hit = np.zeros(len(d), bool)
    for by, bp, bh in boxes:
        h = float(bh or 45.0) * st.box_margin; w = st.box_width * h / max(math.cos(math.radians(bp)), 0.2)
        hit |= (np.abs(wrap(lon - by)) < w) & (np.abs(lat - bp) < h / 2)
    return float(hit.mean())


def node_scores(grid, t, heading, prior, boxes, st):
    """The score of every yaw bin at time `t`: (24,) array, and the people share of each."""
    i = int(round(t * float(grid['hz']))); h = heading(t); b = bins(); fb = boxes(t); out = np.zeros(len(b)); shares = np.zeros(len(b))
    for k, y in enumerate(b):
        look = VQ.view_score(grid, i, y, st.pitch, st.hfov, st.aspect)['score']; pr = prior(t, float(wrap(y - h))); share = person_share(y, st.pitch, st.hfov, st.aspect, fb, st); shares[k] = share
        out[k] = look * (st.prior_floor + (1 - st.prior_floor) * pr) - st.person_cost * max(0.0, share - st.person_share)
    return out, shares


def availability(grid, times, heading, prior, boxes, st=None):
    """For each time in `times`: the best view's score over all directions, 0 where every direction has a person in it or looks bad (0..1): is there somewhere good to look that shows no one?"""
    st = st or Settings(); return np.array([max(float(node_scores(grid, t, heading, prior, boxes, st)[0].max()), 0.0) for t in times])


def track(grid, t0, t1, heading, prior, boxes, st=None, rng=None, start=None):
    """The camera over [t0, t1] (clip seconds): dict(times, yaw (degrees, in the grid's frame, one per step), jumps (indices of steps that start with a cut), score, budget). `start` (a yaw in degrees) makes the camera begin there (within a bin); else it begins wherever is best."""
    st = st or Settings(); rng = rng if rng is not None else np.random.default_rng(0); n = max(int(math.floor((t1 - t0) / st.step_s + 1e-9)) + 1, 2); times = t0 + np.arange(n) * st.step_s; times = np.minimum(times, t1)
    S = np.array([node_scores(grid, t, heading, prior, boxes, st)[0] for t in times]) + rng.normal(0, st.noise, (n, 24)); J = int(math.floor(st.budget_per_min * (t1 - t0) / 60.0 + 1e-9)); B = 24
    NEG = -1e18; V = np.full((n, B, J + 1), NEG); P = np.zeros((n, B, J + 1, 2), int); V[0, :, 0] = S[0]
    if start is not None: V[0, np.abs(wrap(bins() - start)) > BIN_DEG, 0] = NEG
    d = np.abs(np.arange(B)[:, None] - np.arange(B)[None, :]); d = np.minimum(d, B - d)                                 # circular distance in bins between b0 (row) and b1 (column)
    pan = max(int(1e-9 + 15.0 * st.step_s / BIN_DEG), 1)
    for t in range(1, n):
        for j in range(J + 1):
            for b1 in range(B):
                best, arg = NEG, (0, 0)
                for b0 in range(B):
                    if d[b0, b1] <= pan: v = V[t - 1, b0, j]; c = st.pan_cost * d[b0, b1]; jj = j
                    elif j > 0: v = V[t - 1, b0, j - 1]; c = st.jump_cost; jj = j - 1
                    else: continue
                    if v > NEG / 2 and v - c > best: best, arg = v - c, (b0, jj)
                if best > NEG / 2: V[t, b1, j] = best + S[t, b1]; P[t, b1, j] = arg
    b, j = np.unravel_index(int(np.argmax(V[-1])), V[-1].shape); path = [int(b)]; jumps = []
    for t in range(n - 1, 0, -1):
        b0, jj = P[t, b, j]
        if jj != j: jumps.append(t)
        b, j = int(b0), int(jj); path.append(b)
    path = path[::-1]; yaw = bins()[path]; return dict(times=times, yaw=yaw, jumps=sorted(jumps), score=float(V[-1].max()) / n, budget=J)


def keyframes(path, T, pitch=0.0, fov=100.0, t0=None):
    """Camera keyframes (window seconds from 0 to T; the world frame, yaw continuous across pans, a cut where the path jumps: two keyframes 0.04 s apart)."""
    t0 = float(path['times'][0]) if t0 is None else t0; ts = np.clip(path['times'] - t0, 0.0, T); yaw = np.array(path['yaw'], float); out = []; cur = yaw[0]; last = None
    for k, (t, y) in enumerate(zip(ts, yaw)):
        if k == 0 or k in path['jumps']:
            if k in path['jumps'] and last is not None: out.append(dict(t=round(max(t - 0.04, last), 3), yaw=round(float(cur), 2), pitch=pitch, fov=fov, ease='linear'))
            cur = float(y)
        else: cur += float(wrap(y - cur))                                                                                              # continuous: the shortest way round (cur is not kept inside +-180)
        out.append(dict(t=round(float(t), 3), yaw=round(float(cur), 2), pitch=pitch, fov=fov, ease='linear')); last = float(t)
    if out[-1]['t'] < T: out.append(dict(out[-1], t=round(float(T), 3)))
    return out
