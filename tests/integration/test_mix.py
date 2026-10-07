"""audio/mix.py (A3): joins, stereo, the music under the voice-over, and the loudness target, on synthetic tones."""
import os, re, subprocess
import numpy as np
import pytest
from strata360.audio import mix
from strata360.pipeline import config

SR = 8000


def tone(path, hz, secs, vol=4.0):                                                      # (ffmpeg's sine is 0.125 at full: vol 4 is an amplitude of 0.5)
    subprocess.run(['ffmpeg', '-y', '-v', 'error', '-f', 'lavfi', '-i', f'sine=frequency={hz}:duration={secs}', '-af', f'volume={vol}', '-ar', '48000', '-ac', '1', path], check=True)


def clip(rd, name, hz, secs=10, role_files=('audio_clean.flac',)):
    d = os.path.join(rd, 'clips', name); os.makedirs(d, exist_ok=True)
    for f in role_files: tone(os.path.join(d, f), hz, secs)


def read(path, ac=1):
    raw = subprocess.run(['ffmpeg', '-v', 'error', '-i', path, '-f', 'f32le', '-ac', str(ac), '-ar', str(SR), '-'], capture_output=True).stdout; x = np.frombuffer(raw, np.float32); return x if ac == 1 else x.reshape(-1, ac).T


def rms(x, a, b): return float(np.sqrt(np.mean(x[int(a * SR):int(b * SR)] ** 2)))


def band(x, a, b, hz):
    seg = x[int(a * SR):int(b * SR)]; t = np.arange(len(seg)) / SR; return float(abs(np.mean(seg * np.exp(-2j * np.pi * hz * t))) * 2)


def window(clip_id, start, dur, role='clip', **kw): return dict(clip=clip_id, clip_start_s=0.0, dur_s=dur, film_start_s=start, speech=role == 'clip', role=role, **kw)


def test_a_plain_cut_between_equal_loud_sounds_does_not_dip(tmp_path):
    f = str(tmp_path); rd = config.race_dir(f); clip(rd, 'A', 600); clip(rd, 'B', 1100)
    plan = dict(film=dict(length_s=4.0), segments=[window('A', 0.0, 2.0), window('B', 2.0, 2.0)]); out = str(tmp_path / 'a.wav'); rep = mix.build_audio(f, plan, out, 4.0); x = read(out)
    ref = rms(x, 0.5, 1.5); frame = int(0.01 * SR); around = [float(np.sqrt(np.mean(x[i:i + frame] ** 2))) for i in range(int(1.9 * SR), int(2.1 * SR), frame)]
    assert rep['windows'] == 2 and min(around) > ref * 10 ** (-1 / 20) and max(around) < ref * 10 ** (1 / 20) and abs(rms(x, 2.5, 3.5) - ref) < 0.02 * ref          # no dip, and no bump, at the join


def test_a_dissolve_crossfades_over_its_own_length_with_both_sounds_present_in_the_middle(tmp_path):
    f = str(tmp_path); rd = config.race_dir(f); clip(rd, 'A', 500); clip(rd, 'B', 1500)
    b = window('B', 2.0, 2.0); b['transition'] = dict(type='dissolve', dur_s=1.0); plan = dict(film=dict(length_s=4.0), segments=[window('A', 0.0, 2.0), b]); out = str(tmp_path / 'a.wav'); mix.build_audio(f, plan, out, 4.0); x = read(out)
    assert band(x, 0.2, 1.3, 500) > 0.4 and band(x, 0.2, 1.3, 1500) < 0.01 and band(x, 2.7, 3.8, 1500) > 0.4 and band(x, 2.7, 3.8, 500) < 0.01        # before the blend only A, after it only B
    assert band(x, 1.8, 2.2, 500) > 0.1 and band(x, 1.8, 2.2, 1500) > 0.1                                                  # at the cut both are there
    assert abs(len(x) / SR - 4.0) < 0.02                                                                                    # the film keeps its length


def test_the_output_is_stereo_a_voice_is_centred_and_a_stereo_music_keeps_its_sides(tmp_path):
    f = str(tmp_path); rd = config.race_dir(f); clip(rd, 'A', 700); os.makedirs(os.path.join(rd, 'music'))
    subprocess.run(['ffmpeg', '-y', '-v', 'error', '-f', 'lavfi', '-i', 'sine=frequency=300:duration=6', '-f', 'lavfi', '-i', 'sine=frequency=900:duration=6', '-filter_complex', '[0:a][1:a]join=inputs=2:channel_layout=stereo', '-ar', '48000', os.path.join(rd, 'music', 'track.wav')], check=True)
    plan = dict(film=dict(length_s=4.0, music=dict(file='music/track.wav', offset_s=0.0)), segments=[window('A', 0.0, 4.0, 'broll')]); plan['segments'][0]['speech'] = False
    out = str(tmp_path / 'a.wav'); mix.build_audio(f, plan, out, 4.0, music_gain=0.5); st = read(out, 2); assert st.shape[0] == 2
    assert band(st[0], 1, 3, 300) > 10 * band(st[0], 1, 3, 900) and band(st[1], 1, 3, 900) > 10 * band(st[1], 1, 3, 300)         # the music: 300 Hz left, 900 Hz right
    clip(rd, 'V', 700); out2 = str(tmp_path / 'b.wav'); mix.build_audio(f, dict(film=dict(length_s=3.0), segments=[window('V', 0.0, 3.0)]), out2, 3.0); v = read(out2, 2)
    assert abs(band(v[0], 0.5, 2.5, 700) - band(v[1], 0.5, 2.5, 700)) < 1e-3 and band(v[0], 0.5, 2.5, 700) > 0.1                  # a voice is the same on both sides


def test_the_music_is_at_least_ten_db_down_within_a_tenth_of_a_second_of_each_voice_over_line(tmp_path):
    f = str(tmp_path); rd = config.race_dir(f); os.makedirs(os.path.join(rd, 'music')); os.makedirs(os.path.join(rd, 'voiceover')); clip(rd, 'A', 700)
    tone(os.path.join(rd, 'music', 'track.wav'), 440, 16, 4.0)
    vo = os.path.join(rd, 'voiceover', 'voiceover.wav')                                                                          # two lines: 2.0 to 3.5 s and 6.0 to 7.0 s, speaking at 300 Hz
    subprocess.run(['ffmpeg', '-y', '-v', 'error', '-f', 'lavfi', '-i', 'sine=frequency=300:duration=16', '-af', "volume=3.0,volume=0:enable='lt(t,2)+between(t,3.5,6)+gt(t,7)'", '-ar', '48000', '-ac', '1', vo], check=True)
    plan = dict(film=dict(length_s=14.0, music=dict(file='music/track.wav', offset_s=0.0)), segments=[window('A', 0.0, 14.0, 'broll')]); plan['segments'][0]['speech'] = False
    out = str(tmp_path / 'a.wav'); mix.build_audio(f, plan, out, 14.0, music_gain=0.5); x = read(out); free = band(x, 0.5, 1.5, 440)
    for start in (2.0, 6.0):
        assert band(x, start, start + 0.1, 440) < free * 10 ** (-10 / 20) and band(x, start + 0.2, start + 0.8, 440) < free * 10 ** (-10 / 20)
    assert band(x, 4.4, 5.4, 440) > 0.8 * free and band(x, 8.5, 9.4, 440) > 0.8 * free                                          # between the lines and after the last one it comes back


def measure(path):
    r = subprocess.run(['ffmpeg', '-v', 'info', '-nostats', '-i', path, '-af', 'ebur128=peak=true', '-f', 'null', '-'], capture_output=True, text=True).stderr; tail = r[r.rindex('Summary'):]
    return float(re.search(r'I:\s+(-?[\d.]+) LUFS', tail).group(1)), float(re.search(r'Peak:\s+(-?[\d.]+) dBFS', tail).group(1))


def test_the_loudness_target_is_met_with_the_true_peak_under_the_limit(tmp_path):
    f = str(tmp_path); rd = config.race_dir(f); os.makedirs(os.path.join(rd, 'music')); clip(rd, 'A', 700, 20); tone(os.path.join(rd, 'music', 'track.wav'), 220, 20, 0.5)
    plan = dict(film=dict(length_s=15.0, music=dict(file='music/track.wav', offset_s=0.0)), segments=[window('A', 0.0, 15.0)])
    quiet = str(tmp_path / 'q.wav'); rep = mix.build_audio(f, plan, quiet, 15.0, music_gain=0.2, loudness=-14.0)
    lufs, peak = measure(quiet); assert abs(lufs + 14.0) <= 0.5 and peak <= -1.0 + 0.1 and rep['loudness']['target_lufs'] == -14.0 and rep['loudness']['measured']['input_lufs'] != lufs      # a quiet mix is brought up to the target and the report says what it was
    loud = str(tmp_path / 'l.wav'); mix.build_audio(f, dict(plan, segments=[dict(plan['segments'][0], dur_s=15.0)]), loud, 15.0, music_gain=1.0, loudness=-14.0); lufs2, peak2 = measure(loud); assert abs(lufs2 + 14.0) <= 0.5 and peak2 <= -0.9
    sil = str(tmp_path / 's.wav'); r = mix.build_audio(f, dict(film=dict(length_s=2.0), segments=[window('nope', 0.0, 2.0)]), sil, 2.0, loudness=-14.0); assert r['loudness']['measured'] is None and os.path.exists(sil)        # silence: nothing to normalise, no failure
