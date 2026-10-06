"""The intensity curve of the film (Milestone G1, docs/ai-music.md 4.1): one value 0..1 per bar of film time, from signals the project already has, so the music can be sparse on the long grind and full at the start, the finish, the crowds and the hard climbs.

curve(n_bars, bar_s, signals, marks, speech) -> dict(levels=[per bar], phrases=[per phrase], phrase_bars)
  signals  list of dict(t=[film seconds], v=[values], weight=1.0): any series (motion, pace, slope, crowd energy, technique energy ...), each scaled to its own 5th..95th percentile and averaged by weight
  marks    list of (film seconds, level 0..1, span_s) for story weight: the start, the finish, a moment the director marks
  speech   list of (film t0, t1): the music is sparser under speech, by SPEECH_DUCK
The result is smoothed, averaged over each phrase and quantised to LEVELS with hysteresis, so it changes only on phrase boundaries and does not flicker. Gathering the signals from a project (audio_events, motion, series, scenes, techniques) is the caller's job: this module is pure."""
import numpy as np

LEVELS = (0.15, 0.4, 0.65, 0.9)                   # sparse, steady, driving, full
SPEECH_DUCK = 0.6                                  # a bar of speech keeps this share of its level
HYSTERESIS = 0.08                                  # a phrase must pass a level boundary by this much to change level
SMOOTH_BARS = 2


def _scaled(v):
    v = np.asarray(v, float); lo, hi = np.percentile(v, 5), np.percentile(v, 95); return np.clip((v - lo) / (hi - lo), 0, 1) if hi - lo > 1e-9 else np.zeros_like(v)


def signal_bars(n_bars, bar_s, signals):
    """Each signal as a 0..1 value per bar: [(name, weight, array)]. Points with no value (NaN) are dropped first; a signal with fewer than two points is skipped."""
    centres = (np.arange(n_bars) + 0.5) * bar_s; out = []
    for i, s in enumerate(signals):
        t = np.asarray(s['t'], float); v = np.asarray(s['v'], float); ok = np.isfinite(t) & np.isfinite(v)
        if ok.sum() < 2: continue
        out.append((s.get('name', f'signal {i + 1}'), float(s.get('weight', 1.0)), np.interp(centres, t[ok], _scaled(v[ok]))))
    return out


def curve(n_bars, bar_s, signals=(), marks=(), speech=(), phrase_bars=4, smooth_bars=SMOOTH_BARS, hysteresis=HYSTERESIS):
    centres = (np.arange(n_bars) + 0.5) * bar_s; acc = np.zeros(n_bars); wsum = 0.0
    for _, w, a in signal_bars(n_bars, bar_s, signals): acc += w * a; wsum += w
    base = acc / wsum if wsum else np.full(n_bars, 0.5)
    if smooth_bars > 1: k = np.ones(smooth_bars) / smooth_bars; base = np.convolve(np.pad(base, (smooth_bars, smooth_bars), mode='edge'), k, 'same')[smooth_bars:-smooth_bars]
    for a, b in speech: base[(centres >= a) & (centres < b)] *= SPEECH_DUCK
    n_ph = -(-n_bars // phrase_bars); ph = np.array([base[i * phrase_bars:(i + 1) * phrase_bars].mean() for i in range(n_ph)])
    for t, lv, span in marks:                                                                           # story weight: raises the phrases it touches, after the averaging so one bar is enough
        for i in range(n_ph):
            a, b = i * phrase_bars * bar_s, min((i + 1) * phrase_bars, n_bars) * bar_s
            if a - span <= t <= b + span: ph[i] = max(ph[i], lv)
    edges = [(LEVELS[i] + LEVELS[i + 1]) / 2 for i in range(len(LEVELS) - 1)]; cur = 0; out = []
    for v in ph:
        if len(out) == 0: cur = int(sum(v > e for e in edges))
        else:
            while cur < len(edges) and v > edges[cur] + hysteresis: cur += 1
            while cur > 0 and v < edges[cur - 1] - hysteresis: cur -= 1
        out.append(LEVELS[cur])
    levels = [lv for lv in out for _ in range(phrase_bars)][:n_bars]
    return dict(levels=[round(float(v), 3) for v in levels], phrases=[float(v) for v in out], phrase_bars=phrase_bars)
