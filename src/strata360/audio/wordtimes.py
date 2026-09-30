"""Accurate word boundaries and safe cut points for editing (run with the project venv).

Whisper's own word times come from attention and are loose: words tile the audio with zero gap (word ends stretch over the pause that
follows), so they cannot be used as edit points. This module refines them:

  1. CTC forced alignment: a wav2vec2 character model gives 20 ms frame-level emissions; the known transcript is Viterbi-aligned to
     them, giving each word a start and end grounded in the acoustics (English: facebook/wav2vec2-base-960h; other languages need
     a language-specific model, see LANGUAGE_MODELS).
  2. Energy refinement: word ends are extended to where the speech energy actually falls away, starts to where it rises.
  3. Cut finder: for every gap between words, the quietest 5 ms hop (band-limited to speech) snapped to a zero crossing, with the
     margins and the energy drop relative to the neighbouring words, and a `safe` flag.

All times are clip-relative seconds, at millisecond resolution (edit points are then rounded to video frames by the caller).
"""
import re
import numpy as np

LANGUAGE_MODELS = {'en': 'facebook/wav2vec2-base-960h',
                   'fr': 'jonatasgrosman/wav2vec2-large-xlsr-53-french', 'nl': 'jonatasgrosman/wav2vec2-large-xlsr-53-dutch',
                   'de': 'jonatasgrosman/wav2vec2-large-xlsr-53-german'}
_M = {}
FRAME_S = 0.02                      # wav2vec2 stride: 320 samples at 16 kHz


def _load(lang):
    if lang not in _M:
        import torch
        from transformers import Wav2Vec2ForCTC, Wav2Vec2Processor
        name = LANGUAGE_MODELS[lang]
        _M[lang] = (Wav2Vec2Processor.from_pretrained(name), Wav2Vec2ForCTC.from_pretrained(name).eval())
    return _M[lang]


def emissions(x16, lang='en'):
    """Log-probabilities (frames, vocab) at 20 ms per frame for 16 kHz mono audio."""
    import torch
    proc, model = _load(lang)
    x = np.asarray(x16, np.float32); x = (x - x.mean()) / (x.std() + 1e-7)
    with torch.no_grad():
        return torch.log_softmax(model(torch.from_numpy(x)[None]).logits, dim=-1)[0].numpy()


def _norm_word(w, vocab):
    keep = ''.join(c for c in w.upper() if c in vocab and c not in ('|', '<pad>', '<s>', '</s>', '<unk>'))
    return keep


def force_align(x16, words, lang='en'):
    """Viterbi CTC alignment of `words` (list of strings) to the audio. Returns [(t0, t1, score)] per word (None when a word has no
    alignable characters, e.g. digits). Times in seconds from the start of x16."""
    proc, _ = _load(lang); vocab = proc.tokenizer.get_vocab(); blank = proc.tokenizer.pad_token_id; delim = vocab.get('|')
    em = emissions(x16, lang); T = em.shape[0]
    toks, owner = [], []
    for wi, w in enumerate(words):
        nw = _norm_word(w, vocab)
        if not nw: continue
        if toks and delim is not None: toks.append(delim); owner.append(-1)
        for c in nw: toks.append(vocab[c]); owner.append(wi)
    if not toks: return [None] * len(words)
    N = len(toks)
    trellis = np.full((T, N + 1), -np.inf); trellis[0, 0] = 0.0
    for t in range(1, T):
        trellis[t, 0] = trellis[t - 1, 0] + em[t, blank]
        stay = trellis[t - 1, 1:] + em[t, blank]; move = trellis[t - 1, :-1] + em[t, toks]
        trellis[t, 1:] = np.maximum(stay, move)
    # backtrack
    j, t = N, int(np.argmax(trellis[:, N]))
    path = []
    while j > 0 and t > 0:
        stay = trellis[t - 1, j] + em[t, blank]; move = trellis[t - 1, j - 1] + em[t, toks[j - 1]]
        if move >= stay: path.append((j - 1, t)); j -= 1
        t -= 1
    path.reverse()
    first, last, score = {}, {}, {}
    for tok_i, frame in path:
        w = owner[tok_i]
        if w < 0: continue
        first.setdefault(w, frame); last[w] = frame; score.setdefault(w, []).append(np.exp(em[frame, toks[tok_i]]))
    out = []
    for wi in range(len(words)):
        if wi in first: out.append((first[wi] * FRAME_S, (last[wi] + 1) * FRAME_S, float(np.mean(score[wi]))))
        else: out.append(None)
    return out


def energy_envelope(x, sr, hop_s=0.005, band=(100, 4000)):
    """RMS envelope (dBFS) in `hop_s` hops of the speech-band-filtered audio. Returns (times of hop centres, dB)."""
    from scipy import signal
    sos = signal.butter(4, band, 'bp', fs=sr, output='sos'); y = signal.sosfilt(sos, np.asarray(x, np.float64))
    h = int(hop_s * sr); n = len(y) // h
    e = np.sqrt(np.mean(y[:n * h].reshape(n, h) ** 2, axis=1) + 1e-14)
    return (np.arange(n) + 0.5) * hop_s, 20 * np.log10(e + 1e-9)


def refine_with_energy(words, x, sr, lo_db_below_peak=22.0, max_shift_s=0.12):
    """Snap each aligned word's start and end to the speech energy: the end moves to the last hop that is within `lo_db_below_peak` of
    the word's own peak (within max_shift_s of the aligned end), the start to the first such hop. Words stay ordered and non-overlapping."""
    t, e = energy_envelope(x, sr); out = []
    for w in words:
        if w is None: out.append(None); continue
        a, b, sc = w[:3]
        i0, i1 = np.searchsorted(t, a), np.searchsorted(t, b)
        if i1 <= i0 + 1: out.append(w); continue
        peak = e[i0:i1].max(); thr = peak - lo_db_below_peak
        lo = np.searchsorted(t, a - max_shift_s); hi = min(np.searchsorted(t, b + max_shift_s), len(e))
        active = np.where(e[lo:hi] >= thr)[0] + lo
        if len(active) == 0: out.append(w); continue
        na = max(t[active[0]] - 0.0025, a - max_shift_s); nb = min(t[active[-1]] + 0.0025, b + max_shift_s)
        out.append((float(min(na, nb)), float(max(na, nb)), sc))
    for k in range(1, len(out)):                                                           # keep order, no overlap
        if out[k] is not None and out[k - 1] is not None and out[k][0] < out[k - 1][1]:
            m = (out[k][0] + out[k - 1][1]) / 2; out[k - 1] = (out[k - 1][0], m, out[k - 1][2]); out[k] = (m, out[k][1], out[k][2])
    return out


def vad_probabilities(x16):
    """Speech probability per 32 ms window (Silero VAD bundled with faster-whisper). Returns (window centre times, probabilities)."""
    from faster_whisper.vad import get_vad_model
    n = 512; xp = np.pad(np.asarray(x16, np.float32), (0, (-len(x16)) % n))
    p = np.asarray(get_vad_model()(xp)).reshape(-1)
    return (np.arange(len(p)) + 0.5) * n / 16000, p


def cut_points(words, x, sr, pad_s=0.06, vad=None, pause_prob=0.35, min_pause_s=0.064, safe_drop_db=12.0, min_margin_s=0.015):
    """For each gap between consecutive words (gap i = between word i and i+1) find the best place to cut.
    With `vad` = (times, probabilities) the cut is placed inside the longest run of low speech probability that overlaps the gap
    (+- pad_s), at the quietest 5 ms hop of that run's inner half, snapped to a zero crossing, and `safe` means the run lasts at least
    min_pause_s (two VAD windows) with probability below pause_prob. Without VAD it falls back to energy only (noise fills pauses, so
    this is much less reliable). Words that touch (no pause) get safe=False.
    Returns per gap: dict(t, pause_s, vad_prob, drop_db, safe) or None."""
    t, e = energy_envelope(x, sr); out = []
    for i in range(len(words) - 1):
        a, b = words[i], words[i + 1]
        if a is None or b is None: out.append(None); continue
        lo, hi = min(a[1], b[0]) - pad_s, max(a[1], b[0]) + pad_s
        pause = None
        if vad is not None:
            vt, vp = vad; m = (vt >= lo) & (vt <= hi) & (vp < pause_prob)
            best = None; k = 0; idx = np.where(m)[0]
            while k < len(idx):                                   # longest contiguous low-probability run
                j = k
                while j + 1 < len(idx) and idx[j + 1] == idx[j] + 1: j += 1
                if best is None or j - k > best[1] - best[0]: best = (k, j)
                k = j + 1
            if best is not None:
                ta, tb = vt[idx[best[0]]] - 0.016, vt[idx[best[1]]] + 0.016; pause = (ta, tb)
        if pause is not None:
            span = pause[1] - pause[0]; w0, w1 = pause[0] + 0.25 * span, pause[1] - 0.25 * span
        else:
            w0, w1 = min(a[1], b[0]), max(a[1], b[0])
        i0, i1 = np.searchsorted(t, w0), max(np.searchsorted(t, w1), np.searchsorted(t, w0) + 1)
        k = i0 + int(np.argmin(e[i0:i1])); tc = float(t[min(k, len(t) - 1)])
        s0, s1 = int((tc - 0.003) * sr), int((tc + 0.003) * sr); w = np.asarray(x[max(s0, 0):s1], np.float64)
        zc = np.where(np.diff(np.signbit(w)))[0]
        if len(zc): tc = (max(s0, 0) + zc[np.argmin(np.abs(zc - len(w) / 2))]) / sr
        ia, ib = np.searchsorted(t, a[0]), max(np.searchsorted(t, a[1]), np.searchsorted(t, a[0]) + 1)
        ja, jb = np.searchsorted(t, b[0]), max(np.searchsorted(t, b[1]), np.searchsorted(t, b[0]) + 1)
        drop = float(min(np.median(e[ia:ib]), np.median(e[ja:jb])) - e[min(k, len(e) - 1)])
        vp_cut = float(np.interp(tc, vad[0], vad[1])) if vad is not None else None
        if vad is not None: safe = bool(pause is not None and (pause[1] - pause[0]) >= min_pause_s)
        else: safe = bool(drop >= safe_drop_db and (b[0] - a[1]) >= 0.04)
        out.append(dict(t=round(tc, 4), pause_s=round(pause[1] - pause[0], 3) if pause else 0.0, vad_prob=None if vp_cut is None else round(vp_cut, 2), drop_db=round(drop, 1), safe=safe))
    return out
