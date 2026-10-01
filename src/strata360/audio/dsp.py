"""Audio analysis, conditioning and mixing for the three use cases (spike).

  1. AMBIENCE / background noise: kept low under music, swelled up when the music goes quiet, so the film breathes.
  2. CROWD / excitement (starts, finishes, aid stations): normalised, peak-safe, mixed in where it adds energy.
  3. WEARER SPEECH (quiet or muffled voice to camera): denoise + auto-gain for the best speech recognition (16 kHz mono
     for the recogniser) and a gentler version for the mix.

Everything here is deterministic DSP (numpy, scipy, ffmpeg filters); the analysis returns a JSON-able dict (audio.json, README 5.10).
Loudness follows ITU-R BS.1770 (K-weighting, 400 ms blocks, gating), checked against ffmpeg's ebur128 in test_audio.py.

CLI:  python audio.py analyse CAM.OSV audio.json
      python audio.py speech in.wav out_asr16k.wav [out_mix48k.wav]
"""
import json, os, subprocess, sys
import numpy as np
from scipy import signal

SR = 48000

# --------------------------------------------------------------------------------------------- tunable thresholds
SILENCE_DBFS = -65.0            # window RMS below this is silence
WIND_LF_SHARE = 0.75            # share of energy below 150 Hz that marks wind / handling rumble
VOICED_ACF = 0.55               # normalised autocorrelation peak that marks a voiced frame
SPEECH_MIN_VOICED = 0.40        # fraction of voiced frames in a 0.4 s window for "speech"
SPEECH_MIN_SNR = 8.0            # dB above the clip's noise floor (speech band) for speech or crowd
CROWD_MAX_VOICED = 0.30
CROWD_MIN_SPEECH_SHARE = 0.30   # crowd = energy concentrated in the speech band (300-3400 Hz) but not one clean voice
EXCITEMENT_LU = 6.0             # momentary loudness above the clip median that counts as excitement
CLIP_LEVEL = 0.999


# ------------------------------------------------------------------------------------------------------ io
def load_audio(path, channels=2, sr=SR):
    """Decode the audio of any media file to float32 (n, channels)."""
    raw = subprocess.check_output(['ffmpeg', '-v', 'error', '-i', path, '-vn', '-f', 'f32le', '-ac', str(channels), '-ar', str(sr), '-'])
    return np.frombuffer(raw, np.float32).reshape(-1, channels).copy()


def write_wav(path, x, sr=SR):
    x = np.asarray(x, np.float32)
    if x.ndim == 1: x = x[:, None]
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'f32le', '-ar', str(sr), '-ac', str(x.shape[1]), '-i', '-', '-c:a', 'pcm_f32le', path],
                   input=x.tobytes(), check=True)


def ffmpeg_filter(x, sr, graph, out_sr=None, out_channels=None):
    """Run a float array (n, ch) through an ffmpeg -af graph and return the result (n', ch')."""
    x = np.asarray(x, np.float32)
    if x.ndim == 1: x = x[:, None]
    out_sr = out_sr or sr; oc = out_channels or x.shape[1]
    raw = subprocess.run(['ffmpeg', '-v', 'error', '-f', 'f32le', '-ar', str(sr), '-ac', str(x.shape[1]), '-i', '-', '-af', graph,
                          '-f', 'f32le', '-ar', str(out_sr), '-ac', str(oc), '-'], input=x.tobytes(), capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.float32).reshape(-1, oc).copy()


# ------------------------------------------------------------------------------------------------- loudness
_K1 = (np.array([1.53512485958697, -2.69169618940638, 1.19839281085285]), np.array([1.0, -1.69065929318241, 0.73248077421585]))
_K2 = (np.array([1.0, -2.0, 1.0]), np.array([1.0, -1.99004745483398, 0.99007225036621]))
_KSOS = np.vstack([np.r_[_K1[0], _K1[1]], np.r_[_K2[0], _K2[1]]])       # BS.1770 K-weighting at 48 kHz


def k_weight(x):
    return signal.sosfilt(_KSOS, x, axis=0)


def block_loudness(x, block=0.4, hop=0.1, sr=SR):
    """Momentary loudness (LUFS) of overlapping blocks. Returns (block start times, LUFS, mean-square per block)."""
    assert sr == SR
    y = k_weight(x); n, b, h = len(y), int(block * sr), int(hop * sr)
    starts = np.arange(0, max(n - b, 0) + 1, h)
    ms = np.array([np.sum(np.mean(y[s:s + b] ** 2, axis=0)) for s in starts])
    return starts / sr, -0.691 + 10 * np.log10(np.maximum(ms, 1e-12)), ms


def integrated_lufs(x, sr=SR):
    """BS.1770-4 gated integrated loudness (absolute gate -70 LUFS, relative gate -10 LU)."""
    _, l, ms = block_loudness(x, 0.4, 0.1, sr)
    keep = l > -70
    if not keep.any(): return -70.0
    rel = -0.691 + 10 * np.log10(np.mean(ms[keep])) - 10
    keep = keep & (l > rel)
    return float(-0.691 + 10 * np.log10(np.mean(ms[keep]))) if keep.any() else -70.0


def true_peak_dbfs(x, oversample=4):
    y = signal.resample_poly(x, oversample, 1, axis=0)
    return float(20 * np.log10(max(np.abs(y).max(), 1e-9)))


def db(a): return 20 * np.log10(np.maximum(a, 1e-9))


# --------------------------------------------------------------------------------------------------- analysis
def _voicing(m, sr=SR, frame=0.032, hop=0.010):
    """Per 10 ms frame: (voicing strength 0..1, f0 Hz or 0). Normalised autocorrelation peak in 70..500 Hz on 80 Hz-high-passed audio."""
    sos = signal.butter(2, 80, 'hp', fs=sr, output='sos'); h = signal.sosfilt(sos, m)
    N, H = int(frame * sr), int(hop * sr); lo, hi = int(sr / 500), int(sr / 70)
    nfr = max((len(h) - N - hi) // H, 0)
    vo = np.zeros(nfr); f0 = np.zeros(nfr)
    if nfr == 0: return vo, f0
    w = np.hanning(N)
    for c0 in range(0, nfr, 2000):
        idx = np.arange(c0, min(c0 + 2000, nfr))
        fr = np.stack([h[i * H:i * H + N] * w for i in idx])
        F = np.fft.rfft(fr, 2 * N, axis=1); r = np.fft.irfft(np.abs(F) ** 2, axis=1)[:, :hi + 1]
        r0 = np.maximum(r[:, 0], 1e-12)
        lags = np.arange(lo, hi + 1)
        rn = r[:, lo:hi + 1] / r0[:, None] * (N / np.maximum(N - lags, 1))[None, :] * 0.5 + 0.5 * r[:, lo:hi + 1] / r0[:, None]
        best = rn.max(1); lag = lags[rn.argmax(1)]
        loud = 10 * np.log10(np.mean(fr ** 2, 1) + 1e-12) > -75
        vo[idx] = np.where(loud, best, 0.0); f0[idx] = np.where(loud & (best > VOICED_ACF), sr / lag, 0.0)
    return vo, f0


def analyse_array(x, sr=SR, hop_s=0.1, win_s=0.4):
    """Per-window features and a segment labelling for a float array (n, ch) at 48 kHz. Returns the audio.json body."""
    assert sr == SR
    if x.ndim == 1: x = x[:, None]
    n = len(x); m = x.mean(1)
    win, hop = int(win_s * sr), int(hop_s * sr)
    starts = np.arange(0, max(n - win, 0) + 1, hop)
    t = (starts + win / 2) / sr
    # STFT band energies (10 ms hop)
    f, tf, Z = signal.stft(m, sr, nperseg=2048, noverlap=2048 - 480, boundary=None, padded=False)
    P = np.abs(Z) ** 2
    def bandP(lo, hi): return P[(f >= lo) & (f < hi)].sum(0)
    bands = {'lf': bandP(0, 150), 'lowmid': bandP(150, 300), 'speech': bandP(300, 3400), 'high': bandP(3400, 8000), 'air': bandP(8000, sr / 2)}
    tot = sum(bands.values()) + 1e-20
    vo, f0 = _voicing(m, sr); tv = np.arange(len(vo)) * 0.010 + 0.016
    _, lufs_m, _ = block_loudness(x, win_s, hop_s, sr)
    W = dict(t_s=[], rms_dbfs=[], peak_dbfs=[], lufs_m=[], lf_share=[], speech_share=[], speech_band_dbfs=[], high_share=[], flatness=[], voiced_frac=[], f0_hz=[], clipped_samples=[])
    for k, s in enumerate(starts):
        seg = x[s:s + win]; a, b = t[k] - win_s / 2, t[k] + win_s / 2
        fm = (tf >= a) & (tf < b); vm = (tv >= a) & (tv < b)
        rms = float(np.sqrt(np.mean(seg ** 2)) + 1e-12); tt = tot[fm].sum() + 1e-20
        sp = bands['speech'][fm]; spg = np.exp(np.mean(np.log(sp + 1e-20))) / (np.mean(sp) + 1e-20) if fm.any() else 1.0
        vf = float(np.mean(vo[vm] > VOICED_ACF)) if vm.any() else 0.0
        ff = f0[vm][f0[vm] > 0]
        W['t_s'].append(round(float(t[k]), 3)); W['rms_dbfs'].append(round(float(db(rms)), 2)); W['peak_dbfs'].append(round(float(db(np.abs(seg).max())), 2))
        W['lufs_m'].append(round(float(lufs_m[min(k, len(lufs_m) - 1)]), 2))
        W['lf_share'].append(round(float(bands['lf'][fm].sum() / tt), 3))
        W['speech_share'].append(round(float(bands['speech'][fm].sum() / tt), 3))
        W['speech_band_dbfs'].append(round(float(db(rms) + 10 * np.log10(bands['speech'][fm].sum() / tt + 1e-12)), 2))
        W['high_share'].append(round(float((bands['high'][fm].sum() + bands['air'][fm].sum()) / tt), 3)); W['flatness'].append(round(float(spg), 3))
        W['voiced_frac'].append(round(vf, 3)); W['f0_hz'].append(round(float(np.median(ff)), 1) if len(ff) else 0.0)
        W['clipped_samples'].append(int((np.abs(seg) >= CLIP_LEVEL).sum()))
    A = {k: np.array(v) for k, v in W.items()}
    floor = float(np.percentile(A['speech_band_dbfs'], 10)); snr = A['speech_band_dbfs'] - floor
    med = float(np.median(A['lufs_m']))
    labels = []
    for k in range(len(t)):
        if A['rms_dbfs'][k] < SILENCE_DBFS: labels.append('silence')
        elif A['voiced_frac'][k] >= SPEECH_MIN_VOICED and snr[k] >= SPEECH_MIN_SNR: labels.append('speech')
        elif snr[k] >= SPEECH_MIN_SNR and A['voiced_frac'][k] < CROWD_MAX_VOICED and A['lf_share'][k] < WIND_LF_SHARE and A['speech_share'][k] >= CROWD_MIN_SPEECH_SHARE: labels.append('crowd')
        elif A['lf_share'][k] >= WIND_LF_SHARE: labels.append('wind')
        else: labels.append('ambience')
    labels = _majority(labels, 5)
    segs = _segments(labels, A, t, hop_s, win_s, floor, med)
    clip_idx = np.nonzero(A['clipped_samples'])[0]
    summary = dict(duration_s=round(n / sr, 3), channels=int(x.shape[1]), dual_mono=bool(x.shape[1] == 2 and np.abs(x[:, 0] - x[:, 1]).max() < 1e-6),
                   integrated_lufs=round(integrated_lufs(x), 2), true_peak_dbfs=round(true_peak_dbfs(x), 2), sample_peak_dbfs=round(float(db(np.abs(x).max())), 2),
                   loudness_range_lu=round(float(np.percentile(A['lufs_m'], 95) - np.percentile(A['lufs_m'], 10)), 2), noise_floor_speech_band_dbfs=round(floor, 2),
                   clipped_samples=int(A['clipped_samples'].sum()), clipped_windows_s=[round(float(t[i]), 2) for i in clip_idx][:50])
    return dict(sample_rate=sr, window_s=win_s, hop_s=hop_s, summary=summary, windows={k: v.tolist() for k, v in A.items()}, window_labels=labels, segments=segs)


def _majority(labels, k):
    if len(labels) < k: return labels
    out = list(labels); h = k // 2
    for i in range(len(labels)):
        w = labels[max(0, i - h):i + h + 1]; out[i] = max(set(w), key=w.count)
    return out


def _segments(labels, A, t, hop_s, win_s, floor, med):
    segs, i = [], 0
    while i < len(labels):
        j = i
        while j + 1 < len(labels) and labels[j + 1] == labels[i]: j += 1
        s = slice(i, j + 1); lab = labels[i]
        seg = dict(label=lab, t0_s=round(float(t[i] - hop_s / 2), 3), t1_s=round(float(t[j] + hop_s / 2), 3),
                   mean_lufs_m=round(float(A['lufs_m'][s].mean()), 2), peak_dbfs=round(float(A['peak_dbfs'][s].max()), 2),
                   snr_db=round(float((A['speech_band_dbfs'][s] - floor).mean()), 1), voiced_frac=round(float(A['voiced_frac'][s].mean()), 2),
                   lf_share=round(float(A['lf_share'][s].mean()), 2), clipped=bool(A['clipped_samples'][s].sum() > 0))
        if lab in ('speech', 'crowd'): seg['excitement_lu'] = round(float(A['lufs_m'][s].mean() - med), 1)
        seg['use'] = dict(speech='enhance_speech (asr + mix), duck music', crowd='condition_ambience(crowd), mix in at starts/finishes / excitement',
                          ambience='condition_ambience(bed), swell when music is quiet', wind='high-pass; keep only as far-low bed or drop', silence='none')[lab]
        segs.append(seg); i = j + 1
    return segs


# ---------------------------------------------------------------------------------------- neural denoisers
_DFN = None


def dfn_denoise(x48, atten_lim_db=None):
    """DeepFilterNet3 (neural speech enhancement, native 48 kHz, 2023). x48: float32 mono at 48 kHz. `atten_lim_db` caps how much it
    may attenuate (e.g. 12-20 dB), which keeps artefacts down at the price of leaving some noise. Needs the project venv."""
    global _DFN
    import torch
    from df.enhance import enhance, init_df
    if _DFN is None: _DFN = init_df(log_level='ERROR')[:2]
    model, st = _DFN
    y = enhance(model, st, torch.from_numpy(np.asarray(x48, np.float32)[None]), atten_lim_db=atten_lim_db)
    return y[0].numpy().astype(np.float32)


def write_flac(path, x, sr=SR):
    x = np.asarray(x, np.float32)
    if x.ndim == 1: x = x[:, None]
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'f32le', '-ar', str(sr), '-ac', str(x.shape[1]), '-i', '-', '-c:a', 'flac', '-compression_level', '5', path], input=x.tobytes(), check=True)


CLEAN_TARGET_LUFS = -14.0       # full-volume speech: louder than the camera's own level, which is usually low; what to use, and fades, are editing decisions


def clean_for_playback(x, sr=SR, atten_lim_db=18.0, target_lufs=CLEAN_TARGET_LUFS):
    """The clip's sound cleaned for listening and for the film (NOT for recognition: enhancement raised word error rate, see enhance_speech): rumble removed, DeepFilterNet3 with a capped
    attenuation (so the crowd and the place stay, and artefacts stay small), a little speech EQ, speech-aware auto gain (quiet speech is lifted, pauses are not), then loudness normalised up to
    `target_lufs` with a peak limiter: speech at full volume. x: (n,) or (n, ch) float32 at 48 kHz; returns mono 48 kHz."""
    if x.ndim == 2: x = x.mean(1)
    y = dfn_denoise(ffmpeg_filter(x, sr, 'highpass=f=80:poles=2')[:, 0], atten_lim_db)
    y = ffmpeg_filter(y, sr, 'equalizer=f=250:t=q:w=1:g=-2,equalizer=f=3000:t=q:w=0.9:g=2,speechnorm=e=6:r=0.0005:l=1:t=0.02', out_channels=1)[:, 0]
    for _ in range(3):                                                                    # normalise the loudness (the limiter takes some back, so correct again)
        cur = integrated_lufs(np.repeat(y[:, None], 2, 1))
        if not np.isfinite(cur) or abs(target_lufs - cur) < 0.4: break
        y = ffmpeg_filter(y * 10 ** (float(np.clip(target_lufs - cur, -12, 30)) / 20), sr, 'alimiter=limit=0.89:attack=5:release=60:level=0', out_channels=1)[:, 0]
    return ffmpeg_filter(y, sr, 'alimiter=limit=0.89:attack=5:release=60:level=0', out_channels=1)[:, 0]


def mossformer_denoise(x48):
    """MossFormer2_SE_48K via ClearerVoice-Studio (2024-25 model). Runs in its own venv (.venv-cv, clearvoice pins numpy<2) as a subprocess."""
    import tempfile
    here = os.path.dirname(os.path.abspath(__file__))
    py = os.environ.get('STRATA_CV_PYTHON') or os.path.join(here, '..', '..', '..', '.venv-cv', 'bin', 'python')   # repo root / .venv-cv
    with tempfile.TemporaryDirectory() as d:
        write_wav(f'{d}/in.wav', x48, SR)
        subprocess.run([py, os.path.join(here, 'mossformer_cli.py'), f'{d}/in.wav', f'{d}/out.wav'], check=True, capture_output=True)
        y = load_audio(f'{d}/out.wav', 1)[:, 0]
    return y[:len(x48)] if len(y) >= len(x48) else np.pad(y, (0, len(x48) - len(y)))


# ---------------------------------------------------------------------------------------- speech conditioning
SPEECH_CHAIN = dict(hp=100, nr=18, nf=-40, tr=1, rf=-45, presence_db=3.0, boom_db=-3.0, lp=7500, speechnorm_e=8, speechnorm_t=0.02, limit=0.89,
                    denoise='afftdn', atten_lim_db=None)   # denoise: 'afftdn' (ffmpeg, classical) | 'dfn' (DeepFilterNet3) | 'mossformer' | 'none'


def enhance_speech(x, sr=SR, profile='asr', **over):
    """Denoise and auto-gain a quiet or muffled voice. NOTE (measured, README 5.11 / docs/progress.md): for whisper-class recognisers use RAW audio
    resampled to 16 kHz, not this: enhancement raised word error rate (0.16 -> 0.19-0.22 with `small`, 0.12 -> 0.14 with `large-v3-turbo`) except
    against wind. Use profile 'mix' for the film. profile 'asr' -> 16 kHz mono float (kept for recognisers that need conditioning);
    profile 'mix' -> 48 kHz mono (gentler denoise, loudness set to -18 LUFS, peak-safe) for the film.
    Chain: high-pass (wind/handling rumble) -> adaptive FFT denoise -> speech EQ -> speech-aware auto gain (only above a
    threshold, so pauses are not boosted) -> peak limiter."""
    p = dict(SPEECH_CHAIN); p.update(over)
    if x.ndim == 2: x = x.mean(1)
    if profile == 'mix': p.update(nr=min(p['nr'], 10), speechnorm_e=min(p['speechnorm_e'], 5), lp=12000)
    if p['denoise'] == 'dfn':
        x = dfn_denoise(ffmpeg_filter(x, sr, f"highpass=f={min(p['hp'], 80)}:poles=2")[:, 0], p['atten_lim_db']); pre = ''
    elif p['denoise'] == 'mossformer':
        x = mossformer_denoise(ffmpeg_filter(x, sr, f"highpass=f={min(p['hp'], 80)}:poles=2")[:, 0]); pre = ''
    else:
        pre = f"highpass=f={p['hp']}:poles=2," + (f"afftdn=nr={p['nr']}:nf={p['nf']}:tn=1:tr={p['tr']}:rf={p['rf']}:ad=0.6," if p['denoise'] == 'afftdn' else '')
    g = (f"{pre}equalizer=f=250:t=q:w=1:g={p['boom_db']},equalizer=f=3000:t=q:w=0.9:g={p['presence_db']},lowpass=f={p['lp']},"
         f"speechnorm=e={p['speechnorm_e']}:r=0.0005:l=1:t={p['speechnorm_t']},alimiter=limit={p['limit']}:attack=5:release=60:level=0")
    y = ffmpeg_filter(x, sr, g, out_sr=16000 if profile == 'asr' else sr, out_channels=1)[:, 0]
    if profile == 'mix':                                     # loudness to -18 LUFS; the limiter takes some back, so correct once more
        for _ in range(3):
            gain = -18.0 - integrated_lufs(y[:, None].repeat(2, 1))
            if abs(gain) < 0.3: break
            y = _peak_limit(y * 10 ** (float(np.clip(gain, -24, 24)) / 20), 0.89)
    return y


def _peak_limit(y, limit):
    pk = np.abs(y).max()
    if pk <= limit: return y
    return ffmpeg_filter(y, SR, f"alimiter=limit={limit}:attack=3:release=40:level=0")[:, 0]


# ------------------------------------------------------------------------------- ambience / crowd conditioning
def condition_ambience(x, sr=SR, target_lufs=-30.0, kind='bed', max_gain_db=18.0, tp_limit_dbfs=-1.5):
    """Clean, level and peak-protect a background or crowd stem. kind 'bed' (steady ambience: strong rumble filter,
    levelled quiet) or 'crowd' (excitement: light rumble filter, gentle compression, louder target).
    Returns (audio (n, ch) float32, report dict). Clipped input is repaired first (ffmpeg adeclip)."""
    if x.ndim == 1: x = x[:, None]
    rep = dict(kind=kind, lufs_in=round(integrated_lufs(np.repeat(x, 2, 1) if x.shape[1] == 1 else x), 2), peak_in_dbfs=round(float(db(np.abs(x).max())), 2),
               clipped_in=int((np.abs(x) >= CLIP_LEVEL).sum()))
    hp = 80 if kind == 'bed' else 50
    graph = f"highpass=f={hp}:poles=2" + (",adeclip" if rep['clipped_in'] else "")
    graph += ",acompressor=threshold=0.1:ratio=2.5:attack=30:release=300:makeup=1" if kind == 'crowd' else ",acompressor=threshold=0.15:ratio=1.8:attack=50:release=400:makeup=1"
    y = ffmpeg_filter(x, sr, graph)
    cur = integrated_lufs(np.repeat(y, 2, 1) if y.shape[1] == 1 else y)
    gain = float(np.clip(target_lufs - cur, -30, max_gain_db)); y = y * 10 ** (gain / 20)
    tp_lim = 10 ** (tp_limit_dbfs / 20)
    if true_peak_dbfs(y) > tp_limit_dbfs:
        y = ffmpeg_filter(y, sr, f"alimiter=limit={tp_lim * 0.97:.4f}:attack=3:release=50:level=0")
    rep.update(gain_db=round(gain, 2), lufs_out=round(integrated_lufs(np.repeat(y, 2, 1) if y.shape[1] == 1 else y), 2),
               true_peak_out_dbfs=round(true_peak_dbfs(y), 2), clipped_out=int((np.abs(y) >= CLIP_LEVEL).sum()))
    return y.astype(np.float32), rep


# ---------------------------------------------------------------------------------------------- mix planning
def _smooth_gain(target_db, rate, attack_s, release_s):
    """Asymmetric one-pole smoothing of a dB envelope sampled at `rate` Hz. Falling gain uses `attack`, rising uses `release`."""
    out = np.empty_like(target_db); g = target_db[0]
    ka, kr = np.exp(-1 / (attack_s * rate)), np.exp(-1 / (release_s * rate))
    for i, v in enumerate(target_db):
        k = ka if v < g else kr
        g = k * g + (1 - k) * v; out[i] = g
    return out


def envelope_db(x, rate=100, sr=SR):
    """RMS envelope in dBFS at `rate` Hz (mono mix)."""
    m = x.mean(1) if x.ndim == 2 else x; h = sr // rate
    n = len(m) // h; e = np.sqrt(np.mean(m[:n * h].reshape(n, h) ** 2, axis=1))
    return db(e)


def mix_plan(n_samples, music, speech_flags=(), crowd_flags=(), *, rate=100, sr=SR, music_quiet_dbfs=-45.0, hold_s=0.3,
             ambience_swell_db=12.0, swell_in_s=0.5, swell_out_s=0.15,
             duck_speech_db=-12.0, duck_crowd_db=-6.0, duck_attack_s=0.05, duck_release_s=0.4):
    """Gain envelopes (dB relative to each stem's nominal level, at `rate` Hz).
      * ambience: sits at its nominal (bed) level under the music and swells by `ambience_swell_db` while the music is
        quiet. A rest only counts once it has lasted `hold_s` (short rests do not pump it). The swell fades in over
        `swell_in_s` (gentle) and drops over `swell_out_s` when the music returns (so it never fights the music).
      * music: ducked under wearer speech and (less) under crowd; fast attack, slower release.
    speech_flags / crowd_flags: lists of (t0_s, t1_s) in output time. Returns dict of arrays plus the music-quiet mask."""
    n = int(np.ceil(n_samples / sr * rate)); t = np.arange(n) / rate
    env = envelope_db(music, rate, sr); env = np.r_[env, np.full(max(n - len(env), 0), -120.0)][:n]
    quiet = env < music_quiet_dbfs
    k = max(int(hold_s * rate), 1); q = np.zeros(n, bool); run = 0
    for i in range(n):
        run = run + 1 if quiet[i] else 0
        if run >= k: q[i - k + 1:i + 1] = True            # a rest that lasted the hold counts from its start
    amb = _smooth_gain(np.where(q, ambience_swell_db, 0.0), rate, attack_s=swell_out_s, release_s=swell_in_s)
    def flags_to_db(flags, depth):
        d = np.zeros(n)
        for a, b in flags: d[(t >= a) & (t < b)] = depth
        return d
    duck = np.minimum(flags_to_db(speech_flags, duck_speech_db), flags_to_db(crowd_flags, duck_crowd_db))
    music_g = _smooth_gain(duck, rate, duck_attack_s, duck_release_s)
    return dict(rate=rate, t_s=t, ambience_gain_db=amb, music_gain_db=music_g, music_quiet=q)


def apply_gain_db(x, gain_db, rate, sr=SR):
    """Apply a dB envelope (at `rate` Hz, linearly interpolated) to (n, ch) or (n,) audio."""
    g = 10 ** (np.interp(np.arange(len(x)) / sr, np.arange(len(gain_db)) / rate, gain_db) / 20)
    return x * (g[:, None] if x.ndim == 2 else g)


def render_mix(music, ambience, speech, crowd, plan, *, speech_lufs=-18.0, crowd_db=-4.0, target_lufs=-16.0, tp_dbfs=-1.0, sr=SR):
    """Sum the stems with the plan's envelopes, then set the programme loudness and protect the true peak. All inputs (n, 2) at 48 kHz."""
    n = len(music); pad = lambda a: np.pad(a, ((0, max(n - len(a), 0)), (0, 0)))[:n]
    m = apply_gain_db(pad(music), plan['music_gain_db'], plan['rate'])
    amb = apply_gain_db(pad(ambience), plan['ambience_gain_db'], plan['rate'])           # the ambience stem arrives at its bed level; the plan adds the swell
    sp = pad(speech); cr = pad(crowd) * 10 ** (crowd_db / 20)
    mix = m + amb + sp + cr
    lu = integrated_lufs(mix); mix = mix * 10 ** ((target_lufs - lu) / 20)
    if true_peak_dbfs(mix) > tp_dbfs: mix = ffmpeg_filter(mix, sr, f"alimiter=limit={10 ** ((tp_dbfs - 0.5) / 20):.4f}:attack=3:release=50:level=0")
    return mix.astype(np.float32), dict(lufs=round(integrated_lufs(mix), 2), true_peak_dbfs=round(true_peak_dbfs(mix), 2), clipped=int((np.abs(mix) >= CLIP_LEVEL).sum()))


# ---------------------------------------------------------------------------------------------- objective test
def stoi_approx(clean, degraded, sr):
    """Short-time objective intelligibility (after Taal et al. 2011), compact re-implementation: 10 kHz, 512-point STFT, 15
    one-third-octave bands from 150 Hz, 384 ms envelope segments, normalisation and clipping (beta = -15 dB), mean correlation.
    Phase-insensitive, so unlike waveform SDR it does not punish the small delays every filter adds. Range about 0..1
    (higher = more intelligible); a relative measure for comparing processing chains, not an absolute prediction of word error rate."""
    fs = 10000
    c = signal.resample_poly(clean, fs, sr) if sr != fs else clean; d = signal.resample_poly(degraded, fs, sr) if sr != fs else degraded
    n = min(len(c), len(d)); c, d = c[:n], d[:n]
    cc = signal.correlate(d, c, mode='full', method='fft'); mid = n - 1; lag = int(np.argmax(cc[mid - 300:mid + 301])) - 300      # align (max +-30 ms)
    if lag > 0: d = d[lag:]; c = c[:len(d)]
    elif lag < 0: c = c[-lag:]; d = d[:len(c)]
    m = min(len(c), len(d)); c, d = c[:m], d[:m]
    N, hop = 512, 256; win = np.hanning(N + 2)[1:-1]
    def frames(x): idx = np.arange(0, len(x) - N, hop); return np.stack([x[i:i + N] * win for i in idx])
    fc, fd = frames(c), frames(d)
    en = 20 * np.log10(np.linalg.norm(fc, axis=1) + 1e-9); keep = en > en.max() - 40                                            # drop silent clean frames
    fc, fd = fc[keep], fd[keep]
    Sc = np.abs(np.fft.rfft(fc, axis=1)) ** 2; Sd = np.abs(np.fft.rfft(fd, axis=1)) ** 2
    freqs = np.fft.rfftfreq(N, 1 / fs); cf = 150 * 2 ** (np.arange(15) / 3.0); lo = cf / 2 ** (1 / 6); hi = cf * 2 ** (1 / 6)
    B = np.stack([((freqs >= l) & (freqs < h)).astype(float) for l, h in zip(lo, hi)])
    X = np.sqrt(np.einsum('tf,bf->tb', Sc, B)); Y = np.sqrt(np.einsum('tf,bf->tb', Sd, B))     # (frames, bands) one-third-octave envelopes (einsum: matmul is broken on this Mac's numpy)
    Nseg = 30; beta = 10 ** (15 / 20.0); scores = []
    for j in range(Nseg, X.shape[0] + 1):
        x = X[j - Nseg:j]; y = Y[j - Nseg:j]
        a = np.linalg.norm(x, axis=0) / (np.linalg.norm(y, axis=0) + 1e-12)
        yn = np.minimum(y * a, x * (1 + beta))
        xc = x - x.mean(0); yc = yn - yn.mean(0)
        scores.append(np.mean(np.sum(xc * yc, 0) / (np.linalg.norm(xc, axis=0) * np.linalg.norm(yc, axis=0) + 1e-12)))
    return float(np.mean(scores)) if scores else 0.0



def wer(reference, hypothesis):
    """Word error rate after lower-casing and stripping punctuation."""
    import re
    norm = lambda t: re.sub(r"[^a-z0-9' ]+", ' ', t.lower()).split()
    r, h = norm(reference), norm(hypothesis)
    d = np.zeros((len(r) + 1, len(h) + 1), int); d[:, 0] = np.arange(len(r) + 1); d[0, :] = np.arange(len(h) + 1)
    for i in range(1, len(r) + 1):
        for j in range(1, len(h) + 1):
            d[i, j] = min(d[i - 1, j] + 1, d[i, j - 1] + 1, d[i - 1, j - 1] + (r[i - 1] != h[j - 1]))
    return d[-1, -1] / max(len(r), 1)


def si_sdr(est, ref):
    """Scale-invariant SDR (dB) of est against ref (both zero-meaned)."""
    est = est - est.mean(); ref = ref - ref.mean()
    a = np.dot(est, ref) / (np.dot(ref, ref) + 1e-12); tgt = a * ref; e = est - tgt
    return float(10 * np.log10((np.dot(tgt, tgt) + 1e-12) / (np.dot(e, e) + 1e-12)))


def band_si_sdr(est, ref, sr, lo=200, hi=4000, max_lag=2400):
    """SI-SDR between band-passed (zero-phase) versions, after aligning est to ref by cross-correlation (chains add small delays)."""
    sos = signal.butter(4, [lo, hi], 'bp', fs=sr, output='sos')
    e = signal.sosfiltfilt(sos, est); r = signal.sosfiltfilt(sos, ref)
    n = min(len(e), len(r)); e, r = e[:n], r[:n]
    cc = signal.correlate(e, r, mode='full', method='fft'); mid = n - 1
    lag = int(np.argmax(cc[mid - max_lag:mid + max_lag + 1])) - max_lag
    if lag > 0: e = e[lag:]; r = r[:len(e)]
    elif lag < 0: r = r[-lag:]; e = e[:len(r)]
    m = min(len(e), len(r)); return si_sdr(e[:m], r[:m])


if __name__ == '__main__':
    cmd = sys.argv[1]
    if cmd == 'analyse':
        a = analyse_array(load_audio(sys.argv[2])); a['source'] = os.path.basename(sys.argv[2])
        json.dump(a, open(sys.argv[3], 'w'), indent=1); print(json.dumps(a['summary'], indent=1)); [print(' ', s['label'], s['t0_s'], s['t1_s'], s['mean_lufs_m'], 'snr', s['snr_db']) for s in a['segments']]
    elif cmd == 'speech':
        x = load_audio(sys.argv[2], 1); write_wav(sys.argv[3], enhance_speech(x[:, 0], SR, 'asr'), 16000)
        if len(sys.argv) > 4: write_wav(sys.argv[4], enhance_speech(x[:, 0], SR, 'mix'), SR)
