"""The 360 version of the final film (render/vr.py, `strata360 final --vr`) on the synthetic clips: equirectangular pieces from the lenses, the film assembled with its sound and marked as a spherical video."""
import json
import os

import pytest

from utils import library

C1, C2 = 'CAM_20260221120007_0019_D', 'CAM_20260221120107_0020_D'


@pytest.fixture
def planned(processed, monkeypatch):
    """The processed project with a two-window plan (a whip between them, which is a cut in 360) and the motion files heading-follow needs."""
    from strata360.edit import project as PJ
    from strata360.pipeline import config
    from strata360.render import flat
    cj = json.load(open(os.path.join(config.race_dir(processed), 'clips', C1, 'clip.json'))); monkeypatch.setattr(flat, 'LS', cj['video']['width']); monkeypatch.setenv('STRATA_RENDER_WORKERS', '1')
    plan = {'film': {'length_s': 1.0, 'bpm': 120, 'music': None}, 'segments': [
        {'id': 'S1', 'clip': C1, 'clip_start_s': 0.0, 'film_start_s': 0.0, 'dur_s': 0.5, 'utc_start': '2026-02-21T12:00:07Z', 'transition': {'type': 'cut', 'dur_s': 0.0}, 'technique': 'hold_wide', 'subject': 'front'},
        {'id': 'S2', 'clip': C2, 'clip_start_s': 0.0, 'film_start_s': 0.5, 'dur_s': 0.5, 'utc_start': '2026-02-21T12:01:07Z', 'transition': {'type': 'whip', 'dur_s': 0.2}, 'technique': 'hold_wide', 'subject': 'front'}]}
    for c in (C1, C2):
        json.dump({'start_utc': '2026-02-21T12:00:07Z', 'duration_s': 1.2, 'dt': 0.1, 't': [0.0, 0.1, 0.2, 0.3], 'world_heading_deg': [0] * 4, 'smooth_heading_deg': [0] * 4, 'bank_deg': [0] * 4, 'v_ground_ms': [0] * 4, 'v_up_ms': [0] * 4},
                  open(os.path.join(config.race_dir(processed), 'clips', c, 'motion.json'), 'w'))
    view = {'mode': 'body', 'fov': 90, 'pitch': 0, 'yaw': 30, 'roll': 0}
    PJ.save(processed, {'plan': plan, 'framing': {'S1': view, 'S2': dict(view, yaw=-60)}}); return processed


def test_the_360_film_is_an_equirectangular_spherical_video_with_the_films_length_and_sound(planned, cli):
    r = cli('final', planned, '--vr', '--size', '128x64', '--fps', '50', '--bitrate', '1M', check=False)
    assert r.code == 0, r.stderr
    root = os.path.join(planned, 'strata360', 'final'); keys = [d for d in os.listdir(root) if len(d) == 10]; film = os.path.join(root, keys[0], 'film-360.mp4')
    probe = library.ffprobe(film); v = next(s for s in probe['streams'] if s['codec_type'] == 'video')
    assert (v['width'], v['height'], v['codec_name']) == (128, 64, 'hevc')
    assert {d['side_data_type']: d.get('projection') for d in v.get('side_data_list', [])}.get('Spherical Mapping') == 'equirectangular'
    assert any(s['codec_type'] == 'audio' for s in probe['streams'])
    assert float(probe['format']['duration']) == pytest.approx(1.0, abs=0.1)
    assert sorted(f for f in os.listdir(os.path.join(root, keys[0])) if f.endswith('.mov')) == ['p0000.mov', 'p0001.mov']          # the whip became a cut: two plain pieces, no transition piece
    assert os.path.exists(os.path.join(root, keys[0], 'timemap.json'))


def test_the_360_film_and_the_flat_film_never_share_pieces(planned, cli):
    cli('final', planned, '--size', '128x64', '--fps', '50', '--bitrate', '1M', '--pieces', '1')
    cli('final', planned, '--vr', '--size', '128x64', '--fps', '50', '--bitrate', '1M', '--pieces', '1')
    assert len([d for d in os.listdir(os.path.join(planned, 'strata360', 'final')) if len(d) == 10]) == 2


def test_a_360_film_must_be_two_to_one(planned, cli):
    r = cli('final', planned, '--vr', '--size', '128x72', '--fps', '50', check=False)
    assert r.code != 0 and '2:1' in (r.stderr + r.stdout)
