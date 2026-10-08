"""Exposure matching between shots (implementation plan A4): a gentle gain on each footage window so neighbouring shots from different times of day, or from a view of the sky and then of the ground, do not jump, while a day still looks like a day and a night like a night.

  plan_gains(folder, segs, framing) -> {segment id: Gain}      the gain (in stops) of every footage window as a function of the time inside it
  apply(img, stops) -> img                                      the gain on a picture (uint8 or uint16 code values, any channel order), in linear light, with a soft shoulder so highlights are not clipped

How the gain is chosen. The brightness of a window is that of the VIEW it shows: the clip's quality grid (analysis/quality_grid.py, `luma` on the 15 degree grid at 2 Hz, in the frame the camera paths use) averaged over the cells the camera path looks at, every half second, as the log2 of the mean linear luma. A window's own level `m` is its median; the film's local look `s` is the weighted
mean of its neighbours' levels (the two before and after, nearer ones counting more), so the grade follows the film's slow changes (dusk coming on) and removes the jumps. The base gain is `STRENGTH` of `s - m`, limited to +-`CAP_STOPS` (to +`CAP_NIGHT_UP` for a dark window: a night keeps its darkness), plus the window's own nudge (`grade_ev` in the plan segment, the Timeline's brightness control). At its start a window begins at the gain that makes its first frames as bright as the previous window's last were (the cut is invisible in brightness), and eases to its base gain over `EASE_S` seconds. A generated clip, or a window of a clip with no quality grid, gets no gain and breaks the chain.

The same maths runs on the proxy (the preview) and on the lens frames (the final film), so the preview shows the grade."""
import json, math, os

import numpy as np

from strata360.pipeline import config

STRENGTH = 0.8           # the share of the difference to the film's local look that is corrected
CAP_STOPS = 1.0          # the most a window is brightened or darkened (stops)
CAP_NIGHT_UP = 0.35      # the most a dark window is brightened (stops): a night stays dark
DARK_LIN = 0.02          # a window whose mean linear luma is under this is a night shot
EASE_S = 0.6             # seconds over which a window moves from the gain that matches the previous cut to its own base gain
NEIGHBOUR_W = (1.0, 2.0, 3.0, 2.0, 1.0)      # weights of the windows k-2 .. k+2 in the film's local look
KNEE = 0.6               # linear level above which a brightened picture is rolled off towards white
STEP_S = 0.5
GAMMA = 2.4


def code_to_lin(c):
    """Encoded 0..1 to linear light (BT.709 transfer, as the exposure stage measures it)."""
    c = np.asarray(c, np.float64); return np.where(c < 0.081, c / 4.5, ((c + 0.099) / 1.099) ** (1 / 0.45))


def lin_to_code(x):
    x = np.clip(np.asarray(x, np.float64), 0.0, 1.0); return np.where(x < 0.018, 4.5 * x, 1.099 * x ** 0.45 - 0.099)


_LUTS = {}


def lut(stops, bits=8):
    """The lookup table (2**bits entries, the picture's own dtype) for a gain of `stops`, applied in linear light; above the knee a brightened picture rolls off smoothly so no white is made out of nothing and highlights keep their shape."""
    key = (round(float(stops), 2), bits)
    if key not in _LUTS:
        n = 1 << bits; x = code_to_lin(np.arange(n) / (n - 1.0)); g = 2.0 ** key[0]; y = x * g
        if g > 1.0: y = np.where(y > KNEE, KNEE + (1 - KNEE) * np.tanh((y - KNEE) / (1 - KNEE)), y)
        _LUTS[key] = np.round(lin_to_code(y) * (n - 1)).astype(np.uint8 if bits == 8 else np.uint16)
        if len(_LUTS) > 400: _LUTS.pop(next(iter(_LUTS)))
    return _LUTS[key]


def apply(img, stops):
    """`img` with a gain of `stops` (uint8 or uint16 code values); the same object when the gain is nil."""
    if abs(float(stops)) < 0.01: return img
    if img.dtype == np.uint8: return lut(stops, 8)[img]
    if img.dtype == np.uint16: return lut(stops, 16)[img]
    raise TypeError(f'a picture of {img.dtype} cannot be graded')


class Gain:
    """The gain (stops) of one window at a time `t` seconds into it: `base + (match - base) * exp(-t / EASE_S)` plus the window's nudge."""
    def __init__(self, base, match=None, nudge=0.0, ease=EASE_S): self.base, self.match, self.nudge, self.ease = float(base), float(base if match is None else match), float(nudge), float(ease)
    def __call__(self, t): return self.base + (self.match - self.base) * math.exp(-max(float(t), 0.0) / self.ease) + self.nudge
    def __repr__(self): return f'Gain(base={self.base:.2f}, match={self.match:.2f}, nudge={self.nudge:.2f})'


def view_levels(grid, path, T, t0, heading=None, aspect=16 / 9, step=STEP_S):
    """(times from 0, log2 mean linear luma of the view) for a window of `T` seconds from clip second `t0` whose camera `path` is the dict the renderer takes (keyframes in degrees). A world-frame path looks where it says; a heading-relative one is turned by the clip's heading; a body-frame one (the views of you) shows the whole sphere's level, as its yaw has no fixed place in the grid."""
    from strata360.edit import view_quality as VQ
    kf = path['keyframes']; ts = [k['t'] for k in kf]; ref = path.get('ref', 'world'); hz = float(grid['hz']); luma = grid['luma']; out = []; times = np.arange(0.0, T + 1e-9, step)
    for x in times:
        i = int(np.clip(round((t0 + x) * hz), 0, len(luma) - 1)); fr = np.asarray(luma[i], np.float32) / 255.0
        if ref == 'body' or (ref == 'heading' and heading is None) or any(k.get('disc') is not None or abs(k.get('pitch', 0)) > 80 for k in kf[:1]): lin = float(code_to_lin(fr).mean())
        else:
            y, p, f = (float(np.interp(x, ts, [k.get(key, 0.0) for k in kf])) for key in ('yaw', 'pitch', 'fov'))
            if ref == 'heading': y += float(heading(t0 + x))
            r, c = VQ.cell_of(VQ.view_dirs(y, p, f, aspect)); lin = float(code_to_lin(fr[r, c]).mean())
        out.append(math.log2(max(lin, 1e-4)))
    return times, np.array(out)


def _wmean(vals, weights): return float(np.average(vals, weights=weights))


def plan_gains(folder, segs, framing, heading_of=None):
    """{segment id: Gain} for the footage windows of a plan (`framing` is edit/framing.resolve's {id: path}). A window of a clip with no quality grid, a generated clip, or a window without a camera path gets none (and breaks the chain). `heading_of(clip)` gives the clip's heading function (default: read from motion.json)."""
    from strata360.analysis import quality_grid as QG, views
    rd = config.race_dir(folder); grids = {}; levels = []; ids = []
    def grid(c):
        if c not in grids: grids[c] = QG.load(os.path.join(rd, 'clips', c))
        return grids[c]
    for g in segs:
        c, p = g.get('clip'), framing.get(g.get('id'))
        gr = None if g.get('synthetic') or not c or p is None else grid(c)
        if gr is None or 'luma' not in gr: levels.append(None); ids.append(g.get('id')); continue
        hd = heading_of(c) if heading_of else _heading(rd, c, views); ts, lv = view_levels(gr, p, float(g['dur_s']), float(g.get('clip_start_s') or 0.0), hd); levels.append((ts, lv)); ids.append(g.get('id'))
    med = [None if x is None else float(np.median(x[1])) for x in levels]; out = {}; prev_end = None; prev_gain = None
    for k, g in enumerate(segs):
        if levels[k] is None: prev_end = None; continue
        win = [(j, w) for j, w in zip(range(k - 2, k + 3), NEIGHBOUR_W) if 0 <= j < len(segs) and med[j] is not None]; s = _wmean([med[j] for j, _ in win], [w for _, w in win])
        dark = 2.0 ** med[k] < DARK_LIN; up = CAP_NIGHT_UP if dark else CAP_STOPS; base = float(np.clip(STRENGTH * (s - med[k]), -CAP_STOPS, up)); nudge = float(g.get('grade_ev') or 0.0)
        match = base
        if prev_end is not None:                                                                       # begin as bright as the previous window ended
            match = float(np.clip(prev_end - levels[k][1][0] - nudge, -CAP_STOPS, up))
        out[ids[k]] = Gain(base, match, nudge); end = out[ids[k]](float(g['dur_s'])); prev_end = float(levels[k][1][-1]) + end
    return out


def _heading(rd, clip, views):
    try: return views.heading_fn(os.path.join(rd, 'clips', clip), json.load(open(os.path.join(rd, 'clips', clip, 'clip.json')))['source_files']['osv'])
    except Exception: return lambda t: 0.0


def on(folder):
    """Is the exposure match on? race.json `grade.enabled` (default on); `STRATA_GRADE=0` switches it off."""
    if os.environ.get('STRATA_GRADE') == '0': return False
    try: return bool((config.load(folder).get('grade') or {}).get('enabled', True))
    except FileNotFoundError: return True


def gains_for(folder, segs, framing):
    """{segment id: Gain} for the plan, or {} when the grade is off."""
    return plan_gains(folder, segs, framing) if on(folder) else {}
