"""Speed ramps: long, uneventful running is raced through in a fast, stabilised hyperlapse instead of being cut out (implementation plan, Milestone H).

The planner leaves most of a long clip unused: between two windows of one clip (or after a clip's last window) the running is simply skipped by a cut. Here a window followed by a long, quiet stretch becomes
a RAMP WINDOW. Its length in the film does not change (the cuts stay on the beat); only the footage it plays does:

  lead      the window's own moment at real speed (at least LEAD_MIN_S, LEAD_FRAC of the window)
  ramp up   an eased speed-up (a half cosine) to the hyperlapse speed
  hold      the quiet stretch at `speed` (3x to 24x)
  ramp down eased back to real speed
  tail      real speed again, landing exactly where the next window of the clip starts, so the cut after it joins one continuous run

The speed is solved so the window lands on the next window's start; when the stretch is too long for MAX_SPEED the ramp covers what it can and the cut after it skips the rest, as before.

A stretch is QUIET when nobody talks in it (the clip's speech stretches), you did not skip it in the GUI (a banned window), no other window of the film shows it, and it holds no unusable footage longer than
UNUSABLE_MAX_S (a moment of hand over the lens flashes by at 10x; a minute of it does not). Only windows that follow your heading (`follow_runner`) are ramped: a view aimed at a person or at you cannot keep
them in frame at 10x. A window the optimiser gave another technique is switched to `follow_runner` (when that is one of its options, or the window's length suits it), unless you chose its technique or
it is locked. A glide into it from the window before still works: the ramp starts with its own moment at real speed.

Stabilisation. The gyro already holds the view still whatever the camera does (render/flat.py stabilises every frame), and the heading the camera follows is smoothed in FILM time (render/camera.py), so at
10x it is calm. What a hyperlapse adds is the choice of source frames (`select_frames`, after Joshi et al. 2015, "Real-time hyperlapse creation via optimal frame selection"): near each frame the speed asks
for, the renderer may take a neighbour instead, and a dynamic programme picks the run of frames that keeps
  * the stride in step: running bobs the camera up and down three times a second; the accelerometer's magnitude gives the stride's phase, and frames at the same phase (the top of the stride, where the
    camera moves least) take the bounce out of the hyperlapse. Fully so only above one stride per film frame (about 17x at 3 steps a second and 50 fps; on synthetic running the bounce falls to a quarter
    at 20x); slower, there are fewer frames at that phase than film frames, and the picker only narrows the spread (to two thirds at 12x);
  * motion blur low: frames where the gyro turns fastest are avoided;
  * the speed steady: the step between chosen frames stays close to the one asked for, and no frame strays far from its time.
At real speed (the lead and the tail) the window is the plain footage, frame for frame.

The plan carries the ramp on the segment (`ramp`: dur_s, lead_s, ramp_s, tail_s, speed, src_dur_s, lands) and `src_dur_s`: the seconds of the clip the window plays. `src_time` maps a window's film seconds to clip
seconds; the renderer, the time map and the sound use it."""
import datetime as dt
from dataclasses import dataclass
import numpy as np

LEAD_FRAC = 0.35       # the share of a ramp window that plays its own moment at real speed first
LEAD_MIN_S = 1.0
RAMP_S = 0.6           # each eased change of speed
TAIL_S = 0.3           # real speed before the landing
MIN_GAP_S = 20.0       # a quiet stretch shorter than this is cut as before
MIN_WINDOW_S = 3.0     # a shorter window has no room for a ramp
MIN_SPEED, MAX_SPEED = 3.0, 24.0       # faster than 24x a run reads as flicker, and the renderer decodes every frame it passes
UNUSABLE_MAX_S = 2.0   # unusable footage longer than this ends a quiet stretch
TECHS = ('follow_runner',)
CONTIGUOUS_S = 0.05    # (seconds) the next window of the clip may start this far before the ramp window's end

MAX_RADIUS = 8         # frames: how far the frame picker may move from the frame the speed asks for
W_BLUR, W_BOB, W_DRIFT, W_VEL = 1.0, 1.0, 0.5, 2.0
CADENCE_HZ = (1.2, 4.0)     # running and walking cadence: the band of the accelerometer that holds the stride
MIN_STRIDE_SHARE = 0.3      # the stride band must hold this share of the accelerometer's variation, else there is no stride to keep in step (standing, riding a bus)


@dataclass
class Settings:
    enabled: bool = True
    min_gap_s: float = MIN_GAP_S
    min_window_s: float = MIN_WINDOW_S
    min_speed: float = MIN_SPEED
    max_speed: float = MAX_SPEED
    lead_frac: float = LEAD_FRAC
    lead_min_s: float = LEAD_MIN_S
    ramp_s: float = RAMP_S
    tail_s: float = TAIL_S
    unusable_max_s: float = UNUSABLE_MAX_S


# ------------------------------------------------------------------------------------------------------------------------------------- the speed ramp
def profile(D, S, st=None):
    """The ramp of a window `D` film seconds long that plays `S` seconds of footage: dict(dur_s, lead_s, ramp_s, tail_s, speed, src_dur_s), or None when the window is too short for one or `S` needs less than
    `min_speed`. The speed is capped at `max_speed`; `src_dur_s` then falls short of `S`."""
    st = st or Settings(); D, S = float(D), float(S)
    lead = max(st.lead_min_s, st.lead_frac * D); tail = min(st.tail_s, max(D - lead, 0.0) / 4); L = D - lead - tail          # L: the film seconds from the start of the speed-up to the end of the slow-down
    if D < st.min_window_s - 1e-9 or L <= 0: return None
    r = min(st.ramp_s, L / 3); V = (S - D + L - r) / (L - r)                                                                         # S = (D - L) + r (1 + V) + V (L - 2 r): real speed, two half-cosine ramps, the hold
    if V < st.min_speed - 1e-9: return None
    rp = dict(dur_s=round(D, 4), lead_s=round(lead, 4), ramp_s=round(r, 4), tail_s=round(tail, 4), speed=round(min(V, st.max_speed), 4))
    rp['src_dur_s'] = round(float(offsets(rp, rp['dur_s'])), 4); return rp


def speed_at(ramp, t):
    """The playback speed (1 = real time) at film seconds `t` from the window's start."""
    t = np.asarray(t, float); a, r, V = ramp['lead_s'], ramp['ramp_s'], ramp['speed']; D = ramp['dur_s']; b = D - ramp['tail_s']
    up = np.clip((t - a) / r, 0, 1); down = np.clip((b - t) / r, 0, 1); e = (1 - np.cos(np.pi * np.minimum(up, down))) / 2
    return 1 + (V - 1) * e


def offsets(ramp, t):
    """Clip seconds from the window's start shown at film seconds `t` from its start (the integral of `speed_at`, exact). Real speed before the window and after it (a transition plays a little of both)."""
    t = np.asarray(t, float); a, r, V = ramp['lead_s'], ramp['ramp_s'], ramp['speed']; D = ramp['dur_s']; b = D - ramp['tail_s']; k = V - 1
    def ease(x):                                                                                      # the integral of (1 - cos(pi u / r)) / 2 over the first x seconds of a ramp r long
        return (x - r / np.pi * np.sin(np.pi * x / r)) / 2
    x1 = np.clip(t - a, 0, r); x2 = np.clip(t - (a + r), 0, (b - r) - (a + r)); x3 = np.clip(t - (b - r), 0, r)          # into the speed-up, the hold, the slow-down
    return t + k * (ease(x1) + x2 + ease(r) - ease(r - x3))


def src_dur(g):
    """The seconds of its clip a plan segment plays: `src_dur_s` for a ramp window, its length otherwise."""
    return float(g.get('src_dur_s') or g['dur_s'])


def src_span(g):
    """(start, end) clip seconds a plan segment plays."""
    a = float(g.get('clip_start_s') or 0.0); return a, a + src_dur(g)


def src_time(g, t):
    """Clip seconds shown at film seconds `t` from the start of plan segment `g` (t may be negative or past the window's end inside a transition: real speed there)."""
    t = np.asarray(t, float); return float(g.get('clip_start_s') or 0.0) + (offsets(g['ramp'], t) if g.get('ramp') else t)


# ------------------------------------------------------------------------------------------------------------------------------------- choosing the source frames
def stride_cost(acc, fps):
    """0..1 per source frame: how far each frame is from the top of the runner's stride (0 at the trough of the accelerometer's magnitude, where the camera is highest and moves least), from the phase of
    the cadence band; zeros when the clip has no clear stride (too short, standing, no accelerometer)."""
    acc = np.asarray(acc, float); n = len(acc)
    if acc.ndim != 2 or n < 4 * fps / CADENCE_HZ[0] or fps <= 2 * CADENCE_HZ[1]: return np.zeros(n)
    from scipy.signal import butter, hilbert, sosfiltfilt
    mag = np.linalg.norm(acc, axis=1); mag = mag - mag.mean()
    if not np.isfinite(mag).all() or mag.var() <= 1e-12: return np.zeros(n)
    band = sosfiltfilt(butter(2, CADENCE_HZ, btype='band', fs=fps, output='sos'), mag)
    if band.var() < MIN_STRIDE_SHARE * mag.var(): return np.zeros(n)
    return (1 + np.cos(np.angle(hilbert(band)))) / 2


def blur_cost(quat):
    """0..1 per source frame: how fast the camera turns there (the angle between a frame's orientation and the next's, from the gyro's quaternions), against the clip's usual turn rate."""
    q = np.asarray(quat, float); n = len(q)
    if q.ndim != 2 or n < 2: return np.zeros(n)
    q = q / np.maximum(np.linalg.norm(q, axis=1, keepdims=True), 1e-12); ang = 2 * np.arccos(np.clip(np.abs(np.sum(q[1:] * q[:-1], axis=1)), 0, 1)); ang = np.append(ang, ang[-1])
    med = float(np.median(ang)); return np.clip(ang / (4 * med), 0, 1) if med > 1e-9 else np.zeros(n)


def select_frames(f_ideal, frame_cost, max_radius=MAX_RADIUS):
    """The source frame (index) for each output frame: near the fractional indices `f_ideal` (increasing) the speed asks for, the run that minimises the frames' own cost (`frame_cost`, one per source
    frame), the drift from the ideal and the change of step (dynamic programme). Where the step is about one frame (real speed) the frame is the ideal one."""
    f = np.asarray(f_ideal, float); m = len(f); n = len(frame_cost); cost = np.asarray(frame_cost, float)
    if m == 0: return np.zeros(0, int)
    step = np.diff(f, prepend=f[0] - (f[1] - f[0] if m > 1 else 1.0)); loc = np.maximum(step, np.append(step[1:], step[-1]))
    rad = np.clip(np.floor(loc / 2 + 1e-9), 0, max_radius).astype(int); centre = np.clip(np.round(f).astype(int), 0, n - 1)
    cands = [np.unique(np.clip(np.arange(c - r, c + r + 1), 0, n - 1)) for c, r in zip(centre, rad)]
    acc = cost[cands[0]] + W_DRIFT * ((cands[0] - f[0]) / max(rad[0], 1)) ** 2; back = []
    for i in range(1, m):
        c = cands[i]; own = cost[c] + W_DRIFT * ((c - f[i]) / max(rad[i], 1)) ** 2; s = max(step[i], 1e-6)
        d = c[:, None] - cands[i - 1][None, :]; tr = W_VEL * ((d - s) / max(s, 1.0)) ** 2
        ok = d >= (1 if s >= 1.5 else 0)                                                              # fast: always forwards; about real speed: a frame may repeat (a film faster than the footage)
        if not (ok & np.isfinite(acc)[None, :]).any(): ok = d >= 0
        if not ok.any(): ok = np.ones_like(ok)                                                        # (never stuck)
        tot = acc[None, :] + np.where(ok, tr, np.inf); j = np.argmin(tot, axis=1)
        acc = tot[np.arange(len(c)), j] + own; back.append(j)
    out = np.zeros(m, int); k = int(np.argmin(acc)); out[-1] = cands[-1][k]
    for i in range(m - 1, 0, -1): k = int(back[i - 1][k]); out[i - 1] = cands[i - 1][k]
    return out


def source_times(g, times, pts, quat=None, acc=None):
    """The clip seconds (from the clip's first frame) to show at film seconds `times` of plan segment `g`: for a ramp window the frames the picker chose (the stride in step, the blur low); otherwise
    `clip_start_s + times` unchanged."""
    t = src_time(g, times)
    if not g.get('ramp') or len(pts) < 2: return t
    rel = np.asarray(pts, float) - float(pts[0]); f = np.interp(t, rel, np.arange(len(rel)))
    fps = 1.0 / max(float(np.median(np.diff(rel))), 1e-6); cost = np.zeros(len(rel))
    if quat is not None and len(quat) == len(rel): cost += W_BLUR * blur_cost(quat)
    if acc is not None and len(acc) == len(rel): cost += W_BOB * stride_cost(acc, fps)
    k = select_frames(f, cost); return np.where((t >= rel[0]) & (t <= rel[-1]), rel[k], t)                     # (outside the clip the renderer holds the end frame, as before)


# ------------------------------------------------------------------------------------------------------------------------------------- the planner's pass
def _merge(spans):
    out = []
    for a, b in sorted(spans):
        if out and a <= out[-1][1]: out[-1] = (out[-1][0], max(out[-1][1], b))
        else: out.append((a, b))
    return out


def blockers(clip, bans=(), st=None):
    """[(a, b)] clip seconds a hyperlapse may not race through: the clip's speech stretches, windows you skipped, unusable footage longer than `unusable_max_s`."""
    st = st or Settings(); out = [(float(c['start_s']), float(c['end_s'])) for c in clip.get('candidates') or [] if c.get('kind') == 'speech']
    out += [(float(u['start_s']), float(u['end_s'])) for u in clip.get('unusable') or [] if float(u['end_s']) - float(u['start_s']) > st.unusable_max_s]
    for key in bans:
        if key.startswith('win:') and key.count('@') >= 2:
            cid, a, b = key[4:].rsplit('@', 2)
            if cid == clip['id']: out.append((float(a), float(b)))
        else: out += [(float(c['start_s']), float(c['end_s'])) for c in clip.get('candidates') or [] if c.get('id') == key]
    return _merge(out)


def quiet_run(start, limit, blocked):
    """The end of the quiet stretch from clip second `start` up to `limit`: the first blocked stretch after it, or `limit`; `start` itself when it is blocked."""
    end = limit
    for a, b in blocked:
        if a <= start < b: return start
        if start <= a < end: end = a
    return end


def _iso(utc, add):
    t = dt.datetime.fromisoformat(utc.replace('Z', '+00:00')) + dt.timedelta(seconds=add); return t.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'


def apply(segs, clips, lib=None, bans=(), protect=(), st=None):
    """Turn the plan's windows that are followed by a long quiet stretch into ramp windows, in place (see the module docstring). `clips` are the planner's clip dicts (candidates, unusable, duration_s),
    `bans` the stretches you skipped (the planner's `bans_cands`), `protect` the windows whose technique you chose. Returns the report: one dict per ramp (window, clip seconds raced through, speed, landing)."""
    st = st or Settings(); report = []
    if not st.enabled: return report
    by_id = {c['id']: c for c in clips}; foot = [g for g in segs if not g.get('synthetic') and g.get('clip') in by_id]
    for k, g in enumerate(segs):
        if g.get('synthetic') or g.get('ramp') or g.get('clip') not in by_id or g.get('speech') or g.get('role') == 'clip' or g.get('locked') or float(g['dur_s']) < st.min_window_s - 1e-9: continue
        tech = g.get('technique'); switch = None
        if tech not in TECHS:
            opts = [o.get('tech') for o in g.get('options') or []]; d = float(g['dur_s'])
            switch = next((t for t in TECHS if t in opts or (lib is not None and t in lib and lib[t].dmin - 1e-9 <= d <= lib[t].dmax + 1e-9)), None)
            if switch is None or g.get('id') in protect: continue
        clip = by_id[g['clip']]; e0 = float(g['clip_start_s']) + float(g['dur_s'])
        nxt = [float(h['clip_start_s']) for h in foot if h is not g and h['clip'] == g['clip'] and float(h['clip_start_s']) >= e0 - CONTIGUOUS_S]
        limit = min(nxt + [float(clip.get('duration_s') or e0)])
        end = quiet_run(e0, limit, blockers(clip, bans, st)); gap = end - e0
        if gap < st.min_gap_s - 1e-9: continue
        rp = profile(g['dur_s'], float(g['dur_s']) + gap, st)
        if rp is None: continue
        rp['lands'] = bool(nxt) and end >= limit - 1e-6 and rp['src_dur_s'] >= float(g['dur_s']) + gap - 1e-3            # the window ends where the next window of the clip starts: one continuous run
        if switch is not None:
            g['ramp_from'] = tech; g['technique'] = switch
            if lib is not None and switch in lib: g['family'] = lib[switch].family; g['hero'] = lib[switch].hero
        g['ramp'] = rp; g['src_dur_s'] = rp['src_dur_s']
        if g.get('utc_start'): g['utc_end'] = _iso(g['utc_start'], rp['src_dur_s'])
        report.append(dict(id=g.get('id'), clip=g['clip'], film_start_s=g.get('film_start_s'), dur_s=g['dur_s'], from_s=round(e0, 3), to_s=round(float(g['clip_start_s']) + rp['src_dur_s'], 3), speed=rp['speed'], lands=rp['lands'], technique_was=switch and tech))
    return report


def summary(report):
    """One line for the plan's notes: how much running the ramps race through."""
    if not report: return None
    s = sum(r['to_s'] - r['from_s'] for r in report); return f"{len(report)} speed ramp{'s' if len(report) != 1 else ''} race through {s / 60:.1f} min of running that would have been cut (up to x{max(r['speed'] for r in report):.0f})"

