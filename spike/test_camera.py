"""Tests for spike/camera.py. Run: python spike/test_camera.py   (plain asserts; pytest also works)."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from camera import CameraPath, heading_series, limits_report, wrap

FPS = 50.0

def Rz(a):
    c, s = np.cos(a), np.sin(a); return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])

def cams_turning(yaws):                       # a camera whose +Y axis points along E-yaw `yaw` (M = Rz(yaw), so M.T @ Y = (sin yaw, cos yaw, 0))
    return [Rz(y) for y in yaws]

def test_shortest_way_yaw():
    p = CameraPath([dict(t=0, yaw=170), dict(t=1, yaw=-170)], 'world').evaluate(np.arange(0, 1.0001, 0.02))
    assert np.abs(np.diff(p['yaw'])).max() < np.radians(2) , 'yaw must cross the +-180 seam, not swing 340 degrees'
    assert abs(wrap(p['yaw'][-1] - np.radians(-170))) < 1e-6

def test_spline_no_overshoot_and_endpoints():
    p = CameraPath([dict(t=0, fov=90), dict(t=1, fov=90), dict(t=2, fov=60)], 'world').evaluate(np.arange(0, 2.0001, 0.02))
    assert p['fov'].max() <= 90 + 1e-6 and p['fov'].min() >= 60 - 1e-6
    assert abs(p['fov'][0] - 90) < 1e-9 and abs(p['fov'][-1] - 60) < 1e-9

def test_smooth_ease_has_zero_velocity_at_keys():
    t = np.arange(0, 2.0001, 0.02)
    p = CameraPath([dict(t=0, yaw=0, ease='smooth'), dict(t=2, yaw=90)], 'world').evaluate(t)
    v = np.abs(np.diff(p['yaw']) * FPS)
    assert v[0] < 0.05 * v.max() and v[-1] < 0.05 * v.max()

def test_static_path_constant():
    p = CameraPath.static('world', yaw=30, pitch=-5, fov=80).evaluate(np.arange(0, 1, 0.02))
    assert np.allclose(p['yaw'], np.radians(30)) and np.allclose(p['fov'], 80)

def test_heading_rejects_arm_swing():
    t = np.arange(0, 12, 1 / FPS)
    true = np.radians(60) * np.clip((t - 3) / 6, 0, 1)                      # a 60 degree turn between 3 s and 9 s
    swing = np.radians(8) * np.sin(2 * np.pi * 1.8 * t)                     # 8 degree arm swing at 1.8 Hz
    h = heading_series(cams_turning(true + swing), tau_s=1.0, fps=FPS)
    clean = heading_series(cams_turning(true), tau_s=1.0, fps=FPS)
    assert np.abs(h - clean).max() < np.abs(swing).max() / 10, 'arm swing must be filtered out, including at the clip ends (leakage < 10%)'
    assert np.abs(h - clean)[int(2 * FPS):int(-2 * FPS)].max() < np.abs(swing).max() / 100, 'interior leakage < 1%'
    assert np.abs(h - true).max() < np.radians(6), 'and the smoothed heading must still follow the real turn (rounding only)'
    assert abs(h[-1] - np.radians(60)) < np.radians(1)

def test_heading_unwraps_across_seam():
    t = np.arange(0, 6, 1 / FPS); true = np.radians(150) + np.radians(60) * t / 6      # goes from 150 through 180 to 210 degrees
    h = heading_series(cams_turning(wrap(true)), tau_s=0.5, fps=FPS)
    assert np.abs(np.diff(h)).max() < np.radians(3), 'heading must not jump at the +-180 seam'
    assert abs(h[len(h) // 2] - true[len(h) // 2]) < np.radians(2)

def test_heading_does_not_spin_when_axis_vertical():
    # body +Y tilts from horizontal up to (almost) straight up and back: heading undefined at the top, must hold, not spin
    n = int(6 * FPS); t = np.arange(n) / FPS; tilt = np.radians(88) * np.sin(np.pi * t / 6)
    Ms = []
    for k in range(n):                                                          # rotate about world X by -tilt so +Y tips upward
        c, s = np.cos(tilt[k]), np.sin(tilt[k]); R = np.array([[1, 0, 0], [0, c, -s], [0, s, c]])   # body->world
        Ms.append(R.T)
    h = heading_series(Ms, tau_s=0.3, fps=FPS)
    assert np.isfinite(h).all() and np.abs(np.diff(h)).max() < np.radians(2)

def test_limits_report_constant_pan():
    t = np.arange(0, 4, 1 / FPS); p = CameraPath([dict(t=0, yaw=0), dict(t=4, yaw=80, ease='linear')], 'world').evaluate(t)
    r = limits_report(p, FPS)
    assert abs(r['max_speed_deg_s'] - 20) < 1.0 and r['max_accel_deg_s2'] < 5

def test_extra_smoothing_reduces_accel():
    t = np.arange(0, 4, 1 / FPS)
    kf = [dict(t=0, yaw=0, ease='linear'), dict(t=2, yaw=60, ease='linear'), dict(t=4, yaw=0)]
    a = limits_report(CameraPath(kf, 'world').evaluate(t), FPS)['max_accel_deg_s2']
    b = limits_report(CameraPath(kf, 'world', smooth_s=0.3).evaluate(t), FPS)['max_accel_deg_s2']
    assert b < a / 3

def test_mixed_easing_is_flagged():
    from camera import path_warnings
    t = np.arange(0, 4.8, 1 / FPS)
    bad = CameraPath([dict(t=0, yaw=0), dict(t=2, yaw=35, ease='smooth'), dict(t=4.8, yaw=60)], 'world').evaluate(t)
    good = CameraPath([dict(t=0, yaw=0), dict(t=2, yaw=35), dict(t=4.8, yaw=60)], 'world').evaluate(t)
    assert path_warnings(limits_report(bad, FPS), amax=100) and not path_warnings(limits_report(good, FPS), amax=100)

if __name__ == '__main__':
    fns = [v for k, v in sorted(globals().items()) if k.startswith('test_') and callable(v)]
    for f in fns: f(); print('ok  ', f.__name__)
    print(f'{len(fns)} tests passed')
