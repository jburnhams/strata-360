"""Music analysis on a synthetic track."""
import os, subprocess, shutil
import numpy as np
import pytest
from strata360.edit import music as M
from strata360.render import preview as PV
from strata360.pipeline import config
from strata360.edit import voiceover as V
from library import make_track

def test_tempo_bar_line_and_energy(tmp_path):
    track_path = make_track(str(tmp_path / 'track.wav'), 124.0, 1.3)
    r = M.analyse(track_path); assert abs(r['bpm'] - 124.0) < 0.6, r
    beat = 60 / 124.0; assert min(abs(r['offset_s'] - 1.3 - k * 4 * beat) for k in range(-3, 4)) < 0.05, r                      # the first downbeat is on the bar line (any bar: the thump marks them all)
    assert r['sections'][0][2] < r['sections'][-1][2], r['sections']                                                          # quiet first half, louder second half

def test_the_film_sound_mixes_music_under_the_voice_over(tmp_path):
    f = str(tmp_path)
    rd = config.race_dir(f); os.makedirs(os.path.join(rd, 'music')); os.makedirs(os.path.join(rd, 'voiceover'))
    make_track(os.path.join(rd, 'music', 'track.wav'), 124.0, 1.3, 30)
    subprocess.run(['ffmpeg', '-y', '-v', 'error', '-f', 'lavfi', '-i', 'sine=frequency=300:duration=6', '-ar', '48000', '-ac', '1', os.path.join(rd, 'voiceover', 'voiceover.wav')], check=True)
    plan = dict(film=dict(music=dict(file='music/track.wav', offset_s=1.3)), segments=[dict(clip='X', clip_start_s=0.0, dur_s=4.0, speech=False), dict(clip='Y', clip_start_s=0.0, dur_s=4.0, speech=True)])
    out = os.path.join(f, 'a.wav'); PV.build_audio(f, plan, out, 8.0)
    assert abs(V.duration(out) - 8.0) < 0.05
    raw = subprocess.run(['ffmpeg', '-v', 'error', '-i', out, '-f', 'f32le', '-ac', '1', '-ar', '8000', '-'], capture_output=True).stdout; a = np.frombuffer(raw, np.float32); assert np.abs(a[8000:16000]).max() > 0.05 and np.abs(a[-4000:]).max() < np.abs(a[8000:16000]).max()   # music is there; it fades at the end
