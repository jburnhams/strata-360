"""Music analysis on a synthetic track. Run: .venv/bin/python tests/test_music.py"""
import os, subprocess, sys, tempfile
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))
from strata360.edit import music as M


def make_track(bpm=124.0, offset=1.3, seconds=64, path=None):
    sr = 22050; x = np.zeros(int(seconds * sr), np.float32); beat = 60.0 / bpm; k = 0
    rng = np.random.default_rng(1)
    while offset + k * beat < seconds - 0.3:
        i = int((offset + k * beat) * sr); n = int(0.06 * sr); env = np.exp(-np.arange(n) / (0.012 * sr)); loud = 1.0 if seconds * 0.5 > offset + k * beat else 2.2       # louder second half
        tone = np.sin(2 * np.pi * (60 if k % 4 == 0 else 900) * np.arange(n) / sr) * env * (1.0 if k % 4 == 0 else 0.5) * loud * 0.3           # a low thump on the bar line, a tick on the other beats
        x[i:i + n] += tone + (rng.standard_normal(n) * 0.02 * env).astype(np.float32); k += 1
    path = path or os.path.join(tempfile.mkdtemp(), 'track.wav'); import wave
    with wave.open(path, 'wb') as w: w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr); w.writeframes((np.clip(x, -1, 1) * 32767).astype(np.int16).tobytes())
    return path


def test_tempo_bar_line_and_energy():
    r = M.analyse(make_track(124.0, 1.3)); assert abs(r['bpm'] - 124.0) < 0.6, r
    beat = 60 / 124.0; assert min(abs(r['offset_s'] - 1.3 - k * 4 * beat) for k in range(-3, 4)) < 0.05, r                      # the first downbeat is on the bar line (any bar: the thump marks them all)
    assert r['sections'][0][2] < r['sections'][-1][2], r['sections']                                                          # quiet first half, louder second half


def test_the_film_sound_mixes_music_under_the_voice_over():
    import json, shutil
    from strata360.render import preview as PV
    from strata360.pipeline import config
    f = tempfile.mkdtemp(); rd = config.race_dir(f); os.makedirs(os.path.join(rd, 'music')); os.makedirs(os.path.join(rd, 'voiceover'))
    shutil.copy(make_track(124.0, 1.3, 30), os.path.join(rd, 'music', 'track.wav'))
    subprocess.run(['ffmpeg', '-y', '-v', 'error', '-f', 'lavfi', '-i', 'sine=frequency=300:duration=6', '-ar', '48000', '-ac', '1', os.path.join(rd, 'voiceover', 'voiceover.wav')], check=True)
    plan = dict(film=dict(music=dict(file='music/track.wav', offset_s=1.3)), segments=[dict(clip='X', clip_start_s=0.0, dur_s=4.0, speech=False), dict(clip='Y', clip_start_s=0.0, dur_s=4.0, speech=True)])
    out = os.path.join(f, 'a.wav'); PV.build_audio(f, plan, out, 8.0)
    from strata360.edit import voiceover as V; assert abs(V.duration(out) - 8.0) < 0.05
    raw = subprocess.run(['ffmpeg', '-v', 'error', '-i', out, '-f', 'f32le', '-ac', '1', '-ar', '8000', '-'], capture_output=True).stdout; a = np.frombuffer(raw, np.float32); assert np.abs(a[8000:16000]).max() > 0.05 and np.abs(a[-4000:]).max() < np.abs(a[8000:16000]).max()   # music is there; it fades at the end


if __name__ == '__main__':
    fns = [v for k, v in sorted(globals().items()) if k.startswith('test_')]; bad = 0
    for fn in fns:
        try: fn(); print('ok  ', fn.__name__)
        except Exception as e: bad += 1; print('FAIL', fn.__name__, repr(e)[:300])
    print(f'{len(fns) - bad}/{len(fns)} passed'); sys.exit(bad)
