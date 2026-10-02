import math
import numpy as np
from strata360.edit import aim


def run(ty, tp, T, dt=0.04):
    t = np.arange(0, T, dt); y, p = aim.follow(t, [ty(x) for x in t], [tp(x) for x in t], dt); return t, np.unwrap(np.radians(y)) * 180 / math.pi, np.array(p)


def test_jitter_inside_the_band_does_not_move():
    t, y, p = run(lambda x: 100 + 5 * math.sin(x * 7), lambda x: -20 + 2 * math.sin(x * 5), 20)
    assert np.ptp(y) < 0.01 and np.ptp(p) < 0.01


def test_slow_drift_pans_smoothly_and_never_reverses():
    t, y, p = run(lambda x: 100 + 2.0 * x, lambda x: -20.0, 30)
    v = np.diff(y) / 0.04
    assert v.min() > -0.5 and v.max() <= aim.PAN_DEG_S + 0.5                       # forward only, speed limited
    assert abs(y[-1] - (100 + 60)) < aim.BAND_YAW + 1                              # still with the person at the end


def test_large_move_is_one_quick_move():
    t, y, p = run(lambda x: 100.0 if x < 5 else 190.0, lambda x: -20.0, 12)
    v = np.diff(y) / 0.04; moving = v > 1
    assert abs(y[-1] - 190) < 2
    edges = np.flatnonzero(np.diff(moving.astype(int)) == 1); assert len(edges) == 1   # a single move
    assert moving.sum() * 0.04 < 1.2                                                # done within about a second of starting
    assert v.min() > -0.5                                                           # never goes back


def test_the_head_is_always_in_frame_and_the_body_as_far_as_fits():
    vf = aim.vfov_deg(100)
    for pitch, h in ((-30, 47), (-30, 70), (-20, 15)):
        top = pitch + h / 2; a = aim.aim_pitch(pitch, h, vf, top)
        assert top - (a - aim.BAND_PITCH) <= (0.5 - aim.HEAD_MARGIN) * vf + 1e-6          # even with the camera at the low end of its dead band the head is inside the margin
    tall = aim.aim_pitch(-30, 70, vf, -30 + 35); small = aim.aim_pitch(-30, 15, vf, -30 + 7.5)
    assert tall < -30 + 35                                                                  # a tall person: aimed below the head, the head near the top
    assert small == -30                                                                     # a person who fits easily: centred


def test_a_narrower_view_has_a_narrower_dead_band_so_you_stay_in_frame():
    ty = lambda x: 100 + 6.0 * min(x, 3) / 3          # you drift 6 degrees: inside the usual 9 degree band, outside a band scaled to a 50 degree view
    _, y_wide, _ = run(ty, lambda x: -20.0, 8); t = np.arange(0, 8, 0.04); y_n, _ = aim.follow(t, [ty(x) for x in t], [-20.0] * len(t), 0.04, scale=50 / 85)
    assert np.ptp(y_wide) < 0.01 and abs(np.unwrap(np.radians(y_n))[-1] * 180 / math.pi - 106) < abs(y_wide[-1] - 106)
    assert aim.Follower(0, 0, 0.5).by == aim.BAND_YAW / 2 and aim.Follower(0, 0).by == aim.BAND_YAW
