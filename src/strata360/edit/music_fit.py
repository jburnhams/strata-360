"""Fit, check and repair the built music (Milestone G5, docs/ai-music.md 4.7): the built track is held to the uploaded track's grid, to the film's length and to its sung moments, and a generated section that does not keep time is stretched, or sent back to be made again.

  to_mono(y, sr) -> samples at music.SR; envelope(y, sr) -> its rhythm (onsets, the low band doubled), FPS frames a second
  lag(ea, a0, eb, b0, n, reach) / bar_lags(...) -> how late a bar's rhythm is against the bar it should sound like, and how well they match
  grid_check(y, sr, marks, ref, ref_sr, ref_marks, beat_s) -> dict(ok, worst_ms, median_ms, off_bars, offsets_ms, judged)   every bar of the build lined up with its bar of the original
  tempo_fit(y, sr, n_bars, bar_s, ..., marks, ref, stretchable) -> (samples, dict(action, ratio, worst_ms))   a take lined up bar by bar with the audio it replaces: 'as is', 'stretched' (a drift up to 3%), 'repaint' (a bar more than 40 ms off) or 'regenerate' (the wrong tempo, or no beat that lines up)
  gain_match(x, ref) -> x scaled to the loudness of ref (a repainted part comes out 2 to 3 times louder than the bars around it)
  splice(y, sr, x, at_s, fade_s) -> y with x laid in from at_s, an equal-power crossfade from each end's downbeat into the section
  fit_length(y, sr, length_s, fade_s, fps) -> (samples, dict(ok, trimmed_s, padded_s))   the film's length to within a frame
  singing_db(x, vocals) -> the vocal stem separated from a generated take against the take, dB
  stale(old, new) -> the sections of `new` whose key no previous section had: the only ones to make again
  repair(items, generate, sr, tries, ...) -> [(samples | None, dict(ok, seed, takes))]   generate in batches, fit, and try the next seed while a take does not keep time
Timing is measured by lining up rhythms, not by comparing beat lists: on Legends the beat tracker locks onto off-beat hits in dense bars and chooses differently in the build and in the original (errors up to half a beat), while the rhythm of each built bar lines up with its bar of the original within 9 ms (7 Oct). `stretch` is injectable (ffmpeg atempo by default) so the rules are tested on synthetic clicks without ffmpeg."""
import subprocess
import numpy as np
from scipy.signal import resample_poly
from strata360.edit import music as MU

GRID_TOL_S = 0.04                      # a downbeat further than this from the grid is out
MAX_STRETCH = 0.03                     # a uniform tempo error up to this is fixed with a time-stretch
MIN_CORR = 0.3                         # a bar whose rhythm matches its reference less than this is not judged (silence, a fade, different material)
TRIES = 3                              # takes of one section before it is reported
FPS = MU.SR / MU.HOP


def to_mono(y, sr):
    x = np.asarray(y, np.float32); x = x.mean(1) if x.ndim > 1 else x
    if sr == MU.SR: return x
    g = np.gcd(int(sr), MU.SR); return resample_poly(x, MU.SR // g, int(sr) // g).astype(np.float32)


def envelope(y, sr):
    """The rhythm of y, FPS frames a second: onsets over all bands plus twice those under 200 Hz (kick and bass), less their local mean."""
    x = to_mono(y, sr)
    if len(x) < 2 * MU.N_FFT: return np.zeros(1, np.float32)
    e, low = MU.onset_envelope(MU.spectrogram(x)); e = e / max(float(e.max()), 5.0) + 2 * low / max(float(low.max()), 5.0); k = int(FPS)        # the floor: a held tone reads about 0.2, clicks 25, a rock track several hundred, so a track with no rhythm stays flat
    return np.maximum(e - np.convolve(e, np.ones(k) / k, 'same'), 0).astype(np.float32)


def pulse(n_frames, marks, beats_per_bar=4):
    """An ideal rhythm to judge against when there is no reference audio: a soft pulse on every beat between the marks, stronger on the downbeat."""
    e = np.zeros(n_frames, np.float32); t = np.arange(-3, 4); w = np.exp(-0.5 * (t / 1.5) ** 2); late = MU.N_FFT / 2 / MU.SR             # a frame is stamped at its start and hears the sound half a window later (as in music.beat_grid)
    for a, z in zip(marks[:-1], marks[1:]):
        for j in range(beats_per_bar):
            c = int(round((a + (z - a) * j / beats_per_bar - late) * FPS)) + t; ok = (c >= 0) & (c < n_frames); e[c[ok]] += (2.0 if j == 0 else 1.0) * w[ok]
    return e


def lag(ea, a0, eb, b0, n, reach):
    """How late (s) the rhythm of ea from frame a0 is against eb from frame b0, over n frames, searched within reach frames either way (parabolic peak), and how well they match at that lag (correlation)."""
    a = ea[max(0, a0):a0 + n]; n = len(a)                                                                   # the last bar may run past the end of the audio
    if n < 4 or not np.any(a): return 0.0, 0.0
    a = a - a.mean(); na = float(np.linalg.norm(a)); v = np.full(2 * reach + 1, -1.0)
    for i, d in enumerate(range(-reach, reach + 1)):
        if b0 - d < 0 or b0 - d + n > len(eb): continue
        b = eb[b0 - d:b0 - d + n] - eb[b0 - d:b0 - d + n].mean(); nb = float(np.linalg.norm(b))
        if na > 0 and nb > 0: v[i] = float(np.dot(a, b) / (na * nb))
    k = int(np.argmax(v)); den = v[k - 1] - 2 * v[k] + v[k + 1] if 0 < k < len(v) - 1 else 0.0
    f = k + (0.5 * (v[k - 1] - v[k + 1]) / den if den < 0 else 0.0); return (f - reach) / FPS, max(float(v[k]), 0.0)


def bar_lags(ey, marks, er, ref_marks, beat_s):
    """For each bar k of ey (from marks[k] to marks[k + 1]), its lag and match against er at ref_marks[k], searched within half a beat. The window starts a quarter beat early, so the bar's own downbeat is in it and the next bar's is not."""
    R = max(1, int(beat_s / 2 * FPS)); q = int(beat_s / 4 * FPS); P = R + q; tail = np.zeros(P + int(4 * beat_s * FPS), np.float32)
    ey = np.concatenate([np.zeros(P, np.float32), ey, tail]); er = np.concatenate([np.zeros(P, np.float32), er, tail]); out = []        # padded, so a bar at the very start or end can still be searched both ways
    for k in range(len(marks) - 1):
        n = int((marks[k + 1] - marks[k]) * FPS); out.append(lag(ey, int(round(marks[k] * FPS)) - q + P, er, int(round(ref_marks[k] * FPS)) - q + P, n, R))
    return out


def grid_check(y, sr, marks, ref=None, ref_sr=None, ref_marks=None, beat_s=0.6, tol_s=GRID_TOL_S, min_corr=MIN_CORR, end_s=None, skip=()):
    """Each bar of y (from marks[k]) against the bar it should sound like: ref (the original) from ref_marks[k], or with no ref an ideal pulse on the planned beats. The lag that best lines up their rhythm is the timing error; a bar whose rhythm matches too little (silence, a fade) is not judged, nor the bars in `skip` (new bars: their take was judged against the audio it replaced, and new material lines up with the original only loosely). Returns ok, the worst and median error of the bars judged, the bars off, the errors (None: not judged), how many were judged."""
    ey = envelope(y, sr); m = list(marks) + [end_s if end_s is not None else (marks[-1] + (marks[-1] - marks[-2] if len(marks) > 1 else 2.0))]
    m = [v for v in m if v * FPS < len(ey) - 4] + [min(m[-1], len(ey) / FPS)]; m = m if m[-1] > m[-2] else m[:-1]
    if len(m) < 2: return dict(ok=False, worst_ms=None, median_ms=None, off_bars=[], offsets_ms=[], judged=0)
    if ref is None: er, rm = pulse(len(ey), m), m[:-1]
    else: er, rm = envelope(ref, ref_sr or sr), list(ref_marks)
    res = bar_lags(ey, m, er, rm, beat_s); judged = [c >= min_corr and k not in skip for k, (_, c) in enumerate(res)]; err = [l * 1000 for l, _ in res]
    bad = [k for k, (e, j) in enumerate(zip(err, judged)) if j and abs(e) > tol_s * 1000]; e = np.abs([v for v, j in zip(err, judged) if j])
    return dict(ok=not bad and bool(e.size), worst_ms=round(float(e.max()), 1) if e.size else None, median_ms=round(float(np.median(e)), 1) if e.size else None, off_bars=bad, judged=int(sum(judged)),
                offsets_ms=[round(v, 1) if j else None for v, j in zip(err, judged)])


def atempo(y, sr, factor):
    """Play y `factor` times faster without changing its pitch (ffmpeg atempo; 0.97 to 1.03 is all G5 asks of it)."""
    x = np.asarray(y, np.float32); ch = 1 if x.ndim == 1 else x.shape[1]
    r = subprocess.run(['ffmpeg', '-v', 'error', '-f', 'f32le', '-ar', str(sr), '-ac', str(ch), '-i', '-', '-af', f'atempo={factor:.6f}', '-f', 'f32le', '-'], input=np.ascontiguousarray(x).tobytes(), capture_output=True)
    if r.returncode: raise RuntimeError('could not stretch: ' + r.stderr.decode(errors='ignore')[-200:])
    out = np.frombuffer(r.stdout, np.float32); return out if ch == 1 else out.reshape(-1, ch)


def _fix_len(x, n):
    x = np.asarray(x); return x[:n] if len(x) >= n else np.concatenate([x, np.zeros((n - len(x),) + x.shape[1:], x.dtype)])


def _judge(y, sr, m, er, beat, min_corr):
    res = bar_lags(envelope(y, sr), m, er, m[:-1], beat); ok = np.array([c >= min_corr for _, c in res]); lags = np.array([l for l, _ in res]); return lags, ok


def tempo_fit(y, sr, n_bars, bar_s, beats_per_bar=4, stretch=None, tol_s=GRID_TOL_S, max_stretch=MAX_STRETCH, marks=None, ref=None, stretchable=True, min_corr=MIN_CORR):
    """Fit a generated take to the grid. marks: the section's planned downbeats in seconds from the start of y, with its end (n_bars + 1 values; default every bar_s from 0). For a repaint y is the whole context the generator was given; only the bars between marks[0] and marks[-1] are judged and kept.
    ref: the audio the take replaces, on the same timeline (the built track's own bars): each bar of the take is lined up with the same bar of ref by its rhythm (grid_check's measure); with no ref, with an ideal pulse on the planned beats. A take whose rhythm matches in fewer than half its bars is made again (the wrong tempo, or no beat). The lags' drift over the bars is the tempo error: within max_stretch it is stretched away (stretchable: not a repaint, whose bars around are fixed), beyond it the take is made again. A bar still more than tol_s off means it is to be repainted. Returns (the section's samples, report)."""
    m = np.arange(n_bars + 1) * bar_s if marks is None else np.asarray(marks, float); beat = (m[-1] - m[0]) / n_bars / beats_per_bar; a = int(round(m[0] * sr)); n = int(round(m[-1] * sr)) - a
    er = envelope(ref, sr) if ref is not None else pulse(int(m[-1] * FPS) + 8, list(m), beats_per_bar); y = np.asarray(y); fail = 'regenerate' if stretchable else 'repaint'
    lags, ok = _judge(y, sr, m, er, beat, min_corr)
    if ok.sum() < max(1, (n_bars + 1) // 2): return _fix_len(y[a:], n), dict(action=fail, ratio=None, worst_ms=None, why='its beat does not line up with the track\'s')
    s = float(np.polyfit(m[:-1][ok] - m[0], lags[ok], 1)[0]) if ok.sum() >= 3 else 0.0                   # > 0: the take falls behind, it is slow
    if abs(s) > max_stretch: return _fix_len(y[a:], n), dict(action=fail, ratio=round(1 + s, 4), worst_ms=None, why=f'tempo {abs(s) * 100:.1f}% {"slow" if s > 0 else "fast"}')
    action = 'as is'
    if stretchable and abs(s) > 0.002:
        y = np.concatenate([y[:a], (stretch or atempo)(y[a:], sr, 1 + s)]); lags, ok = _judge(y, sr, m, er, beat, min_corr); action = 'stretched'
    worst = float(np.abs(lags[ok]).max()) if ok.any() else 0.0; out = _fix_len(y[a:], n); r = dict(action=action, ratio=round(1 + s, 4), worst_ms=round(worst * 1000, 1), judged=int(ok.sum()))
    if worst > tol_s: r.update(action='repaint', why=f'a downbeat {worst * 1000:.0f} ms off the grid')
    return out, r


def rms(x):
    x = np.asarray(x, np.float64); return float(np.sqrt(np.mean(x ** 2))) if x.size else 0.0


def gain_match(x, ref, limit=8.0):
    """x scaled so it is as loud (RMS) as ref, by at most `limit` either way."""
    a, r = rms(x), rms(ref)
    if a <= 0 or r <= 0: return np.asarray(x, np.float32)
    return (np.asarray(x, np.float32) * float(np.clip(r / a, 1 / limit, limit))).astype(np.float32)


def splice(y, sr, x, at_s, fade_s):
    """y with x laid in from at_s; both ends of x are downbeats of y. Each end is an equal-power crossfade of fade_s that starts on the downbeat and runs into the section, so the downbeat itself is the bar the listener already hears (on the grid) and the new bars take over within a beat. Returns a copy."""
    y = np.array(y, np.float32); x = np.asarray(x, np.float32); a = int(round(at_s * sr)); z = a + len(x)
    if a < 0 or z > len(y): raise ValueError('the section runs past the track')
    f = min(int(fade_s * sr), len(x) // 2); w = np.ones(len(x), np.float32)
    if f: ramp = np.sin(np.linspace(0, np.pi / 2, f)).astype(np.float32); w[:f] = ramp; w[len(x) - f:] = ramp[::-1]
    w2 = w if x.ndim == 1 else w[:, None]; keep = np.sqrt(np.clip(1 - w2 ** 2, 0, 1))
    y[a:z] = y[a:z] * keep + x * w2; return y


def fit_length(y, sr, length_s, fade_s=3.0, fps=25.0, quiet_db=-50.0):
    """The track cut or padded to the film's length. A cut that removes audible music (the track's own long ending runs past the film) fades out over the last fade_s; a track that ends early is padded with silence (the film's own sound carries the end, D7). Returns (samples, report)."""
    y = np.asarray(y, np.float32); n = int(round(length_s * sr)); trimmed = max(0, len(y) - n) / sr; padded = max(0, n - len(y)) / sr; faded = False
    if len(y) > n:
        cut = y[n:]; loud = rms(cut) > 0 and 20 * np.log10(rms(cut) / max(float(np.abs(y).max()), 1e-9)) > quiet_db; y = y[:n].copy()
        if loud and n:
            k = min(n, int(fade_s * sr)); env = (0.5 + 0.5 * np.cos(np.linspace(0, np.pi, k))).astype(np.float32); y[n - k:] *= env if y.ndim == 1 else env[:, None]; faded = True
    else: y = _fix_len(y, n)
    return y, dict(ok=abs(len(y) / sr - length_s) <= 1 / fps, length_s=round(len(y) / sr, 3), trimmed_s=round(trimmed, 3), padded_s=round(padded, 3), faded=faded)


def singing_db(x, vocals):
    """How loud the vocal stem separated from a generated take is against the take itself, in dB (-inf when silent): a generator that added a choir or a hum reads high."""
    a, v = rms(x), rms(vocals)
    return float('-inf') if a <= 0 or v <= 0 else round(float(20 * np.log10(v / a)), 1)


def stale(old, new):
    """The sections of `new` (score.plan sections) whose key no section of `old` had: what changed and must be made again. Moving the fidelity slider changes the key only where it changed the source or the strength."""
    keys = {s.get('key') for s in old or ()}; return [s for s in new if s.get('key') not in keys]


def repair(items, generate, sr, tries=TRIES, stretch=None, seeds=None, note=None):
    """Make generated sections that keep time, all together: generate(items, seeds) -> [samples at sr or None] (one batch, so a model loads once per round), then tempo_fit each; a take that is to be repainted or made again is tried again with the next seed, up to `tries` rounds. items: [(spec, inputs)], spec with first, end, bar_s, beats_per_bar. seeds: a first seed per item (default 0); a chosen take (spec 'take') is tried alone, once. note(spec, seed, report) records each take's verdict. Returns, per item, (samples or None when every take failed, report with each take's verdict)."""
    seeds = list(seeds or [s.get('take') or 0 for s, _ in items]); res = [None] * len(items); reps = [dict(ok=False, seed=None, takes=[]) for _ in items]; todo = list(range(len(items)))
    for k in range(tries):
        if not todo: break
        xs = generate([items[i] for i in todo], [seeds[i] + k for i in todo]); left = []
        for i, x in zip(todo, xs):
            s = items[i][0]; seed = seeds[i] + k
            if x is None: r = dict(action='failed', ratio=None, worst_ms=None, why='the generator made nothing'); y = None
            else: inp = items[i][1]; y, r = tempo_fit(x, sr, s['end'] - s['first'], s['bar_s'], s.get('beats_per_bar', 4), stretch, marks=inp.get('marks'), ref=inp.get('src'), stretchable=s.get('mode') != 'repaint')
            r['seed'] = seed; reps[i]['takes'].append(r)
            if note: note(s, seed, r)
            if r['action'] in ('as is', 'stretched'): res[i] = y; reps[i].update(ok=True, seed=seed)
            elif s.get('take') is None: left.append(i)
        todo = left
    return list(zip(res, reps))
