"""render/grade.py (A4): exposure matching between shots."""
import json, os
import numpy as np
import pytest
from strata360.analysis import quality_grid as QG
from strata360.render import grade as GR

K = dict(heading=lambda t: 0.0)


def project(tmp_path, lumas, n=40):
    """A project folder with one clip per entry of `lumas`: its quality grid holds that luma (a code value 0..255) everywhere."""
    for i, v in enumerate(lumas):
        d = tmp_path / 'strata360' / 'clips' / f'c{i}'; d.mkdir(parents=True); g = dict(hz=2.0, luma=np.full((n, 12, 24), v, np.float16)); QG.save(str(d / QG.FILE), g)
    return str(tmp_path)


def segs(clips, dur=4.0, **kw):
    out = []
    for k, c in enumerate(clips): out.append(dict(id=f'w{k}', clip=c, clip_start_s=2.0, dur_s=dur, film_start_s=k * dur, **kw))
    return out


def path(): return dict(ref='world', keyframes=[dict(t=0, yaw=0, pitch=0, fov=90), dict(t=4, yaw=0, pitch=0, fov=90)])


def level(code): return float(np.log2(GR.code_to_lin(code / 255.0)))


def test_the_transfer_functions_are_inverses_and_the_lut_is_a_linear_light_gain():
    x = np.linspace(0, 1, 11); assert np.allclose(GR.lin_to_code(GR.code_to_lin(x)), x, atol=1e-6)
    lut = GR.lut(1.0, 8); assert lut[0] == 0 and lut[255] >= 254 and (np.diff(lut.astype(int)) >= 0).all()                    # a stop up: monotonic, black stays black, white stays white (nothing is clipped that was not)
    mid = 100; assert abs(np.log2(GR.code_to_lin(lut[mid] / 255.0) / GR.code_to_lin(mid / 255.0)) - 1.0) < 0.05                # in the dark and mid range it is exactly a stop of linear light
    assert (GR.lut(-1.0, 8)[1:200] <= np.arange(1, 200)).all() and np.array_equal(GR.lut(0.0, 8), np.arange(256)) and GR.lut(1.0, 16).dtype == np.uint16 and len(GR.lut(1.0, 16)) == 65536


def test_apply_grades_both_depths_and_leaves_a_nil_gain_alone():
    a8 = np.full((4, 4, 3), 100, np.uint8); a16 = np.full((4, 4, 3), 25700, np.uint16)
    assert GR.apply(a8, 0.0) is a8 and GR.apply(a8, 0.004) is a8 and GR.apply(a8, 1.0).mean() > 100 and GR.apply(a16, 1.0).dtype == np.uint16 and GR.apply(a16, -1.0).mean() < 25700
    with pytest.raises(TypeError): GR.apply(np.zeros((2, 2, 3), np.float32), 1.0)


def test_a_highlight_is_rolled_off_not_clipped_when_brightened():
    img = np.array([[[190, 220, 245]]], np.uint8); out = GR.apply(img, 0.7)[0, 0]
    assert out[0] < out[1] <= out[2] and out[2] <= 255 and len({int(v) for v in out}) == 3                                    # the three levels stay apart: no flat white blob


def test_the_gain_of_a_window_eases_from_the_gain_that_matches_the_previous_cut():
    g = GR.Gain(base=0.2, match=-0.6, nudge=0.1)
    assert g(0.0) == pytest.approx(-0.5) and g(100.0) == pytest.approx(0.3, abs=1e-3) and g(0.3) > g(0.0) and g(-5.0) == g(0.0)


def test_two_windows_at_different_brightness_meet_at_the_same_brightness_at_the_cut(tmp_path):
    f = project(tmp_path, [90, 135])                                                                                             # luma codes about 0.35 and 0.53: about 1.2 stops apart
    gains = GR.plan_gains(f, segs(['c0', 'c1']), {'w0': path(), 'w1': path()}, heading_of=lambda c: (lambda t: 0.0))
    la, lb = level(90), level(135); end_a = la + gains['w0'](4.0); start_b = lb + gains['w1'](0.0)
    assert abs(2 ** end_a / 2 ** start_b - 1) < 0.10                                                                             # the cut does not jump in brightness (within 10 percent)
    assert gains['w0'].base > 0 > gains['w1'].base and (lb + gains['w1'].base) > (la + gains['w0'].base)                          # the brighter shot stays the brighter
    far = GR.plan_gains(project(tmp_path / 'far', [20, 200]), segs(['c0', 'c1']), {'w0': path(), 'w1': path()}, heading_of=lambda c: (lambda t: 0.0))      # a huge gap: nothing is moved more than the cap
    assert all(abs(g(t)) <= GR.CAP_STOPS + 1e-9 for g in far.values() for t in (0.0, 1.0, 4.0))


def test_a_night_window_stays_dark_and_a_synthetic_one_breaks_the_chain(tmp_path):
    f = project(tmp_path, [4, 150, 150]); sg = segs(['c0', 'c1', 'c2']); sg.insert(1, dict(id='gen', clip='G1', synthetic='/x.mp4', clip_start_s=0.0, dur_s=3.0, film_start_s=4.0))
    fr = {s['id']: path() for s in sg}; gains = GR.plan_gains(f, sg, fr, heading_of=lambda c: (lambda t: 0.0))
    assert 'gen' not in gains and gains['w0'].base <= GR.CAP_NIGHT_UP + 1e-9                                                    # the night is brightened by a little at most
    assert gains['w1'].match == gains['w1'].base                                                                                  # nothing before it to match (the generated clip broke the chain)
    assert GR.plan_gains(f, [dict(id='x', clip='nope', clip_start_s=0.0, dur_s=2.0)], {'x': path()}) == {}                       # no quality grid: no gain


def test_the_nudge_in_the_plan_is_added_and_a_body_frame_view_uses_the_whole_sphere(tmp_path):
    f = project(tmp_path, [120]); s = segs(['c0'], grade_ev=0.4); g = GR.plan_gains(f, s, {'w0': path()}, heading_of=lambda c: (lambda t: 0.0))['w0']; assert g.nudge == 0.4 and g(1.0) == pytest.approx(g.base + g.nudge + (g.match - g.base) * np.exp(-1 / GR.EASE_S))
    body = dict(ref='body', keyframes=[dict(t=0, yaw=180, pitch=0, fov=85), dict(t=4, yaw=180, pitch=0, fov=85)])
    ts, lv = GR.view_levels(QG.load(str(tmp_path / 'strata360' / 'clips' / 'c0')), body, 4.0, 2.0); assert np.allclose(lv, level(120), atol=0.02) and len(ts) == 9


def test_the_grade_can_be_switched_off(tmp_path, monkeypatch):
    f = project(tmp_path, [76, 153]); s = segs(['c0', 'c1']); fr = {'w0': path(), 'w1': path()}
    monkeypatch.setenv('STRATA_GRADE', '0'); assert GR.on(f) is False and GR.gains_for(f, s, fr) == {}
    monkeypatch.delenv('STRATA_GRADE'); assert GR.on(f) is True and set(GR.gains_for(f, s, fr)) == {'w0', 'w1'}
