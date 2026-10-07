"""Layering the stems to follow an intensity curve (Milestone G0b, docs/ai-music.md 4.4): per film bar, a gain for each of drums, bass, other and vocals; the re-sequenced stems summed under those gains, with the vocals let through only inside given windows.

  layer_gains(levels, phrase_bars) -> dict stem -> per-bar gain (vocals always 0)
  snap_windows(windows, bars, downbeats, spans) -> (windows grown to whole sung stretches, [what was dropped and why])
  open_vocals(gains, windows) -> gains with vocals at 1 in the given bar windows [(first_bar, end_bar)]
  mix(stems, sr, downbeats, bars, gains) -> (samples, film downbeats)
  stray_vocal_db(vocals, sr, marks, windows) -> level of the vocal stem outside the windows, in dB below its level inside (or its own peak)"""
import numpy as np
from strata360.edit import remix

FLOORS = dict(other=0.8, bass=0.5, drums=0.3)       # quiet is a softer band, not a stripped one: separated `other` alone sounds thin and processed (heard on Legends), so every stem stays in and rises with the level
MASTER = (0.65, 1.0)                                  # the whole mix at level 0 and level 1: quiet is also a few dB lower
ON = dict(bass=(0.15, 0.35), drums=(0.35, 0.6), other=(0.0, 0.3))      # level at which a stem starts to come in, and where it is fully in


def _ramp(v, lo, hi): return float(np.clip((v - lo) / max(hi - lo, 1e-9), 0, 1))


def layer_gains(levels, phrase_bars=4):
    """Per-bar gains from a 0..1 level per bar. The level is averaged over each phrase of phrase_bars so a stem only comes in or goes out on a phrase boundary."""
    lv = np.asarray(levels, float); q = lv.copy()
    for a in range(0, len(lv), phrase_bars): q[a:a + phrase_bars] = lv[a:a + phrase_bars].mean()
    g = {}
    for n, (lo, hi) in ON.items(): g[n] = np.array([FLOORS[n] + (1 - FLOORS[n]) * _ramp(v, lo, hi) for v in q])
    for n in ON: g[n] = g[n] * (MASTER[0] + (MASTER[1] - MASTER[0]) * np.clip(q, 0, 1))
    g['vocals'] = np.zeros(len(lv)); return g


def _bar_of(downbeats, t, end=False):
    """The track's bar holding second t (for the end of a span: the bar holding its last instant)."""
    i = int(np.searchsorted(downbeats, t - 1e-6 if end else t, 'right') - 1); return int(np.clip(i, 0, len(downbeats) - 2))


def stretches_touched(windows, bars, downbeats, spans):
    """The sung stretches the windows touch, as source bar ranges [(first, last)] inclusive: what remix.plan should hold whole."""
    d = np.asarray(downbeats, float); out = set()
    for a, b in windows:
        for t0, t1 in spans:
            s0, s1 = _bar_of(d, t0), _bar_of(d, t1, end=True)
            if any(s0 <= bars[f] <= s1 for f in range(max(0, a), min(len(bars), b))): out.add((s0, s1))
    return sorted(out)


def merge_windows(windows):
    out = []
    for w in sorted((int(a), int(b)) for a, b in windows):
        if out and w[0] <= out[-1][1]: out[-1] = (out[-1][0], max(out[-1][1], w[1]))
        else: out.append(w)
    return out


def snap_windows(windows, bars, downbeats, spans):
    """Grow each vocal window [(first, end)] in film bars until it holds every sung stretch of the original it touches whole, so a verse is never cut mid-line. `bars` is the re-sequencing (source bar per film bar), `spans` [(t0, t1)] where the original is sung (lyrics.view's vocal_spans, in the track's seconds). A stretch is whole only if the film plays all its source bars in one unbroken run; if it does not (a join falls inside it) the window is returned in `dropped` for the caller to hold the stretch whole or keep the window as asked. Overlapping windows are merged. Returns (windows, dropped=[{window, why}])."""
    d = np.asarray(downbeats, float); out = []; dropped = []
    for a, b in windows:
        a = max(0, int(a)); b = min(len(bars), int(b))
        if b <= a: continue
        lo, hi = a, b; ok = True
        for _ in range(len(spans) + 1):                                                    # growing may touch another stretch
            grew = False
            for t0, t1 in spans:
                s0, s1 = _bar_of(d, t0), _bar_of(d, t1, end=True)
                if not any(s0 <= bars[f] <= s1 for f in range(lo, hi)): continue
                f0 = next((f for f in range(lo, hi) if s0 <= bars[f] <= s1), lo); first = f0 - (bars[f0] - s0); last = first + (s1 - s0)
                if first < 0 or last >= len(bars) or any(bars[f] != s0 + (f - first) for f in range(first, last + 1)): ok = False; break
                if first < lo or last + 1 > hi: lo, hi = min(lo, first), max(hi, last + 1); grew = True
            if not ok or not grew: break
        if ok: out.append((lo, hi))
        else: dropped.append(dict(window=(a, b), why='a sung stretch inside it is not played in one piece'))
    return merge_windows(out), dropped


VOCAL_RAMP_S = 0.06                                   # the vocal stem's gain changes quickly and a fall ends on the bar line, so the singing stays inside its window
AS_IS_TOL = 0.2                                       # a source bar this much louder than the level, or quieter, is played as it is


def as_is_bars(levels, bars, energy, tol=AS_IS_TOL):
    """Film bars whose source bar is already as quiet as the level asks (its own energy within `tol` above the level): the track's own quiet stretches, played untouched rather than made by turning stems down. Returns a bool per film bar."""
    lv = np.asarray(levels, float); e = np.asarray(energy, float); return np.array([e[b] <= lv[k] + tol for k, b in enumerate(bars)])


def keep_as_is(gains, mask):
    """gains with every instrument stem at full on the film bars in mask."""
    g = {n: np.array(v, float) for n, v in gains.items()}
    for n in ON: g[n][mask] = 1.0
    return g


def open_vocals(gains, windows):
    g = {n: np.array(v, float) for n, v in gains.items()}
    for a, b in windows: g['vocals'][max(0, a):max(0, b)] = 1.0
    return g


def _envelope(per_bar, marks, n, sr, ramp_s, down_inside=False):
    """Per-sample gain: each bar's gain from its start, changing linearly over ramp_s centred on the bar line. With down_inside a fall ends on the bar line instead (the vocal stem: nothing of it may reach the bar after its window)."""
    env = np.empty(n, np.float32); edges = [int(round(m * sr)) for m in marks] + [n]; h = int(ramp_s * sr / 2)
    for i, g in enumerate(per_bar): env[edges[i]:edges[i + 1]] = g
    for i in range(1, len(per_bar)):
        if per_bar[i] != per_bar[i - 1] and h:
            a = max(0, edges[i] - h); b = min(n, edges[i] + h)
            if down_inside and per_bar[i] < per_bar[i - 1]: a = max(0, edges[i] - 2 * h); b = edges[i]
            env[a:b] = np.linspace(per_bar[i - 1], per_bar[i], b - a)
    return env


def mix(stems, sr, downbeats, bars, gains, fade_s=0.08, ramp_s=0.25, end_s=None):
    """Every stem re-sequenced the same way (remix.render), multiplied by its per-bar gain (len = len(bars)) and summed. Returns (samples, film downbeats)."""
    out = None; marks = None
    for n, x in stems.items():
        y, marks = remix.render(x, sr, downbeats, bars, fade_s=fade_s, end_s=end_s); g = gains.get(n)
        if g is None or not np.any(g): continue
        vocal = n == 'vocals'; y = y * _envelope(np.asarray(g, float), marks, len(y), sr, VOCAL_RAMP_S if vocal else ramp_s, down_inside=vocal)[:, None]; out = y if out is None else out + y
    if marks is None: raise ValueError('no stems')
    return (out if out is not None else np.zeros_like(y)), marks


def stray_vocal_db(vocals, sr, marks, windows, total_s=None):
    """How loud the vocal stem is outside the windows [(first_bar, end_bar)], in dB below its loudest bar (-inf when silent). The check that no singing leaks through."""
    v = np.asarray(vocals, np.float64); v = v.mean(1) if v.ndim > 1 else v; edges = [int(round(m * sr)) for m in marks] + [len(v)]; keep = np.ones(len(marks), bool)
    for a, b in windows: keep[max(0, a):max(0, b)] = False
    rms = np.array([np.sqrt(np.mean(v[edges[i]:edges[i + 1]] ** 2)) if edges[i + 1] > edges[i] else 0.0 for i in range(len(marks))]); top = rms.max() if rms.size else 0.0
    if top <= 0 or not keep.any(): return float('-inf')
    outside = rms[keep].max(); return float('-inf') if outside <= 0 else round(float(20 * np.log10(outside / top)), 1)
