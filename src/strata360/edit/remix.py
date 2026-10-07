"""Re-sequence a track to any length (Milestone G0a, docs/ai-music.md 4.4): a list of source bars, one per film bar, in which every join between two stretches falls on a downbeat between bars that sound alike, the track starts at its first bar and ends on its own ending.

plan(sim, target_bars, ...) -> dict(bars=[source bar index per film bar], runs=[(src_start, n_bars)], joins=[cost per join], worst_join)   pure: needs only the bar similarity matrix
render(x, sr, downbeats, bars, ...) -> (samples, film downbeats in seconds)   joins are equal-power crossfades centred on the downbeat"""
import numpy as np


def join_cost(sim, a, b):
    """How audible it is to jump from the end of bar a to the start of bar b: bar b should sound like the bar that would have come next (a + 1), and a like the bar before b (b - 1)."""
    n = len(sim); x = sim[a + 1, b] if a + 1 < n else 0.0; y = sim[a, b - 1] if b >= 1 else 0.0
    return float(1.0 - 0.5 * (x + y))


def plan(sim, target_bars, ending_bars=2, jump_penalty=0.05, levels=None, energy=None, level_weight=0.5, hold=(), prefix=0, bad_join=0.3, bad_weight=4.0, min_run=4, short_weight=0.3, pins=()):
    """A re-sequencing of target_bars bars from a track of len(sim) bars. Bar 0 first, the last `ending_bars` bars of the track last (in order, played nowhere else), and in between the cheapest path: playing on costs nothing, a jump costs join_cost + jump_penalty. With levels (a 0..1 target per film bar) and energy (0..1 per source bar) the path also prefers bars whose energy is near the level.
    hold: source bar ranges [(first, last)] (inclusive) that, when played, are played whole: no jump leaves from inside one or lands inside one, so a sung verse is never cut.
    prefix: that many bars at the start are played exactly as the track has them (an iconic intro and its first build and break) and the re-sequencing begins after them.
    bad_join, bad_weight: a join costing more than bad_join (see join_cost) is charged bad_weight times the excess again, so it must buy a real gain in matching the level.
    min_run, short_weight: leaving a stretch after fewer than min_run bars costs up to short_weight extra (the fewer, the more), so a cheap join is not used again and again to loop two or three bars.
    pins: [(film_bar, source_bar, n_bars)]: film bar film_bar + k plays source bar source_bar + k for k < n_bars (a sung phrase placed where the film wants it); a pin that falls in the opening, in the ending or outside the film or the track is ignored."""
    n = len(sim); T = int(target_bars)
    if T < 1: raise ValueError('target_bars must be at least 1')
    if T == n: return _result(list(range(n)), sim)                                                      # the track already fits: play it as it is
    E = min(ending_bars, n - 1); tail = list(range(n - E, n)); free = T - len(tail); m = n - E                      # m source bars may be played in the middle
    if free < 1: return _result(tail[len(tail) - T:], sim)                                               # shorter than the ending: its last bars
    pen = lambda c: c + bad_weight * max(0.0, c - bad_join)                                                  # a join worse than bad_join costs much more: it must buy a real gain in matching the level
    J = np.array([[0.0 if b == a + 1 else pen(join_cost(sim, a, b)) + jump_penalty for b in range(m)] for a in range(m)])
    for h0, h1 in hold:
        for a in range(h0, min(h1, m - 1)): J[a, np.arange(m) != a + 1] = np.inf                                # leaving from inside the held range: only on to the next bar
        for b in range(h0 + 1, min(h1 + 1, m)): J[np.arange(m) != b - 1, b] = np.inf                       # landing inside it: only from the bar before
    lv = None if levels is None else np.asarray(levels, float); en = None if energy is None else np.asarray(energy, float)[:m]
    stay = lambda i: np.zeros(m) if lv is None or en is None else level_weight * np.abs(en - lv[min(i, len(lv) - 1)])
    P = prefix if 0 < prefix < m and free - prefix >= 0 else 0; free2 = free - P; head = list(range(P))
    if P and free2 == 0: return _result(head + tail, sim)
    into = np.array([0.0 if a == m - 1 else pen(join_cost(sim, a, m)) + jump_penalty for a in range(m)])         # the last free bar joins the ending
    for h0, h1 in hold: into[h0:min(h1, m - 1)] = np.inf                                                     # the jump into the ending may not cut a held range

    forced = {}
    for fb, sb, n in pins:
        for k in range(int(n)):
            f = int(fb) + k - P; b = int(sb) + k
            if 0 <= f < free2 and 0 <= b < m: forced[f] = b
    keep = lambda f, new: new if f not in forced else np.where(np.arange(m)[:, None] == forced[f], new, np.inf)               # a pinned film bar plays only its source bar
    R = max(2, int(min_run)); extra = np.array([short_weight * (R - 1 - r) / (R - 1) for r in range(R)]); Jj = J.copy()               # state: the bar and how many bars of this stretch have played (1..R, capped)
    for a in range(m - 1): Jj[a, a + 1] = np.inf                                                              # the plain step to the next bar is a continuation, not a jump
    cost = np.full((free2, m, R), np.inf); ba = np.zeros((free2, m, R), int); br = np.zeros((free2, m, R), int)
    if P:
        cost[0, :, 0] = J[P - 1] + stay(P); cost[0, P, 0] = np.inf; cost[0, P, R - 1] = stay(P)[P]                    # carrying on from the opening is a long stretch
    else: cost[0, 0, 0] = stay(0)[0]
    cost[0] = keep(0, cost[0])
    for i in range(1, free2):
        prev = cost[i - 1]; new = np.full((m, R), np.inf)
        for r in range(R):                                                                                    # continue: the next bar, one bar longer
            rn = min(r + 1, R - 1); c = prev[:-1, r]; better = c < new[1:, rn]; new[1:, rn] = np.where(better, c, new[1:, rn]); ba[i, 1:, rn] = np.where(better, np.arange(m - 1), ba[i, 1:, rn]); br[i, 1:, rn] = np.where(better, r, br[i, 1:, rn])
        eff = prev + extra[None, :]; er = np.argmin(eff, 1); ev = eff[np.arange(m), er]                          # jump: leave from the cheapest length of stretch
        c = ev[:, None] + Jj; k = np.argmin(c, 0); cj = c[k, np.arange(m)]; better = cj < new[:, 0]; new[:, 0] = np.where(better, cj, new[:, 0]); ba[i, :, 0] = np.where(better, k, ba[i, :, 0]); br[i, :, 0] = np.where(better, er[k], br[i, :, 0])
        cost[i] = keep(i, new + stay(i + P)[:, None])
    fin = cost[free2 - 1] + into[:, None] + np.where(np.arange(m)[:, None] == m - 1, 0.0, extra[None, :])           # the last free bar joins the ending
    a, r = np.unravel_index(int(np.argmin(fin)), fin.shape); seq = [int(a)]
    for i in range(free2 - 1, 0, -1): a, r = ba[i, a, r], br[i, a, r]; seq.append(int(a))
    return _result(head + seq[::-1] + tail, sim)


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
