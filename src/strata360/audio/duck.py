"""Turning the music down under speech (implementation plan A3), as a gain curve worked out in numpy so the result is exact and testable.

  speech_spans(x, sr)                        -> [(a, b)] seconds where a mono recording is speaking (a voice-over track)
  envelope(n, sr, spans, depth_db, ...)       -> (n,) linear gain: 1 away from the spans, `depth_db` below inside them
  combine(*curves)                            -> the lowest of several envelopes (a curve per reason to duck)

A span ducks the music from `attack_s` BEFORE it starts (the music is already down when the voice comes in, so the first syllable is never covered) to `release_s` after it ends, linearly in dB. Several spans overlap by taking the deepest."""
import numpy as np


def speech_spans(x, sr, thresh_db=-45.0, frame_s=0.02, min_gap_s=0.35, min_len_s=0.15, pad_s=0.05):
    """Where a mono recording speaks: frames whose RMS is above `thresh_db` (dBFS), gaps under `min_gap_s` bridged (a pause between words is not the end of a line), runs under `min_len_s` dropped (a click), each run padded by `pad_s`."""
    x = np.asarray(x, np.float32); n = max(int(frame_s * sr), 1); m = len(x) // n
    if m == 0: return []
    rms = np.sqrt(np.mean(x[: m * n].reshape(m, n) ** 2, axis=1)); on = 20 * np.log10(np.maximum(rms, 1e-9)) > thresh_db; idx = np.flatnonzero(on)
    if not len(idx): return []
    runs = [(int(g[0]), int(g[-1]) + 1) for g in np.split(idx, np.flatnonzero(np.diff(idx) > min_gap_s / frame_s) + 1)]
    return [(max(a * frame_s - pad_s, 0.0), b * frame_s + pad_s) for a, b in runs if (b - a) * frame_s >= min_len_s]


def envelope(n, sr, spans, depth_db, attack_s=0.08, release_s=0.5):
    """(n,) linear gain: 1.0 outside, `depth_db` (negative) inside each of `spans` [(a, b)] seconds, ramping down over the `attack_s` before a span and back up over the `release_s` after it (linear in dB, the deepest wins where spans overlap)."""
    db = np.zeros(int(n), np.float32); depth = abs(float(depth_db))
    for a, b in spans:
        lo, hi = int(max(a - attack_s, 0.0) * sr), min(int((b + release_s) * sr) + 1, len(db))
        if hi <= lo: continue
        t = np.arange(lo, hi) / sr; c = np.clip((t - (a - attack_s)) / max(attack_s, 1e-6), 0.0, 1.0) * np.clip(((b + release_s) - t) / max(release_s, 1e-6), 0.0, 1.0)
        c = np.where((t >= a) & (t <= b), 1.0, c); db[lo:hi] = np.maximum(db[lo:hi], c * depth)
    return (10.0 ** (-db / 20.0)).astype(np.float32)


def combine(*curves):
    out = curves[0].copy()
    for c in curves[1:]: np.minimum(out, c, out=out)
    return out
