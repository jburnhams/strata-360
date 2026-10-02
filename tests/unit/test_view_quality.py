"""analysis/quality_grid.py and edit/view_quality.py (K2): the grid's measurements and the scoring of a view from it, on synthetic grids and pictures."""
import numpy as np
import pytest
from strata360.analysis import quality_grid as QG
from strata360.edit import view_quality as VQ


def grid(n=2, tex=8.0, hi=0.0, lo=0.0, hz=2.0):
    f = lambda v: np.full((n, 12, 24), v, np.float16); return dict(hz=hz, tex=f(tex), clip_hi=f(hi), clip_lo=f(lo))


def test_a_sharp_varied_view_scores_high_a_black_one_near_zero_and_a_blown_out_one_low():
    g = grid(tex=8.0); good = VQ.view_score(g, 0, 0, 0, 100)
    assert good['score'] > 0.7 and good['flat_share'] == 0.0 and good['expo'] == 1.0
    black = VQ.view_score(grid(tex=8.0, lo=0.95), 0, 0, 0, 100); assert black['score'] < 0.05 and black['expo'] == 0.0
    assert VQ.view_score(grid(tex=8.0, hi=0.6), 0, 0, 0, 100)['score'] < 0.05 and VQ.view_score(grid(tex=0.2), 0, 0, 0, 100)['score'] < 0.2                  # blown out; featureless everywhere


def test_a_flat_half_of_the_view_is_penalised_but_a_small_flat_patch_and_an_open_scene_are_not():
    g = grid(tex=8.0); g['tex'][0, :, 12:] = 0.5                                                                    # the half of the sphere behind the view's centre column (yaw 0 is column 12 of 24) is featureless
    half = VQ.view_score(g, 0, 90, 0, 100); clear = VQ.view_score(g, 0, -90, 0, 100)
    assert half['flat_share'] > 0.3 and half['score'] < 0.55 * clear['score'] and clear['flat_share'] == 0.0
    small = grid(tex=8.0); small['tex'][0, 5, 12] = 0.1; s = VQ.view_score(small, 0, 0, 0, 100); assert 0 < s['flat_share'] < VQ.PEN_FROM and s['score'] > 0.7                  # one flat cell: no penalty
    wide_open = grid(tex=5.0); assert VQ.view_score(wide_open, 0, 0, 0, 130)['score'] > 0.55                                                                # a plain but textured landscape is fine


def test_a_view_across_the_wrap_around_column_sees_both_sides_of_it():
    g = grid(tex=8.0); g['tex'][0, :, :4] = 0.2; g['tex'][0, :, 20:] = 0.2                                                  # featureless towards the back (yaw +-180: columns 0 and 23, either side of the wrap-around)
    behind = VQ.view_score(g, 0, 180, 0, 90); assert behind['flat_share'] > 0.6 and behind['score'] < 0.2 and VQ.view_score(g, 0, 0, 0, 90)['flat_share'] == 0.0


def test_the_window_score_averages_the_frames_and_the_best_view_points_at_the_good_side():
    g = grid(n=6, tex=8.0); g['tex'][3:, :, :] = 0.3                                                                 # good for the first 1.5 s (two frames a second), flat after
    a, b = VQ.window_score(g, 0.0, 1.5, 0, 0, 100), VQ.window_score(g, 1.5, 3.0, 0, 0, 100); assert a['score'] > 0.7 and b['score'] < 0.2 and 0.1 < VQ.window_score(g, 0.0, 3.0, 0, 0, 100)['score'] < 0.7
    h = grid(tex=8.0); h['tex'][0, :, :12] = 0.2; best = VQ.best_views(h, 0)[0]; assert best['yaw'] > 0 and best['score'] > 0.5 and VQ.best_views(h, 0)[-1]['score'] <= best['score']       # the left half is flat: the best view looks right


def test_the_measurements_find_detail_blur_haze_and_clipping_in_a_picture():
    rng = np.random.default_rng(1); sharp = rng.integers(0, 255, (QG.H, QG.W, 3), dtype=np.uint8); flat = np.full((QG.H, QG.W, 3), 128, np.uint8); white = np.full((QG.H, QG.W, 3), 255, np.uint8); black = np.zeros((QG.H, QG.W, 3), np.uint8)
    m = QG.measure(sharp); f = QG.measure(flat); assert m['tex'].shape == (12, 24) and set(QG.CHANNELS) == set(m) and m['tex'].mean() > f['tex'].mean() + 3 and f['tex'].max() < 0.01 and f['contrast'].max() < 0.01
    assert QG.measure(white)['clip_hi'].min() == 1.0 and QG.measure(black)['clip_lo'].min() == 1.0 and QG.measure(white)['dark'].min() == 255 and QG.measure(black)['luma'].max() == 0


def test_the_grid_is_made_from_a_video_saved_and_loaded(tmp_path):
    import shutil, subprocess
    if not shutil.which('ffmpeg'): pytest.skip('no ffmpeg')
    v = str(tmp_path / 'p.mp4'); subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'testsrc2=size=640x320:rate=10:duration=3', '-pix_fmt', 'yuv420p', v], check=True)
    seen = []; g = QG.analyse(v, hz=2.0, progress=seen.append); assert g['hz'] == 2.0 and g['tex'].shape == (6, 12, 24) and g['tex'].dtype == np.float16 and seen[-1] == 6 and VQ.view_score(g, 3, 0, 0, 100)['score'] >= 0
    QG.save(str(tmp_path / QG.FILE), g); back = QG.load(str(tmp_path)); assert back['hz'] == 2.0 and np.array_equal(back['luma'], g['luma']) and QG.load(str(tmp_path / 'none')) is None
    with pytest.raises(RuntimeError, match='no frames'): QG.analyse(str(tmp_path / 'missing.mp4'))
