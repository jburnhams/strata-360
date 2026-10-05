"""Layering the stems to follow an intensity curve (Milestone G0b, docs/ai-music.md 4.4): per film bar, a gain for each of drums, bass, other and vocals; the re-sequenced stems summed under those gains, with the vocals let through only inside given windows.

  layer_gains(levels, phrase_bars) -> dict stem -> per-bar gain (vocals always 0)
  open_vocals(gains, windows) -> gains with vocals at 1 in the given bar windows [(first_bar, end_bar)]
  mix(stems, sr, downbeats, bars, gains) -> (samples, film downbeats)
  stray_vocal_db(vocals, sr, marks, windows) -> level of the vocal stem outside the windows, in dB below its level inside (or its own peak)"""
import numpy as np
from strata360.edit import remix

FLOORS = dict(other=0.55, bass=0.0, drums=0.0)      # `other` is never fully off; bass and drums come in as the level rises
ON = dict(bass=(0.15, 0.35), drums=(0.35, 0.6), other=(0.0, 0.3))      # level at which a stem starts to come in, and where it is fully in


def _ramp(v, lo, hi): return float(np.clip((v - lo) / max(hi - lo, 1e-9), 0, 1))


def layer_gains(levels, phrase_bars=4):
    """Per-bar gains from a 0..1 level per bar. The level is averaged over each phrase of phrase_bars so a stem only comes in or goes out on a phrase boundary."""
    lv = np.asarray(levels, float); q = lv.copy()
    for a in range(0, len(lv), phrase_bars): q[a:a + phrase_bars] = lv[a:a + phrase_bars].mean()
    g = {}
    for n, (lo, hi) in ON.items(): g[n] = np.array([FLOORS[n] + (1 - FLOORS[n]) * _ramp(v, lo, hi) for v in q])
    g['vocals'] = np.zeros(len(lv)); return g


def open_vocals(gains, windows):
    g = {n: np.array(v, float) for n, v in gains.items()}
    for a, b in windows: g['vocals'][max(0, a):max(0, b)] = 1.0
    return g


def _envelope(per_bar, marks, n, sr, ramp_s):
    """Per-sample gain: each bar's gain from its start, changing linearly over ramp_s centred on the bar line."""
    env = np.empty(n, np.float32); edges = [int(round(m * sr)) for m in marks] + [n]; h = int(ramp_s * sr / 2)
    for i, g in enumerate(per_bar): env[edges[i]:edges[i + 1]] = g
    for i in range(1, len(per_bar)):
        if per_bar[i] != per_bar[i - 1] and h:
            a = max(0, edges[i] - h); b = min(n, edges[i] + h); env[a:b] = np.linspace(per_bar[i - 1], per_bar[i], b - a)
    return env


def mix(stems, sr, downbeats, bars, gains, fade_s=0.08, ramp_s=0.25, end_s=None):
    """Every stem re-sequenced the same way (remix.render), multiplied by its per-bar gain (len = len(bars)) and summed. Returns (samples, film downbeats)."""
    out = None; marks = None
    for n, x in stems.items():
        y, marks = remix.render(x, sr, downbeats, bars, fade_s=fade_s, end_s=end_s); g = gains.get(n)
        if g is None or not np.any(g): continue
        y = y * _envelope(np.asarray(g, float), marks, len(y), sr, ramp_s)[:, None]; out = y if out is None else out + y
    if marks is None: raise ValueError('no stems')
    return (out if out is not None else np.zeros_like(y)), marks


def stray_vocal_db(vocals, sr, marks, windows, total_s=None):
    """How loud the vocal stem is outside the windows [(first_bar, end_bar)], in dB below its loudest bar (-inf when silent). The check that no singing leaks through."""
    v = np.asarray(vocals, np.float64); v = v.mean(1) if v.ndim > 1 else v; edges = [int(round(m * sr)) for m in marks] + [len(v)]; keep = np.ones(len(marks), bool)
    for a, b in windows: keep[max(0, a):max(0, b)] = False
    rms = np.array([np.sqrt(np.mean(v[edges[i]:edges[i + 1]] ** 2)) if edges[i + 1] > edges[i] else 0.0 for i in range(len(marks))]); top = rms.max() if rms.size else 0.0
    if top <= 0 or not keep.any(): return float('-inf')
    outside = rms[keep].max(); return float('-inf') if outside <= 0 else round(float(20 * np.log10(outside / top)), 1)
