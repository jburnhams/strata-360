"""The rough mix (edit/roughmix.py): the film's sound alone, music and clip background turned down, the voice-over and the runner's speech up."""
import json, os, subprocess
import numpy as np
import pytest
from strata360.edit import roughmix as RM, project as PJ, voiceover as V
from strata360.pipeline import config
from library import make_track


def seg(clip, role, speech): return dict(clip=clip, clip_start_s=0.0, dur_s=4.0, speech=speech, role=role)


@pytest.fixture
def folder(tmp_path):
    f = str(tmp_path / 'trip'); rd = config.race_dir(f); os.makedirs(os.path.join(rd, 'music')); os.makedirs(os.path.join(rd, 'voiceover'))
    make_track(os.path.join(rd, 'music', 'track.wav'), 124.0, 1.3, 30)
    edit = PJ.load(f); edit['plan'] = dict(source='script', film=dict(length_s=8.0, music=dict(file='music/track.wav', offset_s=1.3)), segments=[seg('X', 'vo', False), seg('Y', 'clip', True)]); PJ.save(f, edit); return f


def levels(path, a, b):
    raw = subprocess.run(['ffmpeg', '-v', 'error', '-i', path, '-f', 'f32le', '-ac', '1', '-ar', '8000', '-'], capture_output=True).stdout; x = np.frombuffer(raw, np.float32)[int(a * 8000):int(b * 8000)]; return float(np.sqrt(np.mean(x ** 2)))


def test_the_rough_mix_is_made_with_the_music_turned_down_and_is_then_up_to_date(folder):
    assert RM.status(folder) == dict(has_plan=True, exists=False, stale=False, stale_because=[], length_s=None, made_at=None, source='script')
    log = []; st = RM.build(folder, log=log.append); p = RM.path_of(folder)
    assert st['exists'] and not st['stale'] and st['length_s'] == 8.0 and abs(V.duration(p) - 8.0) < 0.2 and os.path.exists(os.path.join(RM.dir_of(folder), 'mix.json')) and not os.path.exists(os.path.join(RM.dir_of(folder), 'mix.part.wav'))
    full = os.path.join(folder, 'full.wav'); from strata360.render import preview as PV; PV.build_audio(folder, PJ.load(folder)['plan'], full, 8.0)
    assert levels(p, 1.0, 6.0) < 0.75 * levels(full, 1.0, 6.0)                                                      # the rough mix has the music well below the film's own level


def test_a_changed_plan_or_voice_over_makes_the_mix_stale(folder):
    RM.build(folder); assert not RM.status(folder)['stale']
    edit = PJ.load(folder); edit['plan']['segments'][0]['dur_s'] = 3.5; PJ.save(folder, edit); st = RM.status(folder); assert st['stale'] is True and st['stale_because'] == ['plan']
    RM.build(folder); assert RM.status(folder)['stale'] is False
    vo = os.path.join(config.race_dir(folder), 'voiceover', 'voiceover.wav'); subprocess.run(['ffmpeg', '-y', '-v', 'error', '-f', 'lavfi', '-i', 'sine=frequency=300:duration=3', vo], check=True); os.utime(vo, (4102444800, 4102444800))
    st = RM.status(folder); assert st['stale'] is True and st['stale_because'] == ['voice-over']


def test_with_no_plan_it_says_so(tmp_path):
    f = str(tmp_path / 'empty'); os.makedirs(config.race_dir(f))
    assert RM.status(f)['has_plan'] is False
    with pytest.raises(RuntimeError, match='no film plan'): RM.build(f)


def test_reset_forgets_the_mix_and_a_new_version_makes_every_mix_stale(folder, monkeypatch):
    RM.build(folder); assert RM.reset(folder) is True and not RM.status(folder)['exists'] and not os.path.exists(RM.path_of(folder)) and RM.reset(folder) is False
    RM.build(folder); monkeypatch.setattr(RM, 'VERSION', RM.VERSION + 1); st = RM.status(folder); assert st['stale'] is True and st['stale_because'] == ['settings']


def test_a_dialogue_window_plays_the_clips_voice_only_over_the_wanted_lines_and_the_background_elsewhere(tmp_path):
    from strata360.render import preview as PV
    f = str(tmp_path / 'trip'); rd = config.race_dir(f); cdir = os.path.join(rd, 'clips', 'Y'); os.makedirs(cdir)
    tone = lambda path, hz, vol: subprocess.run(['ffmpeg', '-y', '-v', 'error', '-f', 'lavfi', '-i', f'sine=frequency={hz}:duration=6', '-af', f'volume={vol}', path], check=True)
    tone(os.path.join(cdir, 'audio_clean.flac'), 1000, 0.8); tone(os.path.join(cdir, 'audio_background.flac'), 200, 0.2)                 # the "speech" is the loud 1 kHz tone, the background the quiet 200 Hz one
    w = dict(clip='Y', clip_start_s=0.0, dur_s=4.0, speech=True, role='clip', voice_span=[1.0, 2.5])                                      # the lines the script wants fill 1.0 to 2.5 s of the 4 s window
    out = str(tmp_path / 'a.wav'); PV.build_audio(f, dict(segments=[w], film=dict(length_s=4.0)), out, 4.0)
    def band(a, b, hz):
        raw = subprocess.run(['ffmpeg', '-v', 'error', '-i', out, '-f', 'f32le', '-ac', '1', '-ar', '8000', '-'], capture_output=True).stdout; x = np.frombuffer(raw, np.float32)[int(a * 8000):int(b * 8000)]; t = np.arange(len(x)) / 8000.0
        return float(abs(np.mean(x * np.exp(-2j * np.pi * hz * t))) * 2)                                                                  # the level of one frequency
    assert band(1.2, 2.3, 1000) > 0.07 and band(1.2, 2.3, 200) < 0.002                       # inside the wanted lines: the voice, not the background
    assert band(0.1, 0.8, 1000) < 0.002 and band(0.1, 0.8, 200) > 0.004 and band(3.0, 3.9, 1000) < 0.002 and band(3.0, 3.9, 200) > 0.004          # before and after: the background only, no voice
    w2 = dict(w, voice_span=None); PV.build_audio(f, dict(segments=[w2], film=dict(length_s=4.0)), out, 4.0); assert band(3.0, 3.9, 1000) > 0.07                  # no span known (an older plan): the whole window as before


def test_music_the_cuts_start_after_the_film_does_is_delayed_in_the_mix(folder):
    from strata360.render import preview as PV
    out = os.path.join(folder, 'late.wav'); plan = PJ.load(folder)['plan']; PV.build_audio(folder, plan, out, 8.0); assert levels(out, 0.0, 1.4) > 0.004                                    # from its first downbeat at once
    plan['film']['music'] = dict(file='music/track.wav', offset_s=1.3, delay_s=1.5, synced=True); PV.build_audio(folder, plan, out, 8.0)
    assert levels(out, 0.0, 1.4) < 0.002 and levels(out, 1.6, 6.0) > 0.004                                                                  # 1.5 s of silence, then the music
