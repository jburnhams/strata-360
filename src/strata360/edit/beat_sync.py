"""Cuts on the music's real beats (implementation plan V5).

The plan is made in whole beats of one constant tempo (edit/script_plan.py), but a played track drifts: the real beats wander tens of milliseconds either side of that grid, and the analysis' first downbeat
is itself about 23 ms early. This pass moves every cut onto a real beat of the track (edit/music.beat_grid, kept in music/grid.json) and chooses where the music starts, so the cuts land on what is heard.

  sync(segs, beats, downbeats, seek_s, lines=(), clip_len=None, dur_range=None, settings=None) -> (segments, report)

`segs` are the plan's segment dicts in film order, `beats` and `downbeats` times in the track, `seek_s` where the track starts playing at film time 0 (the first downbeat, `offset_s`), `lines` the narration as
[(first word, last word, text)] in film seconds. The music may start up to half a beat earlier or later (a small search over offsets, scored by how well the cuts that matter land: block boundaries and the
film's end prefer bar lines); then the cuts are placed together by dynamic programming over the beats near each one.

A cut moves on its own: the shot after it starts that much earlier or later in its clip, so every other frame, every word of the clips' sound and every narration line keeps its film time; only the frames on
either side of the cut change hands. Hard rules (a cut that cannot keep them stays off the beat, at the allowed point nearest a beat, and the report says why):
  1. the runner's words the script plays (a window's `voice_span`; a speech window without one counts whole) stay whole: a cut next to them may only move away from them;
  2. a narration line keeps its lead-in: a cut before a line never moves closer to its first word than `lead_s`; a cut under a line (between its words) never moves out in front of it;
  3. a shot stays inside its clip, never shows footage another shot of the film shows, and does not get further from its technique's length range; a generated clip plays at most `stretch` faster or slower;
  4. the film does not end before the last narration and the runner's last word (plus `end_pad_s`).
Times are kept exact; the picture cuts on the nearest frame when rendered (render/film.py), the sound at the sample."""
import bisect, dataclasses, datetime as dt, math
from dataclasses import dataclass

import numpy as np


@dataclass
class SyncSettings:
    tolerance_beats: float = 0.5      # a cut moves at most this far (in beats) either way
    shift_beats: float = 0.5          # the music's start moves at most this far either way
    shift_step_s: float = 0.005
    lead_s: float = 0.12              # picture before a narration line's first word after a cut (voiceover.LEAD_S)
    stretch: float = 0.08             # a generated clip plays at most this much faster or slower
    end_pad_s: float = 0.3            # the film runs at least this long after the last word
    min_shot_s: float = 0.3
    w_move: float = 0.5               # cost per beat a cut moves (the plan already put each cut on a beat of the average tempo: a bar line half a beat away is not worth moving the picture that far)
    w_beat: float = 0.05              # a beat rather than a bar line
    w_beat_key: float = 0.2           # ... for a cut that matters (a block boundary, the film's end)
    w_off: float = 2.0                # off the beat, plus its distance in beats


def from_downbeats(downbeats, bar_beats):
    """The beats of a track known only by its bar lines (a built track): each bar split evenly, and one bar more after the last line."""
    d = [float(x) for x in downbeats]; out = []
    for a, b in zip(d, d[1:]): out += [a + (b - a) * i / bar_beats for i in range(bar_beats)]
    if len(d) >= 2: step = (d[-1] - d[-2]) / bar_beats; out += [d[-1] + step * i for i in range(bar_beats + 1)]
    return [round(x, 4) for x in out]


class Grid:
    """The track's beats, each marked as a bar line or not."""
    def __init__(self, beats, downbeats):
        self.t = np.asarray(sorted(float(b) for b in beats)); D = np.asarray(sorted(float(b) for b in downbeats))
        if len(D): j = np.searchsorted(D, self.t); near = np.minimum(np.abs(self.t - D[np.clip(j - 1, 0, len(D) - 1)]), np.abs(self.t - D[np.clip(j, 0, len(D) - 1)]))
        else: near = np.full(len(self.t), np.inf)
        self.bar = near < 1e-3; self.beat_s = float(np.median(np.diff(self.t))) if len(self.t) > 1 else 0.5

    def within(self, lo, hi, seek):
        """[(film time, is a bar line)] of the beats inside [lo, hi] with the track started at `seek`."""
        i0 = bisect.bisect_left(self.t, lo + seek - 1e-9); i1 = bisect.bisect_right(self.t, hi + seek + 1e-9)
        return [(float(self.t[i]) - seek, bool(self.bar[i])) for i in range(i0, i1)]

    def nearest(self, x, seek):
        """(film time, is a bar line) of the beat nearest film time x."""
        i = bisect.bisect_left(self.t, x + seek)
        best = min((j for j in (i - 1, i) if 0 <= j < len(self.t)), key=lambda j: abs(self.t[j] - seek - x)); return float(self.t[best]) - seek, bool(self.bar[best])


def _label(s): c = str(s['clip']); return c[-6:-2] if c.startswith('CAM_') else c


def _short(text, n=40): t = ' '.join(str(text).split()); return t if len(t) <= n else t[:n - 1] + '…'


def _shots(segs, clip_len):
    out = []
    for g in segs:
        fs = float(g['film_start_s']); d = float(g['dur_s']); vs = g.get('voice_span'); sp = None
        if vs: sp = (fs + float(vs[0]), fs + float(vs[1]))
        elif g.get('speech') and g.get('role') in (None, 'clip'): sp = (fs, fs + d)                    # (a speech window with no wanted span: all of it is words)
        out.append(dict(fs=fs, end=fs + d, dur=d, syn=bool(g.get('synthetic')), clip=g['clip'], cs=float(g.get('clip_start_s') or 0.0), sp=sp, len=(clip_len or {}).get(g['clip']), tech=g.get('technique'), item=g.get('item'), role=g.get('role')))
    return out


def _bounds(S, k, lines, st, tol):
    """((lo, why), (hi, why)): how far cut k (the start of shot k; k == len(S) is the film's end) may move under the hard rules, and what stops it each way (None: only the tolerance)."""
    A = S[k - 1]; B = S[k] if k < len(S) else None; T = A['end']; lo, lw, hi, hw = -math.inf, None, math.inf, None
    def up(x, why):
        nonlocal lo, lw
        if x > lo: lo, lw = x, why
    def down(x, why):
        nonlocal hi, hw
        if x < hi: hi, hw = x, why
    run = B is not None and not A['syn'] and not B['syn'] and A['clip'] == B['clip'] and A['cs'] < B['cs'] <= A['cs'] + A['dur'] + 0.01          # two shots of one run of a clip (back to back, or overlapping after whole-beat rounding): its words go on through the cut, so moving it costs none
    if A['sp'] and not run: up(A['sp'][1], f"the words in clip {_label(A)} end there")
    if B and B['sp'] and not run: down(B['sp'][0], f"the words in clip {_label(B)} start there")
    if not A['syn'] and A['len'] is not None: down(A['fs'] + A['len'] - A['cs'], f"clip {_label(A)} has no more footage")
    if B and not B['syn']: up(T - B['cs'], f"clip {_label(B)} has no earlier footage")
    others = lambda s: [(x['cs'], x['cs'] + x['dur']) for j, x in enumerate(S) if j not in (k - 1, k) and not x['syn'] and x['clip'] == s['clip']]
    if not A['syn']:                                                                                    # (footage is never shown twice: its sound would be heard twice)
        ce = A['cs'] + A['dur']; nxt = min((a for a, _ in others(A) if a >= ce - 1e-6), default=None)
        if nxt is not None: down(T + nxt - ce, f"the footage of clip {_label(A)} after it is in another shot")
    if B and not B['syn']:
        prv = max((b for _, b in others(B) if b <= B['cs'] + 1e-6), default=None)
        if prv is not None: up(T - (B['cs'] - prv), f"the footage of clip {_label(B)} before it is in another shot")
    for a, b, text in lines:
        if T <= a + 1e-6: down(max(a - st.lead_s, min(T, a)), f'the narration "{_short(text)}" keeps its lead-in')
        elif T < b: up(a, f'the narration "{_short(text)}" keeps its lead-in')
    top = T + tol
    if B is None:                                                                                       # the film's end: never before the last word (a speech window's span is padded already)
        last = max([b + st.end_pad_s for _, b, _ in lines] + [s['sp'][1] for s in S if s['sp']], default=0.0)
        if last > T + 1e-9 and last <= hi + 1e-9: up(last, 'the last words need the film to run on'); top = max(top, last)
    lo, lw = (lo, lw) if lo > T - tol else (T - tol, None)
    hi, hw = (hi, hw) if hi < top else (top, None)
    if B is None and lo > T: return (lo, lw), (max(hi, lo), hw)                                        # (the end has to move later: where it is breaks rule 4)
    return (min(lo, T), lw), (max(hi, T), hw)


def _candidates(grid, seek, T, b, key, st):
    """[(film time, cost, kind)] for one cut: the beats inside its bounds, the allowed point nearest the nearest beat (off the beat) and the cut where it is. kind: 'bar', 'beat', 'off' or 'none' (no music there)."""
    (lo, _), (hi, _) = b; beat = grid.beat_s; out = []
    for x, bar in grid.within(lo, hi, seek): out.append((x, st.w_move * abs(x - T) / beat + (0.0 if bar else st.w_beat_key if key else st.w_beat), 'bar' if bar else 'beat'))
    if T + seek < grid.t[0] - beat or T + seek > grid.t[-1] + beat: return [(min(max(T, lo), hi), 0.0, 'none')]          # before the music starts or after it ends: nothing to land on
    n, _ = grid.nearest(T, seek); x = min(max(n, lo), hi)
    for y in sorted({round(x, 6)} | ({round(T, 6)} if lo - 1e-9 <= T <= hi + 1e-9 else set())):
        if not any(abs(y - c[0]) < 1e-6 for c in out): m, _ = grid.nearest(y, seek); out.append((y, st.w_off + abs(y - m) / beat + st.w_move * abs(y - T) / beat, 'off'))
    return out


def _shot_ok(s, x0, x1, dur_range, st):
    d = x1 - x0
    if d < st.min_shot_s - 1e-9: return False
    if s['syn']: return s['dur'] * (1 - st.stretch) - 1e-6 <= d <= s['dur'] * (1 + st.stretch) + 1e-6
    r = (dur_range or {}).get(s['tech'])
    return r is None or min(r[0], s['dur']) - 1e-6 <= d <= max(r[1], s['dur']) + 1e-6


def _path(S, C, dur_range, st):
    """The cheapest choice of one candidate per cut such that every shot keeps its rules (dynamic programming over the chain). Returns the chosen indices."""
    x0 = S[0]['fs']; prev = [(c[1] if _shot_ok(S[0], x0, c[0], dur_range, st) else math.inf, -1) for c in C[0]]; back = [prev]
    for k in range(1, len(C)):
        cur = []
        for c in C[k]:
            best = (math.inf, -1)
            for j, p in enumerate(C[k - 1]):
                if back[-1][j][0] < math.inf and _shot_ok(S[k], p[0], c[0], dur_range, st): best = min(best, (back[-1][j][0] + c[1], j))
            cur.append(best)
        back.append(cur)
    j = min(range(len(C[-1])), key=lambda i: back[-1][i][0]); cost = back[-1][j][0]; out = [j]
    if cost == math.inf: return cost, None
    for k in range(len(C) - 1, 0, -1): j = back[k][j][1]; out.append(j)
    return cost, out[::-1]


def _shift_cost(grid, seek, S, bounds, keys, st):
    """How well the cuts would land with the track started at `seek`: each cut's cheapest candidate, the shots' rules left out (they are checked when the cuts are placed)."""
    return sum(min(c[1] for c in _candidates(grid, seek, S[k - 1]['end'], b, key, st)) for k, (b, key) in enumerate(zip(bounds, keys), 1))


def _utc(s, d):
    t = dt.datetime.fromisoformat(s.replace('Z', '+00:00')) + dt.timedelta(seconds=d); return t.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'


def sync(segs, beats, downbeats, seek_s, lines=(), clip_len=None, dur_range=None, settings=None):
    """See the module docstring. Returns (new segment dicts, report): report = dict(seek_s, shift_s, delay_s, length_s, cuts, on_bar, on_beat, off_beat=[{cut, film_s, off_ms, why}], moved_max_ms, warnings)."""
    st = settings or SyncSettings(); grid = Grid(beats, downbeats); segs = list(segs)
    if not segs or len(grid.t) < 2: return segs, None
    S = _shots(segs, clip_len); tol = st.tolerance_beats * grid.beat_s; lines = [(float(a), float(b), t) for a, b, t in lines]
    bounds = [_bounds(S, k, lines, st, tol) for k in range(1, len(S) + 1)]
    keys = [k == len(S) or S[k - 1]['clip'] != S[k]['clip'] or S[k - 1]['item'] != S[k]['item'] for k in range(1, len(S) + 1)]
    span = st.shift_beats * grid.beat_s; shifts = np.arange(-span, span + 1e-9, st.shift_step_s)
    costs = [(_shift_cost(grid, seek_s + s, S, bounds, keys, st), abs(s), s) for s in shifts]; shift = float(min(costs)[2]); seek = seek_s + shift
    C = [_candidates(grid, seek, S[k - 1]['end'], b, key, st) for k, (b, key) in enumerate(zip(bounds, keys), 1)]
    _, pick = _path(S, C, dur_range, st)
    if pick is None: _, pick = _path(S, C, None, dataclasses.replace(st, stretch=1.0))                  # (a plan whose shots already break their lengths: only keep the cuts in order)
    if pick is None: return segs, None
    pos = [S[0]['fs']] + [C[k][j][0] for k, j in enumerate(pick)]
    out = []; off = []; kinds = []
    pos = [round(p, 4) for p in pos]
    for i, g in enumerate(segs):
        d0 = pos[i] - S[i]['fs']; h = dict(g); h['film_start_s'] = pos[i]; h['dur_s'] = round(pos[i + 1] - pos[i], 4)
        if not S[i]['syn'] and abs(d0) > 1e-9:
            h['clip_start_s'] = round(float(g['clip_start_s']) + d0, 4); h['in_s'] = round(float(g.get('in_s') or 0.0) + d0, 4)
            if g.get('utc_start'): h['utc_start'] = _utc(g['utc_start'], d0)
        if not S[i]['syn'] and g.get('utc_start'): h['utc_end'] = _utc(h['utc_start'], h['dur_s'])
        if g.get('voice_span'): vs = g['voice_span']; h['voice_span'] = [round(max(float(vs[0]) - d0, 0.0), 3), round(min(float(vs[1]) - d0, h['dur_s']), 3)]
        out.append(h)
    for k, j in enumerate(pick, 1):
        x, _, kind = C[k - 1][j]; kinds.append(kind)
        if kind != 'off': continue
        n, _ = grid.nearest(x, seek); (lo, lw), (hi, hw) = bounds[k - 1]
        why = lw if n < lo - 1e-9 else hw if n > hi + 1e-9 else 'the shots either side would leave their lengths (or a generated clip would play too fast or slow)'
        off.append(dict(cut=k, film_s=round(x, 3), off_ms=round(abs(x - n) * 1000.0, 1), why=why or 'no beat near enough'))
    warn = [f"cut {o['cut']} ({o['film_s']:.1f} s) is {o['off_ms']:.0f} ms off the beat: {o['why']}" for o in off if o['off_ms'] >= 1.0]
    moved = max((abs(p - s['end']) for p, s in zip(pos[1:], S)), default=0.0)
    report = dict(seek_s=round(max(seek, 0.0), 4), delay_s=round(max(-seek, 0.0), 4), shift_s=round(shift, 4), length_s=round(pos[-1], 4), cuts=len(kinds), on_bar=kinds.count('bar'), on_beat=kinds.count('beat'),
                  off_beat=off, after_music=kinds.count('none'), moved_max_ms=round(moved * 1000.0, 1), warnings=warn)
    return out, report
