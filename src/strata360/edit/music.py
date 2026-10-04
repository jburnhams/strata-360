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
    x, S = _measure(p); return _record_with(rd, rel, r.get('name') if r.get('file') == rel else None, x, S)


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
