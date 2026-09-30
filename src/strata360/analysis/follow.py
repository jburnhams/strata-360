"""Choosing which other person to frame over time, for the player's Person mode (and later the film's framing): always somebody (never the wearer) when anybody is in view, the same person for as long as
possible, and as few jumps between different people as possible.

Input: per sample (once a second) the people seen, each with world yaw (deg), pitch, height_deg (bigger = closer) and whether a face was found. The detections carry no identity, so a person is
followed by position: the same person is one whose world yaw is within a tolerance of the previous choice (which grows with the time between samples, since people move).

A dynamic programme (Viterbi) picks one candidate per sample to minimise  sum(-appeal) + SWITCH * number of changes of person:  a change is only worth it when the new person is clearly better
(bigger / face visible) than staying with the current one for the whole stretch, not just for one sample."""
import math

SWITCH = 1.6          # cost of changing person, in "appeal" units (a person 40 degrees tall with a face scores about 1.1)
TOL_DEG = 22.0        # same person if the world yaw differs by less than this ...
TOL_PER_S = 10.0      # ... plus this per second between the samples


def appeal(c): return min(c.get('height_deg') or 10.0, 60.0) / 45.0 + (0.25 if c.get('face') else 0.0)


def _dyaw(a, b): return abs((a - b + 180.0) % 360.0 - 180.0)


def same(a, b, dt): return _dyaw(a['yaw'], b['yaw']) <= TOL_DEG + TOL_PER_S * max(dt, 0.0)


def choose(frames):
    """frames: [{t, cands: [{yaw, pitch, height_deg, face}]}] -> list of (index into cands or None, person id or None), one per frame."""
    idx = [k for k, f in enumerate(frames) if f['cands']]; out = [(None, None)] * len(frames)
    if not idx: return out
    prev_cost = [-appeal(c) for c in frames[idx[0]]['cands']]; back = []
    for a, b in zip(idx, idx[1:]):
        fa, fb = frames[a], frames[b]; dt = fb['t'] - fa['t']; cost = []; bp = []
        for cb in fb['cands']:
            best = None
            for i, ca in enumerate(fa['cands']):
                v = prev_cost[i] + (0.0 if same(ca, cb, dt) else SWITCH)
                if best is None or v < best[0]: best = (v, i)
            cost.append(best[0] - appeal(cb)); bp.append(best[1])
        back.append(bp); prev_cost = cost
    j = min(range(len(prev_cost)), key=prev_cost.__getitem__); path = [j]
    for bp in reversed(back): j = bp[j]; path.append(j)
    path.reverse(); pid = 0; last = None
    for n, (k, j) in enumerate(zip(idx, path)):
        c = frames[k]['cands'][j]
        if last is not None and not same(last[1], c, frames[k]['t'] - last[0]): pid += 1
        out[k] = (j, pid); last = (frames[k]['t'], c)
    return out


def switches(choice): return len({p for _, p in choice if p is not None})
