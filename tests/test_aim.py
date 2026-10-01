import math
import numpy as np
from strata360.edit import aim


def run(ty, tp, T, dt=0.04, y0=None, p0=None):
    t = np.arange(0, T, dt); y, p = aim.follow(t, [ty(x) for x in t], [tp(x) for x in t], dt); return t, np.unwrap(np.radians(y)) * 180 / math.pi, np.array(p)


def test_jitter_inside_the_band_does_not_move():
    t, y, p = run(lambda x: 100 + 5 * math.sin(x * 7), lambda x: -20 + 3 * math.sin(x * 5), 20)
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


def test_aim_puts_the_head_near_the_top():
    vf = aim.vfov_deg(100)
    a = aim.aim_pitch(-30, 47, vf)                                                  # body centre -30, 47 deg tall: head at -6.5, aim below it by 0.42 of the frame
    assert a < -30 + 47 / 2 and a >= -30 - 47 / 2
    assert aim.aim_pitch(-30, 47, vf) == aim.aim_pitch(-30, 47, vf)
