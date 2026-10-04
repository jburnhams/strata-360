"""Crops cut from the lens frames (analysis/views.py): when a box is re-rendered, the rays of a crop, which lens it needs, and one decode per moment."""
import math

import numpy as np
import pytest

from strata360.analysis import views


def test_a_box_with_enough_pixels_is_cut_from_the_view_a_small_one_is_re_rendered_and_a_speck_is_tiny():
    mode, deg = views.crop_plan([100, 100, 220, 180])                                  # 120 px long: already enough
    assert mode == 'view' and deg == pytest.approx(math.degrees(120 / (512 / math.tan(math.radians(50)))))
    mode, deg = views.crop_plan([100, 100, 160, 140])                                  # 60 px = 8 degrees: the lens frame holds about 160 px of it
    assert mode == 'native' and deg == pytest.approx(8.0, abs=0.1)
    assert views.crop_plan([100, 100, 110, 108])[0] == 'tiny'                          # 10 px = 1.3 degrees: even the lens frame gives 26 px
    assert views.crop_plan([100, 100, 160, 140], native_ppd=9.0)[0] == 'view'          # a lens that adds under 30 percent is not worth the decode


def test_a_crop_is_a_square_of_unit_rays_centred_on_the_direction_with_up_and_right_the_right_way_round():
    lon, lat = 0.3, 0.2; d = views.crop_rays(lon, lat, 40.0, px=5)
    assert d.shape == (5, 5, 3) and np.allclose(np.linalg.norm(d, axis=-1), 1.0)
    assert np.allclose(d[2, 2], [math.sin(lon) * math.cos(lat), math.cos(lon) * math.cos(lat), math.sin(lat)])
    flat = views.crop_rays(0.0, 0.0, 90.0, px=801)
    assert flat[400, 799, 0] > 0 > flat[400, 0, 0] and flat[0, 400, 2] > 0 > flat[799, 400, 2]            # right is +X, the top row looks up
    ang = math.degrees(math.acos(float(np.clip(flat[400, 0] @ flat[400, 799], -1, 1)))); assert ang == pytest.approx(89.86, abs=0.1)         # the field of view across the picture
    assert np.isfinite(views.crop_rays(0.0, math.pi / 2, 30.0, px=4)).all()                                 # straight up: no division by zero


@pytest.mark.parametrize('y, want', [([0.5, 0.9], 'master'), ([-0.5, -0.2], 'slave'), ([0.5, -0.5], 'both'), ([0.05, 0.5], 'both'), ([-0.05, -0.5], 'both')])
def test_which_lens_a_crop_needs_depends_on_the_seam(y, want):
    assert views.lens_choice(np.array(y)) == want


class FakeLens:
    def project(self, d, scale):
        return 31.5 + 30 * d[:, 0], 31.5 - 30 * d[:, 2], np.ones(len(d), bool)


class FakeStab:
    Ms = np.array([np.eye(3)]); master = FakeLens(); slave = FakeLens()


@pytest.fixture
def renderer(monkeypatch):
    decoded = []
    def grab(osv, stream, t, size=0): decoded.append((stream, round(float(t), 3))); return np.full((64, 64, 3), 100 + stream, np.uint8)
    monkeypatch.setattr(views, 'grab_frame', grab); monkeypatch.setattr('strata360.osv.mp4.video_sample_times', lambda osv: np.array([10.0, 10.04, 10.08]))
    return views.CropRenderer('clip.OSV', stab=FakeStab()), decoded


def test_a_crop_ahead_or_behind_decodes_only_its_own_lens_and_one_on_the_seam_blends_both(renderer):
    r, decoded = renderer
    assert (r.crop(0.0, 0.0, 0.0, 20.0, px=16) == 101).all() and decoded == [(1, 10.0)]            # in front: the master lens (stream 1), the other is not decoded
    r2, decoded2 = renderer[0], []
    img = r.crop(0.04, math.pi, 0.0, 20.0, px=16); assert (img == 100).all() and (0, 10.04) in decoded and (1, 10.04) not in decoded           # behind: the slave (stream 0)
    r.crop(0.08, math.pi / 2, 0.0, 30.0, px=16); assert {(0, 10.08), (1, 10.08)} <= set(decoded)           # across the seam: both lenses, blended


def test_all_the_boxes_of_a_moment_come_from_one_decode_and_a_new_moment_decodes_again(renderer):
    r, decoded = renderer
    for lon in (-0.2, 0.0, 0.2): r.crop(0.0, lon, 0.0, 15.0, px=16)
    assert decoded == [(1, 10.0)]                                                                         # three boxes, one frame
    r.crop(0.04, 0.0, 0.0, 15.0, px=16); assert decoded == [(1, 10.0), (1, 10.04)]


def test_the_stabilised_views_can_be_written_at_given_times(monkeypatch, tmp_path):
    import json
    import subprocess
    W, H = 16, 8; side = dict(size=[W, H], frames=[dict(t_s=0.04 * i, source_frame=2 * i) for i in range(100)]); asked = []
    def run(cmd, **kw):
        asked.append(float(cmd[cmd.index('-ss') + 1])); return subprocess.CompletedProcess(cmd, 0, stdout=bytes(W * H * 3))
    monkeypatch.setattr(views.subprocess, 'run', run)
    json.dump(side, open(tmp_path / 'p.json', 'w')); heading = np.zeros(300)
    ks = views._write_stab_views_at(str(tmp_path / 'p.mp4'), side, heading, str(tmp_path), [1.0, 1.01, 2.0], (0, 180), 4, 100.0, 90)
    assert ks == [50, 100] and asked == [pytest.approx(1.0), pytest.approx(2.0)]                    # two times at the same proxy frame are one picture
    assert sorted(p.name for p in tmp_path.glob('s*.jpg')) == ['s00050_v000.jpg', 's00050_v180.jpg', 's00100_v000.jpg', 's00100_v180.jpg']
