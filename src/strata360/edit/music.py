"""Music for the film: tempo, beat grid, downbeats and energy sections of a track the user supplies, found locally (numpy/scipy; ffmpeg decodes). The planner then cuts on the beat and follows the music's
energy (quiet intro, louder middle), and the film's sound mixes the track in from its first downbeat.

analyse(path) -> dict(bpm, offset_s, bar_beats, duration_s, usable_beats, sections=[(start_beat, end_beat, energy 0..1)], confidence, ...)
  offset_s   where the first downbeat is in the track: the track is played from there, so film time 0 is a downbeat
  sections   energy per stretch of whole bars, from the loudness of each bar, merged when similar
The tempo is assumed constant (most dance and pop tracks); a track with tempo changes is reported with low confidence.

The project's track is recorded in <race dir>/music.json: {version, file (relative to the race dir), name (as uploaded), sig, analysis, waveform (peaks 0..1), spectrogram (file under music/)}.
store() saves an upload; info() reads the record and redoes the analysis only when the file or the format changed."""
import json, os, subprocess, time
import numpy as np

VERSION = 2; PEAKS = 1000; SPEC_BANDS = 96; SPEC_COLS = 1600

SR = 22050; N_FFT = 1024; HOP = 256


def decode(path, sr=SR):
    r = subprocess.run(['ffmpeg', '-v', 'error', '-i', path, '-vn', '-ac', '1', '-ar', str(sr), '-f', 'f32le', '-'], capture_output=True)
    if r.returncode or not r.stdout: raise RuntimeError('could not read the audio: ' + r.stderr.decode(errors='ignore')[-200:])
    return np.frombuffer(r.stdout, np.float32)


def spectrogram(x):
    n = 1 + (len(x) - N_FFT) // HOP; w = np.hanning(N_FFT).astype(np.float32); idx = np.arange(N_FFT)[None, :] + HOP * np.arange(n)[:, None]
    return np.abs(np.fft.rfft(x[idx] * w, axis=1)).astype(np.float32)


def onset_envelope(S):
    L = np.log1p(10.0 * S); d = np.maximum(L[1:] - L[:-1], 0); env = np.concatenate([[0.0], d.sum(1)]); low = np.concatenate([[0.0], d[:, :int(200 / (SR / N_FFT))].sum(1)])
    k = np.ones(3) / 3; return np.convolve(env, k, 'same'), np.convolve(low, k, 'same')


def tempo_and_phase(env, fps, lo=70.0, hi=180.0):
    """Best (bpm, phase in frames) of a constant-tempo grid: each candidate tempo folds the onset envelope onto one beat period; the sharper the fold, the better the grid."""
    env = env - np.convolve(env, np.ones(int(fps * 1.5)) / int(fps * 1.5), 'same'); env = np.maximum(env, 0); t = np.arange(len(env)); best = (-1, 0, 0)
    for bpm in np.arange(lo, hi, 0.05):
        P = fps * 60.0 / bpm; ph = (t % P) / P; bins = 48; h = np.bincount((ph * bins).astype(int) % bins, weights=env, minlength=bins) / (np.bincount((ph * bins).astype(int) % bins, minlength=bins) + 1e-9)
        h = np.convolve(np.concatenate([h[-2:], h, h[:2]]), np.ones(3) / 3, 'valid')[:bins] if len(h) > 4 else h; score = (h.max() - h.mean()) / (h.mean() + 1e-9) * (1.0 + 0.15 * np.exp(-0.5 * (np.log(bpm / 120.0) / 0.35) ** 2))   # a mild preference for tempos around 120
        if score > best[0]: best = (score, bpm, int(np.argmax(h)) / bins * P)
    return best[1], best[2], best[0]


def analyse(path, bar_beats=4):
    return analyse_samples(decode(path), bar_beats)


def analyse_samples(x, bar_beats=4, S=None):
    fps = SR / HOP; S = spectrogram(x) if S is None else S; env, low = onset_envelope(S); bpm, phase, score = tempo_and_phase(env, fps); period = fps * 60.0 / bpm
    beats = np.arange(phase, len(env) - 1, period); idx = np.round(beats).astype(int); lowb = np.array([low[i] for i in idx])
    sums = [lowb[k::bar_beats].sum() for k in range(bar_beats)]; bar0 = int(np.argmax(sums)); first = beats[bar0]                            # the bar line: the beat phase with the most low-frequency attack
    rms = np.sqrt(np.convolve(x.astype(np.float64) ** 2, np.ones(SR // 10) / (SR // 10), 'same')); bar_s = 60.0 / bpm * bar_beats; t0 = first / fps; nb = int((len(x) / SR - t0) // bar_s)
    if nb < 2: raise RuntimeError('the track is too short')
    e = np.array([rms[int((t0 + i * bar_s) * SR):int((t0 + (i + 1) * bar_s) * SR)].mean() for i in range(nb)]); lo_, hi_ = np.percentile(e, 10), np.percentile(e, 95); en = np.clip((e - lo_) / max(hi_ - lo_, 1e-9), 0, 1)
    sections = []
    for i, v in enumerate(en):
        if sections and abs(sections[-1][2] - v) < 0.15 and i - sections[-1][3] < 8: s = sections[-1]; sections[-1] = (s[0], (i + 1) * bar_beats, (s[2] * (i - s[3]) + v) / (i - s[3] + 1), s[3])
        else: sections.append((i * bar_beats, (i + 1) * bar_beats, float(v), i))
    sections = [(a, b, round(float(v), 3)) for a, b, v, _ in sections]
    return dict(bpm=round(float(bpm), 2), offset_s=round(float(t0), 3), bar_beats=bar_beats, duration_s=round(len(x) / SR, 2), usable_beats=nb * bar_beats, sections=sections, confidence=round(float(min(score / 6.0, 1.0)), 2))


def track_beats(env, fps, bpm, tight=100.0):
    """Every beat of a track that may drift, in seconds (Ellis dynamic programming): the best chain of onset peaks whose spacing stays near the beat period of `bpm`. `tight` is how hard a spacing that differs from the period is punished."""
    env = np.maximum(env - np.convolve(env, np.ones(int(fps * 1.5)) / int(fps * 1.5), 'same'), 0); env = env / max(float(env.max()), 1e-9); P = fps * 60.0 / bpm
    lo, hi = max(1, int(round(P / 2))), int(round(2 * P)); n = len(env); score = env.copy(); back = np.full(n, -1)
    lags = np.arange(lo, hi + 1); pen = -tight * np.log(lags / P) ** 2 * 0.01
    for t in range(n):
        prev = t - lags; ok = prev >= 0
        if not ok.any(): continue
        c = score[prev[ok]] + pen[ok]; k = int(np.argmax(c)); score[t] = env[t] + c[k]; back[t] = prev[ok][k]
    t = int(np.argmax(score[max(0, n - int(P)):]) + max(0, n - int(P))); chain = [t]
    while back[t] >= 0: t = back[t]; chain.append(t)
    chain = chain[::-1]
    while chain and env[chain[0]] < 0.2: chain.pop(0)                                                  # the chain starts and ends on real onsets, not on silence
    while chain and env[chain[-1]] < 0.2: chain.pop()
    return np.array(chain, float) / fps


def refine_beats(beats, env, fps, radius=0.03):
    """Move each beat to the highest onset within `radius` seconds."""
    r = max(1, int(radius * fps)); out = []
    for b in beats:
        i = int(round(b * fps)); a = max(0, i - r); z = min(len(env), i + r + 1); out.append((a + int(np.argmax(env[a:z]))) / fps if z > a else b)
    return np.array(out)


def regularise(beats, reach=(3, 6, 9), tol=0.04):
    """Pull stray beats back onto the tempo around them. The tracker follows onsets, so in a dense stretch it can land a beat on an off-beat hit (up to a fraction of a beat early or late). Each beat is predicted from the beats on both sides of it (the midpoint of the pair m beats before and after, m up to `reach`, median of the predictions: exact for a steady drift, and a stray neighbour is outvoted); a beat further than `tol` seconds from its prediction is moved onto it. Several passes with a wider reach mend a run of stray beats. The first and last beats are left as they are."""
    b = np.array(beats, float)
    for r in reach:
        out = b.copy()
        for k in range(1, len(b) - 1):
            m = min(r, k, len(b) - 1 - k); pred = float(np.median([(b[k - j] + b[k + j]) / 2 for j in range(1, m + 1)]))
            if abs(b[k] - pred) > tol: out[k] = pred
        b = out
    return b


def _extend(beats, dur, n_local):
    """The beats carried back to the start and on to the end of the track at the local beat period (the tracker only reports beats it heard, and a quiet first or last bar has none)."""
    head = float(np.median(np.diff(beats[:n_local + 1]))); tail = float(np.median(np.diff(beats[-n_local - 1:]))); a = []; t = beats[0] - head
    while t >= -0.005: a.append(t); t -= head
    z = []; t = beats[-1] + tail
    while t <= dur + 0.01: z.append(t); t += tail
    return np.concatenate([a[::-1], beats, z])


def beat_grid(x, bar_beats=4, S=None):
    """The actual beats and downbeats of a track, in seconds, allowing the tempo to wander: dict(bpm, beats, downbeats, bar_beats). The first downbeat is the beat phase with the most low-frequency attack."""
    fps = SR / HOP; S = spectrogram(x) if S is None else S; env, low = onset_envelope(S); bpm, _, _ = tempo_and_phase(env, fps)
    beats = regularise(refine_beats(track_beats(env, fps, bpm), env, fps)) + N_FFT / 2 / SR                         # a spectrogram frame is stamped at its start; the sound it hears is centred half a window later
    if len(beats) < 2 * bar_beats: raise RuntimeError('the track is too short')
    beats = _extend(beats, len(x) / SR, bar_beats)
    idx = np.round(beats * fps).astype(int).clip(0, len(low) - 1); sums = [low[idx[k::bar_beats]].sum() for k in range(bar_beats)]; k0 = int(np.argmax(sums))
    return dict(bpm=round(float(bpm), 2), bar_beats=bar_beats, beats=[round(float(b), 4) for b in beats], downbeats=[round(float(b), 4) for b in beats[k0::bar_beats]])


MAJOR = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
MINOR = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])
NOTES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']


def chroma(S, sr=SR, lo=55.0, hi=2000.0):
    """Pitch-class energy (frames x 12) from a magnitude spectrogram: each FFT bin between lo and hi hertz goes to its nearest semitone class."""
    f = np.fft.rfftfreq(N_FFT, 1.0 / sr); m = (f >= lo) & (f <= hi); pc = (np.round(12 * np.log2(f[m] / 440.0)).astype(int) + 9) % 12; C = np.zeros((S.shape[0], 12), np.float32)
    for k in range(12): C[:, k] = S[:, m][:, pc == k].sum(1)
    return C


def estimate_key(C):
    """(tonic 0..11 with 0 = C, 'major' or 'minor', name such as 'A minor', confidence 0..1) of a chroma matrix, by correlation with the Krumhansl-Kessler profiles."""
    v = C.sum(0).astype(np.float64); best = (-2.0, 0, 'major'); second = -2.0
    for mode, prof in (('major', MAJOR), ('minor', MINOR)):
        for t in range(12):
            r = float(np.corrcoef(v, np.roll(prof, t))[0, 1])
            if r > best[0]: second = max(second, best[0]); best = (r, t, mode)
            else: second = max(second, r)
    return best[1], best[2], f'{NOTES[best[1]]} {best[2]}', round(float(np.clip((best[0] - second) * 4, 0, 1)), 2)


def bar_features(x, downbeats, S=None, bands=8):
    """One feature vector per bar (the bars between consecutive downbeats): its chroma (12) and its energy in `bands` log-spaced frequency bands. Each part has the track's average bar taken off and is then scaled to unit length, so a dot product is a similarity that separates bars of one track (raw chroma and band energies are all positive, and every bar of a real track then looks 0.95 like every other). Returns (bars x (12 + bands)) array."""
    S = spectrogram(x) if S is None else S; C = chroma(S); f = np.fft.rfftfreq(N_FFT, 1.0 / SR); edges = np.geomspace(60.0, 8000.0, bands + 1); fps = SR / HOP; rc = []; rt = []; masks = [(f >= lo) & (f < hi) for lo, hi in zip(edges[:-1], edges[1:])]
    for a, b in zip(downbeats[:-1], downbeats[1:]):
        i = min(int(round(a * fps)), len(C) - 1); j = min(max(int(round(b * fps)), i + 1), len(C)); rc.append(np.log1p(C[i:j].mean(0))); rt.append(np.array([np.log1p(S[i:j][:, m].mean()) if m.any() else 0.0 for m in masks]))
    unit = lambda M: (lambda D: D / np.maximum(np.linalg.norm(D, axis=1, keepdims=True), 1e-9))(np.array(M) - np.mean(M, axis=0))
    return np.concatenate([unit(rc), unit(rt)], axis=1)


def bar_similarity(F):
    """Bar-to-bar similarity 0..1 (1 = the same sound) from bar_features, chroma and timbre weighted equally."""
    n = F.shape[1] - 8; a, b = F[:, :n], F[:, n:]; return np.clip(0.5 * (a @ a.T) + 0.5 * (b @ b.T), 0, 1)


def waveform(x, n=PEAKS):
    """Loudest absolute sample in each of n equal pieces of the track, scaled so the biggest is 1."""
    n = max(1, min(n, len(x))); p = np.array([np.abs(c).max() for c in np.array_split(x, n)]); return [round(float(v), 3) for v in p / max(float(p.max()), 1e-9)]


def spectrogram_png(S, sr=SR):
    """The spectrogram as a PNG (bytes): SPEC_BANDS log-spaced frequency bands (40 Hz to 10 kHz, low at the bottom) by at most SPEC_COLS columns of time, in decibels, in colour."""
    import cv2
    freqs = np.fft.rfftfreq(N_FFT, 1.0 / sr); edges = np.geomspace(40.0, min(10000.0, sr / 2 - 1), SPEC_BANDS + 1); rows = []
    for a, b in zip(edges[:-1], edges[1:]):
        m = (freqs >= a) & (freqs < b)
        if not m.any(): m = np.zeros(len(freqs), bool); m[int(np.argmin(np.abs(freqs - (a + b) / 2)))] = True
        rows.append(S[:, m].mean(1))
    M = 20.0 * np.log10(np.array(rows) + 1e-6); cols = min(SPEC_COLS, M.shape[1]); M = np.stack([c.max(1) for c in np.array_split(M, cols, axis=1)], 1)
    lo, hi = np.percentile(M, 5), np.percentile(M, 99.5); img = (np.clip((M - lo) / max(hi - lo, 1e-9), 0, 1) * 255).astype(np.uint8)[::-1]
    return cv2.imencode('.png', cv2.applyColorMap(img, cv2.COLORMAP_INFERNO))[1].tobytes()


def _sig(path): st = os.stat(path); return [st.st_size, st.st_mtime_ns]


def _measure(path):
    x = decode(path); S = spectrogram(x); return x, S


def info(rd, rel):
    """The record of the track `rel` (inside the race dir): music.json when it is for this file and still current, else the track is analysed again and music.json rewritten. RuntimeError if it cannot be read."""
    p = os.path.join(rd, rel)
    try:
        r = json.load(open(os.path.join(rd, 'music.json')))
        if r.get('version') == VERSION and r.get('file') == rel and r.get('sig') == _sig(p) and os.path.exists(os.path.join(rd, r['spectrogram'])): return r
    except (OSError, ValueError, KeyError): r = {}
    x, S = _measure(p); sc = built_score(rd, rel); return _record_with(rd, rel, r.get('name') if r.get('file') == rel else None, x, S, built_analysis(sc) if sc else None)


def built_score(rd, rel):
    """The score of the built track `rel` (music/built.json, edit/music_build.py) when it is the score of that file, else None."""
    try: sc = json.load(open(os.path.join(rd, 'music', 'built.json')))
    except (OSError, ValueError): return None
    return sc if sc.get('source') == 'built' and sc.get('file') == rel and len(sc.get('downbeats') or []) >= 2 else None


def built_analysis(sc, bar_beats=4):
    """The analysis dict of a built track from its score instead of listening to it again: the bar lines are the ones it was built on, so the tempo is the real mean bar of the built audio (the original's bars wander a little; a tempo from the original would drift against them over a long film), the first bar line is the start of the file, the sections are the runs of equal intensity level."""
    d = sc['downbeats']; nb = len(sc['bars']); bar_s = (d[-1] - d[0]) / (len(d) - 1); lv = sc.get('levels') or []; sections = []
    for i in range(nb):
        v = float(lv[i]) if i < len(lv) else 0.5
        if sections and abs(sections[-1][2] - v) < 1e-9: sections[-1] = (sections[-1][0], (i + 1) * bar_beats, v)
        else: sections.append((i * bar_beats, (i + 1) * bar_beats, v))
    return dict(bpm=round(60.0 * bar_beats / bar_s, 2), offset_s=0.0, bar_beats=bar_beats, duration_s=round(float(sc['length_s']), 2), usable_beats=nb * bar_beats, sections=[(a, b, round(v, 3)) for a, b, v in sections], confidence=1.0, built=True)


def _record_with(rd, rel, name, x, S, analysis=None):
    d = os.path.join(rd, 'music'); os.makedirs(d, exist_ok=True); open(os.path.join(d, 'spectrogram.png'), 'wb').write(spectrogram_png(S))
    rec = dict(version=VERSION, file=rel, name=name or os.path.basename(rel), sig=_sig(os.path.join(rd, rel)), analysis=analysis or analyse_samples(x, S=S), waveform=waveform(x), spectrogram='music/spectrogram.png')
    json.dump(rec, open(os.path.join(rd, 'music.json'), 'w'), indent=1); return json.loads(json.dumps(rec))      # as it will read back (lists, not tuples)


def store(rd, data, ext, name):
    """Save an uploaded track as music/track<ext> and record it in music.json. The track is analysed first, so one that cannot be read (RuntimeError) leaves the current one alone; the old file is kept as track.<ext>.<UTC time>.replaced (every replaced track is kept)."""
    d = os.path.join(rd, 'music'); os.makedirs(d, exist_ok=True); tmp = os.path.join(d, 'incoming' + ext); open(tmp, 'wb').write(data)
    try: x, S = _measure(tmp); an = analyse_samples(x, S=S)
    except Exception:
        os.remove(tmp); raise
    for old in os.listdir(d):
        if old.startswith('track.') and not old.endswith('.replaced'):
            while True:                                                                  # UTC millisecond time stamp; a clash waits for the next millisecond
                t = time.time(); dest = os.path.join(d, f"{old}.{time.strftime('%Y%m%dT%H%M%S', time.gmtime(t))}{int(t * 1000) % 1000:03d}Z.replaced")
                if not os.path.exists(dest): break
                time.sleep(0.002)
            os.replace(os.path.join(d, old), dest)                                       # every earlier track stays, time stamped
    rel = 'music/track' + ext; os.replace(tmp, os.path.join(rd, rel)); return _record_with(rd, rel, name, x, S, an)


def remove(rd):
    """Forget the track: music.json and the spectrogram go (the audio file stays in music/ as it was)."""
    for n in ('music.json', os.path.join('music', 'spectrogram.png')):
        try: os.remove(os.path.join(rd, n))
        except OSError: pass


def cached(folder_rd, path):
    """The analysis dict of the track at `path` (inside the race dir), from music.json when current."""
    return info(folder_rd, os.path.relpath(path, folder_rd))['analysis']
