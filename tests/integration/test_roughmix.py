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
