"""analysis/sampling.py: the moments to look at are chosen by distance moved and scene change, with the sharpest picture near each, and a fixed interval is the fallback when there is nothing to decide with."""
import json

import numpy as np
import pytest

from strata360.analysis import sampling as SP

HZ = SP.HZ


def test_a_running_clip_gets_a_moment_every_few_metres_and_a_standing_one_only_the_longest_gap():
    n = int(60 * HZ); run = SP.adaptive_times(60, speed=np.full(n, 2.5)); stand = SP.adaptive_times(60, speed=np.zeros(n))
    assert run[0] == 1.0 and all(abs((b - a) - 2.0) < 0.01 for a, b in zip(run, run[1:]))                    # 5 m at 2.5 m/s: every 2 s
    assert len(stand) == 1 + int((60 - 1) // SP.MAXGAP_S) and all(abs((b - a) - SP.MAXGAP_S) < 0.01 for a, b in zip(stand, stand[1:]))
    assert len(run) > 2 * len(stand)


def test_a_change_in_the_scene_asks_for_a_moment_and_never_sooner_than_the_minimum_gap():
    n = int(40 * HZ); g = np.random.default_rng(0).normal(0, 0.1, (n, 64)); g[int(20 * HZ):] += 5.0                               # a jump at 20 s on top of the usual small changes
    t = SP.adaptive_times(40, grid=g); assert any(19.5 <= x <= 20.6 for x in t) and all(b - a >= SP.MINGAP_S - 1e-9 for a, b in zip(t, t[1:]))


def test_the_moment_moves_to_the_sharpest_picture_just_before_it():
    n = int(30 * HZ); sharp = np.zeros(n); sharp[int(round(5.5 * HZ))] = 9.0                                              # the sharpest of the seconds before the trigger at 6 s
    t = SP.adaptive_times(30, speed=np.full(n, 1.0), sharp=sharp, dist_m=5.0, maxgap_s=100); assert 5.5 in t and 6.0 not in t
    t = SP.adaptive_times(30, speed=np.full(n, 1.0), sharp=None, dist_m=5.0, maxgap_s=100); assert 6.0 in t


def test_nothing_to_decide_with_means_no_adaptive_answer_and_a_very_short_clip_is_one_moment():
    assert SP.adaptive_times(60) is None
    assert SP.adaptive_times(1.0, speed=np.zeros(2)) == [0.5]


def test_the_inputs_are_read_from_the_clip_folder_and_the_track_and_each_part_may_be_missing(tmp_path, monkeypatch):
    assert SP.load_inputs(str(tmp_path)) == (None, None, None, None) and SP.times_for(str(tmp_path)) is None                # no clip.json
    json.dump(dict(video=dict(source_frames=1500, nominal_fps=25.0), time=dict(start_utc='2026-02-20T10:00:00Z')), open(tmp_path / 'clip.json', 'w'))
    dur, speed, grid, sharp = SP.load_inputs(str(tmp_path)); assert dur == 60.0 and speed is None and grid is None and sharp is None
    n = 120; z = np.zeros((n, 2, 2), np.float16); np.savez(tmp_path / 'quality_grid.npz', hz=HZ, luma=z + 1, fine=z + 2, blur=z + 3)
    dur, speed, grid, sharp = SP.load_inputs(str(tmp_path)); assert grid.shape == (120, 8) and sharp.shape == (120,) and float(sharp[0]) == 3.0
    t0 = 1771581600.0                                                                                                     # 2026-02-20T10:00:00Z
    monkeypatch.setattr('strata360.gps.track.load', lambda p: dict(t=np.array([t0 + 10, t0 + 50]), speed=np.array([2.0, 2.0])))
    dur, speed, grid, sharp = SP.load_inputs(str(tmp_path), 'x.fit'); assert speed.shape == (120,) and speed[0] == 0.0 and speed[40] == 2.0 and speed[-1] == 0.0       # not moving where the track is not known
    monkeypatch.setattr('strata360.gps.track.load', lambda p: (_ for _ in ()).throw(OSError('gone'))); assert SP.load_inputs(str(tmp_path), 'x.fit')[1] is None
