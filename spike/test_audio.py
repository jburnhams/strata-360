"""Tests for spike/audio.py. Run: python spike/test_audio.py   (needs ffmpeg and macOS `say`; the sample OSV supplies real noise)."""
import os, subprocess, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import audio as A

SR = A.SR; HERE = os.path.dirname(os.path.abspath(__file__))
OSV = os.path.join(HERE, '..', 'videos', 'CAM_20260221120007_0019_D.OSV')
TMP = tempfile.mkdtemp(); RNG = np.random.default_rng(1)
SENT = ["Nearly at the summit now, feeling good, the legs are holding up well.", "Aid station in about two kilometres, I will take on some water there.",
        "The weather is turning, so I am putting the jacket on before the ridge.", "Absolutely loving this section, the trail is beautiful today.",
        "Kilometre forty five, still smiling, let's keep it moving.", "Coming into the finish, this is what it is all about."]
VOICES = ['Daniel', 'Samantha', 'Karen', 'Fred', 'Moira', 'Rishi']

def tts(text, voice='Daniel'):
    p = f'{TMP}/{voice}_{abs(hash(text)) % 10**6}.aiff'
    subprocess.run(['say', '-v', voice, '-o', p, text], check=True)
    return A.load_audio(p, 1)[:, 0]

def scale_to_rms_db(x, level): return x * 10 ** (level / 20) / (np.sqrt(np.mean(x ** 2)) + 1e-12)
def sine(f, dur, amp): t = np.arange(int(dur * SR)) / SR; return (amp * np.sin(2 * np.pi * f * t)).astype(np.float32)
def ffmpeg_lufs(x):
    A.write_wav(f'{TMP}/l.wav', x, SR)
    o = subprocess.run(['ffmpeg', '-hide_banner', '-nostats', '-i', f'{TMP}/l.wav', '-af', 'ebur128=peak=true', '-f', 'null', '-'], capture_output=True, text=True).stderr
    return float([l for l in o.splitlines() if l.strip().startswith('I:')][-1].split()[1])

def test_loudness_matches_ffmpeg():
    for name, x in (('sine -20', np.repeat(sine(997, 5, 0.1)[:, None], 2, 1)), ('sine -35', np.repeat(sine(200, 5, 0.018)[:, None], 2, 1)),
                    ('noise', (RNG.standard_normal((SR * 5, 2)) * 0.05).astype(np.float32)), ('speech', np.repeat(scale_to_rms_db(tts(SENT[0]), -24)[:, None], 2, 1))):
        a, b = A.integrated_lufs(x), ffmpeg_lufs(x)
        assert abs(a - b) < 0.15, (name, a, b)
    if os.path.exists(OSV):
        x = A.load_audio(OSV); assert abs(A.integrated_lufs(x) - ffmpeg_lufs(x)) < 0.15

def test_true_peak_detects_intersample_overs():
    x = sine(11025, 1.0, 0.7)[:, None]                 # sampled near its peaks: sample peak below true peak
    x = np.roll(x, 3, 0)
    assert A.true_peak_dbfs(np.repeat(x, 2, 1)) >= A.db(np.abs(x).max()) - 0.01

def _timeline():
    parts, spans = [], {}
    def add(name, y): spans[name] = (sum(len(p) for p in parts) / SR, (sum(len(p) for p in parts) + len(y)) / SR); parts.append(y.astype(np.float32))
    n = int(2.4 * SR)
    def fit(y): return np.pad(y, (0, max(n - len(y), 0)))[:n]
    add('speech', fit(scale_to_rms_db(tts(SENT[0]), -24)) + RNG.standard_normal(n).astype(np.float32) * 10 ** (-58 / 20))
    wind = scale_to_rms_db(np.convolve(RNG.standard_normal(n), np.hanning(400) / np.hanning(400).sum(), 'same'), -22)   # rumble: energy below about 150 Hz
    add('wind', wind)
    add('silence', RNG.standard_normal(n).astype(np.float32) * 10 ** (-85 / 20))
    crowd = sum(fit(scale_to_rms_db(np.roll(tts(SENT[i], VOICES[i]), int(i * 0.37 * SR)), -34)) for i in range(6))
    add('crowd', scale_to_rms_db(crowd, -24) + RNG.standard_normal(n).astype(np.float32) * 10 ** (-52 / 20))
    return np.concatenate(parts), spans

def test_classification_on_synthetic_timeline():
    x, spans = _timeline(); r = A.analyse_array(np.repeat(x[:, None], 2, 1))
    t = np.array(r['windows']['t_s']); lab = np.array(r['window_labels'])
    for name, (a, b) in spans.items():
        m = (t > a + 0.3) & (t < b - 0.3); frac = float(np.mean(lab[m] == name))
        print(f'    {name:8s} windows labelled correctly: {frac:.0%}')
        assert frac >= 0.6, (name, frac, sorted(set(lab[m])))

def test_clipping_is_detected_and_repaired():
    x = np.clip(sine(300, 3.0, 1.6) * np.hanning(3 * SR)[:] + sine(700, 3.0, 0.3), -1, 1)[:, None].astype(np.float32); x = np.repeat(x, 2, 1)
    r = A.analyse_array(x); assert r['summary']['clipped_samples'] > 100 and r['summary']['clipped_windows_s']
    y, rep = A.condition_ambience(x, kind='crowd', target_lufs=-26)
    assert rep['clipped_in'] > 100 and rep['clipped_out'] == 0 and rep['true_peak_out_dbfs'] <= -1.4, rep

def test_ambience_and_crowd_levels_and_peaks():
    if not os.path.exists(OSV): return
    x = A.load_audio(OSV)
    for kind, target in (('bed', -32.0), ('crowd', -24.0)):
        y, rep = A.condition_ambience(x, kind=kind, target_lufs=target)
        print(f'    {kind}: {rep}')
        assert abs(rep['lufs_out'] - target) < 0.6 or rep['gain_db'] in (-30, 18), rep
        assert rep['true_peak_out_dbfs'] <= -1.4 and rep['clipped_out'] == 0

def _noise_from_sample(n):
    x = A.load_audio(OSV, 1)[:, 0]
    return np.tile(x, int(np.ceil(n / len(x)) + 1))[:n]

def test_speech_chain_is_safe_and_does_not_hurt_intelligibility():
    """Classical DSP cannot do much for intelligibility in real non-stationary noise (measured: +0.00..0.01 STOI), so the
    requirement is: never make it worse, never clip, deliver the target level. (A neural denoiser is future work, README 14.6.)"""
    if not os.path.exists(OSV): return
    clean = scale_to_rms_db(tts(SENT[1]), -20); n = len(clean) + SR
    noise = _noise_from_sample(n); nb = np.sqrt(np.mean(A.ffmpeg_filter(noise, SR, 'highpass=f=300,lowpass=f=3400')[:, 0] ** 2))
    sp = np.pad(clean, (SR // 2, n - len(clean) - SR // 2)); spb = np.sqrt(np.mean(A.ffmpeg_filter(sp, SR, 'highpass=f=300,lowpass=f=3400')[:, 0] ** 2))
    for snr in (-5, 0, 5, 10):
        mix = (noise + sp * (nb / spb) * 10 ** (snr / 20)).astype(np.float32) * 0.5
        ya = A.enhance_speech(mix, SR, 'asr'); ym = A.enhance_speech(mix, SR, 'mix')
        mix16 = A.ffmpeg_filter(mix, SR, 'anull', out_sr=16000)[:, 0]; ref16 = A.ffmpeg_filter(sp, SR, 'anull', out_sr=16000)[:, 0]
        b, a = A.stoi_approx(ref16, mix16, 16000), A.stoi_approx(ref16, ya, 16000)
        lu = A.integrated_lufs(np.repeat(ym[:, None], 2, 1))
        print(f'    speech-band SNR {snr:+3d} dB: STOI {b:.3f} -> {a:.3f} ({a - b:+.3f});  asr peak {np.abs(ya).max():.2f}, mix {lu:.1f} LUFS peak {np.abs(ym).max():.2f}')
        assert a >= b - 0.01, ('processing must not reduce intelligibility', snr, b, a)
        assert np.abs(ya).max() <= 0.95 and np.abs(ym).max() <= 0.95, 'no clipping'
        assert abs(lu - (-18)) < 2.0

def test_quiet_voice_is_brought_up_but_pauses_are_not_boosted():
    v = scale_to_rms_db(tts(SENT[2]), -45); pause = np.zeros(SR)          # a very quiet voice followed by digital-quiet room tone
    room = RNG.standard_normal(SR).astype(np.float32) * 10 ** (-70 / 20)
    x = np.concatenate([v, room]).astype(np.float32)
    y = A.enhance_speech(x, SR, 'mix'); a, b = y[:len(v)], y[len(v):]
    assert A.db(np.sqrt(np.mean(a ** 2))) > -30, 'quiet speech should be lifted to a usable level'
    assert A.db(np.sqrt(np.mean(b ** 2))) < A.db(np.sqrt(np.mean(a ** 2))) - 25, 'room tone must not be boosted to speech level'

def _music(dur, gaps):
    t = np.arange(int(dur * SR)) / SR; m = 0.2 * (np.sin(2 * np.pi * 220 * t) + np.sin(2 * np.pi * 277 * t) + np.sin(2 * np.pi * 330 * t)) / 3
    for a, b in gaps: m[(t >= a) & (t < b)] = 0
    return np.repeat(m[:, None], 2, 1).astype(np.float32)

def test_ambience_swells_in_music_gaps_only():
    m = _music(8.0, [(3.0, 5.0), (6.2, 6.4)]); p = A.mix_plan(len(m), m, hold_s=0.3)
    g = p['ambience_gain_db']; at = lambda s: float(np.interp(s, p['t_s'], g))
    assert at(2.0) < 0.5 and at(4.8) > 11.0, (at(2.0), at(4.8))                # swells up in the 2 s gap
    assert at(5.3) < 6.0, 'drops quickly when the music returns'
    assert max(at(s) for s in np.arange(6.2, 6.9, 0.05)) < 1.5, 'a 0.2 s rest must not trigger the swell'

def test_music_ducks_under_speech_and_recovers():
    m = _music(8.0, []); p = A.mix_plan(len(m), m, speech_flags=[(2.0, 4.0)], crowd_flags=[(6.0, 7.0)])
    at = lambda s: float(np.interp(s, p['t_s'], p['music_gain_db']))
    assert at(2.2) <= -11.0 and at(3.9) <= -11.5, (at(2.2), at(3.9))
    assert at(5.5) > -1.0, 'recovers within 1.5 s of the end of speech'
    assert -7.0 <= at(6.5) <= -5.0, 'crowd ducks less than speech'

def test_final_mix_is_peak_safe_and_on_target():
    m = _music(8.0, [(3.0, 5.0)]); amb = np.repeat((RNG.standard_normal(len(m)) * 0.02)[:, None], 2, 1).astype(np.float32)
    sp = np.repeat(np.pad(scale_to_rms_db(tts(SENT[3]), -22), (int(1.0 * SR), 0))[:len(m), None], 2, 1) if False else np.zeros_like(m)
    cr = np.zeros_like(m)
    p = A.mix_plan(len(m), m, speech_flags=[(6.0, 7.0)]); mix, rep = A.render_mix(m, amb, sp, cr, p, target_lufs=-16.0)
    print('    mix:', rep); assert rep['clipped'] == 0 and rep['true_peak_dbfs'] <= -0.9 and abs(rep['lufs'] + 16.0) < 0.6

if __name__ == '__main__':
    fns = [v for k, v in sorted(globals().items()) if k.startswith('test_') and callable(v)]
    fails = 0
    for f in fns:
        try: f(); print('ok  ', f.__name__)
        except AssertionError as e: fails += 1; print('FAIL', f.__name__, e)
    print(f'{len(fns) - fails}/{len(fns)} passed'); sys.exit(1 if fails else 0)
