"""Music analysis on a synthetic track."""
import json, os, subprocess, shutil
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


class TestMusicRecord:
    """music.json: the track's file name and its analysis, waveform and spectrogram, saved when it is uploaded."""

    def test_store_writes_the_record_and_the_spectrogram(self, tmp_path):
        rd = str(tmp_path); data = open(make_track(str(tmp_path / 'src.wav'), 124.0, 1.3, 30), 'rb').read()
        rec = M.store(rd, data, '.wav', 'my song.wav')
        saved = json.load(open(os.path.join(rd, 'music.json')))
        assert saved['file'] == 'music/track.wav' and saved['name'] == 'my song.wav' and abs(saved['analysis']['bpm'] - 124.0) < 0.6 and rec['analysis'] == saved['analysis']
        assert len(saved['waveform']) == M.PEAKS and max(saved['waveform']) == 1.0
        assert open(os.path.join(rd, saved['spectrogram']), 'rb').read(8) == b'\x89PNG\r\n\x1a\n'

    def test_info_reuses_the_record_until_the_file_changes(self, tmp_path):
        rd = str(tmp_path); M.store(rd, open(make_track(str(tmp_path / 'src.wav'), 124.0, 1.3, 30), 'rb').read(), '.wav', 'a.wav')
        mj = os.path.join(rd, 'music.json'); stamp = os.stat(mj).st_mtime_ns
        assert M.info(rd, 'music/track.wav')['name'] == 'a.wav' and os.stat(mj).st_mtime_ns == stamp
        make_track(os.path.join(rd, 'music', 'track.wav'), 100.0, 0.5, 30)                          # the file is replaced behind our back
        r = M.info(rd, 'music/track.wav'); assert abs(r['analysis']['bpm'] - 100.0) < 0.6 and r['name'] == 'a.wav'

    def test_an_unreadable_upload_leaves_the_current_track_alone(self, tmp_path):
        rd = str(tmp_path); M.store(rd, open(make_track(str(tmp_path / 'src.wav'), 124.0, 1.3, 30), 'rb').read(), '.wav', 'good.wav')
        with pytest.raises(RuntimeError): M.store(rd, b'not audio at all' * 500, '.mp3', 'bad.mp3')
        assert json.load(open(os.path.join(rd, 'music.json')))['name'] == 'good.wav' and not os.path.exists(os.path.join(rd, 'music', 'incoming.mp3')) and os.path.exists(os.path.join(rd, 'music', 'track.wav'))

    def test_a_new_track_keeps_the_old_one_aside(self, tmp_path):
        rd = str(tmp_path); a = open(make_track(str(tmp_path / 'a.wav'), 124.0, 1.3, 30), 'rb').read(); M.store(rd, a, '.wav', 'a.wav'); M.store(rd, a, '.wav', 'b.wav')
        assert os.path.exists(os.path.join(rd, 'music', 'track.wav.replaced')) and json.load(open(os.path.join(rd, 'music.json')))['name'] == 'b.wav'

    def test_remove_forgets_the_record(self, tmp_path):
        rd = str(tmp_path); M.store(rd, open(make_track(str(tmp_path / 'a.wav'), 124.0, 1.3, 30), 'rb').read(), '.wav', 'a.wav'); M.remove(rd)
        assert not os.path.exists(os.path.join(rd, 'music.json')) and not os.path.exists(os.path.join(rd, 'music', 'spectrogram.png'))


def test_the_music_is_turned_down_under_the_runners_own_speech_and_only_there(tmp_path):
    f = str(tmp_path); rd = config.race_dir(f); os.makedirs(os.path.join(rd, 'music'))
    make_track(os.path.join(rd, 'music', 'track.wav'), 124.0, 1.3, 30)
    seg = lambda t0, role: dict(clip='X', clip_start_s=0.0, dur_s=4.0, film_start_s=t0, speech=role == 'clip', role=role)
    plan = dict(film=dict(music=dict(file='music/track.wav', offset_s=0.0)), segments=[seg(0.0, 'broll'), seg(4.0, 'clip'), seg(8.0, 'broll')])
    out = os.path.join(f, 'a.wav'); PV.build_audio(f, plan, out, 12.0, music_gain=0.5)
    raw = subprocess.run(['ffmpeg', '-v', 'error', '-i', out, '-f', 'f32le', '-ac', '1', '-ar', '8000', '-'], capture_output=True).stdout; a = np.frombuffer(raw, np.float32)
    rms = lambda t0, t1: float(np.sqrt(np.mean(a[int(t0 * 8000):int(t1 * 8000)] ** 2)))
    assert rms(4.5, 7.5) < 0.6 * rms(0.5, 3.5) and rms(8.5, 11.0) > 0.7 * rms(0.5, 3.5)                       # down by about 8 dB inside the window, back up after it
    assert PV.music_duck(dict(segments=[])) == '' and PV.music_duck(plan).count('clip(') == 1
