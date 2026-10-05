"""Re-sequence a track to any length (Milestone G0a, docs/ai-music.md 4.4): a list of source bars, one per film bar, in which every join between two stretches falls on a downbeat between bars that sound alike, the track starts at its first bar and ends on its own ending.

plan(sim, target_bars, ...) -> dict(bars=[source bar index per film bar], runs=[(src_start, n_bars)], joins=[cost per join], worst_join)   pure: needs only the bar similarity matrix
render(x, sr, downbeats, bars, ...) -> (samples, film downbeats in seconds)   joins are equal-power crossfades centred on the downbeat"""
import numpy as np


def join_cost(sim, a, b):
    """How audible it is to jump from the end of bar a to the start of bar b: bar b should sound like the bar that would have come next (a + 1), and a like the bar before b (b - 1)."""
    n = len(sim); x = sim[a + 1, b] if a + 1 < n else 0.0; y = sim[a, b - 1] if b >= 1 else 0.0
    return float(1.0 - 0.5 * (x + y))


def plan(sim, target_bars, ending_bars=2, jump_penalty=0.05, levels=None, energy=None, level_weight=0.5):
    """A re-sequencing of target_bars bars from a track of len(sim) bars. Bar 0 first, the last `ending_bars` bars of the track last (in order, played nowhere else), and in between the cheapest path: playing on costs nothing, a jump costs join_cost + jump_penalty. With levels (a 0..1 target per film bar) and energy (0..1 per source bar) the path also prefers bars whose energy is near the level."""
    n = len(sim); T = int(target_bars)
    if T < 1: raise ValueError('target_bars must be at least 1')
    if T == n: return _result(list(range(n)), sim)                                                      # the track already fits: play it as it is
    E = min(ending_bars, n - 1); tail = list(range(n - E, n)); free = T - len(tail); m = n - E                      # m source bars may be played in the middle
    if free < 1: return _result(tail[len(tail) - T:], sim)                                               # shorter than the ending: its last bars
    J = np.array([[0.0 if b == a + 1 else join_cost(sim, a, b) + jump_penalty for b in range(m)] for a in range(m)])
    lv = None if levels is None else np.asarray(levels, float); en = None if energy is None else np.asarray(energy, float)[:m]
    stay = lambda i: np.zeros(m) if lv is None or en is None else level_weight * np.abs(en - lv[min(i, len(lv) - 1)])
    cost = np.full((free, m), np.inf); back = np.zeros((free, m), int); cost[0, 0] = stay(0)[0]
    for i in range(1, free):
        c = cost[i - 1][:, None] + J; k = np.argmin(c, 0); cost[i] = c[k, np.arange(m)] + stay(i); back[i] = k
    into = np.array([0.0 if a == m - 1 else join_cost(sim, a, m) + jump_penalty for a in range(m)])         # the last free bar joins the ending
    a = int(np.argmin(cost[free - 1] + into)); seq = [a]
    for i in range(free - 1, 0, -1): a = int(back[i, a]); seq.append(a)
    return _result(seq[::-1] + tail, sim)


def _result(bars, sim):
    runs = []; joins = []
    for i, b in enumerate(bars):
        if runs and b == bars[i - 1] + 1: runs[-1][1] += 1
        else:
            if runs: joins.append(round(join_cost(sim, bars[i - 1], b), 4))
            runs.append([b, 1])
    return dict(bars=[int(b) for b in bars], runs=[tuple(r) for r in runs], joins=joins, worst_join=max(joins) if joins else 0.0)


def render(x, sr, downbeats, bars, fade_s=0.08, end_s=None):
    """The audio of the re-sequenced bars: x is (samples,) or (samples, channels) at sr, downbeats the track's bar lines in seconds (len = bars + 1 or more), bars from plan(). Each run is played as it is; a join is an equal-power crossfade of fade_s centred on the downbeat, so the beat lands where it did. The last run plays on to end_s (default: the track's end) so the ending keeps its decay. Returns (samples, the film's downbeats in seconds)."""
    x = np.asarray(x, np.float32); x = x[:, None] if x.ndim == 1 else x; db = list(downbeats)
    if len(db) < max(bars) + 2: db = db + [end_s if end_s is not None else len(x) / sr]
    runs = []
    for i, b in enumerate(bars):
        if runs and b == bars[i - 1] + 1: runs[-1][1] += 1
        else: runs.append([b, 1])
    h = int(fade_s * sr / 2); pieces = []; starts = []; pos = 0
    for k, (b, m) in enumerate(runs):
        last = k == len(runs) - 1; a = int(round(db[b] * sr)); z = int(round((db[b + m] if not last else (end_s if end_s is not None else len(x) / sr)) * sr)); starts.append(pos); pieces.append((a, z)); pos += z - a
    out = np.zeros((pos + 2 * h, x.shape[1]), np.float32); ramp = np.linspace(0, np.pi / 2, max(2 * h, 1))
    for k, (a, z) in enumerate(pieces):
        lo = max(0, a - h) if k else a; hi = min(len(x), z + h) if k < len(pieces) - 1 else z; seg = x[lo:hi].copy(); n = len(seg)
        if k and h:
            f = min(len(ramp), n); seg[:f] *= np.sin(ramp[:f])[:, None]
        if k < len(pieces) - 1 and h:
            f = min(len(ramp), n); seg[n - f:] *= np.cos(ramp[:f])[:, None]
        o = starts[k] - (a - lo); out[o:o + n] += seg
    marks = []; t = 0.0
    for b in bars: marks.append(round(t, 4)); t += db[b + 1] - db[b]
    return out[:pos], marks
