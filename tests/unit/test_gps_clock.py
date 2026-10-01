import numpy as np
import pytest
from hypothesis import given, strategies as st
from strata360.gps import clock

def test_step_windows_finds_peaks():
    fps = 50
    t = np.arange(0, 10, 1.0/fps)
    acc = 9.8 + 2.0 * np.sin(2 * np.pi * 2.0 * t)

    out = clock.step_windows(acc, t, fps)

    assert len(out) > 0
    assert out[0, 0] >= 2.0
    np.testing.assert_allclose(out[:, 1], 2.0, atol=0.2)
    assert (out[:, 2] > 0.4).all()

def test_step_windows_ignores_weak_signals():
    fps = 50
    t = np.arange(0, 10, 1.0/fps)
    acc = np.random.normal(0, 0.1, len(t))
    out = clock.step_windows(acc, t, fps)
    if len(out) > 0:
        assert (out[:, 2] < 0.4).all()

def test_step_series(monkeypatch):
    def mock_read_frames(osv):
        fps = 50
        t_us = np.arange(0, 10_000_000, 1_000_000 / fps)
        t = t_us / 1e6
        acc = np.zeros((len(t), 3))
        acc[:, 2] = 9.8 + 2.0 * np.sin(2 * np.pi * 2.0 * t)
        return dict(ts_us=t_us, acc=acc)

    monkeypatch.setattr(clock, 'read_frames', mock_read_frames)

    out = clock.step_series("fake.osv")
    assert len(out) > 0
    np.testing.assert_allclose(out[:, 1], 2.0, atol=0.2)


def test_estimate():
    T = np.arange(0, 100, 1.0)
    C = np.full(100, 60.0)
    speed = np.full(100, 3.0)
    track = dict(t=T, cadence=C, speed=speed)

    series = [(10.0, np.array([[float(i), 2.0, 0.8] for i in range(35)]))]

    offsets = [-10.0, 0.0, 10.0]
    score, n = clock.estimate(series, track, offsets)

    assert n == 35
    assert len(score) == 3
    assert np.nanmean(score) < 0.1

def test_estimate_insufficient_samples():
    T = np.arange(0, 100, 1.0)
    track = dict(t=T, cadence=np.full(100, 60.0), speed=np.full(100, 3.0))
    series = [(10.0, np.array([[float(i), 2.0, 0.8] for i in range(15)]))]
    score, n = clock.estimate(series, track, [0.0])
    assert n == 15
    assert np.isnan(score[0])

def test_estimate_empty_series():
    T = np.arange(0, 100, 1.0)
    track = dict(t=T, cadence=np.full(100, 60.0), speed=np.full(100, 3.0))
    score, n = clock.estimate([], track, [0.0, 1.0])
    assert n == 0
    assert np.isnan(score).all()

@given(
    lat=st.floats(min_value=-90, max_value=90),
    lon=st.floats(min_value=-180, max_value=180),
    t=st.floats(min_value=0, max_value=2_000_000_000)
)
def test_sun_elevation_bounds(lat, lon, t):
    el = clock.sun_elevation_deg(lat, lon, t)
    assert -90.1 <= el <= 90.1

def test_scene_brightness():
    exp = dict(frames=[
        dict(t_s=0.1, camera=dict(shutter_den=[100, 100], iso=[100, 100])),
        dict(t_s=0.2, camera=dict(shutter_den=[200, 200], iso=[100, 100])),
        dict(t_s=0.3, camera=dict(shutter_den=[100, 100], iso=[200, 200])),
    ])
    t, b = clock.scene_brightness(exp)
    np.testing.assert_allclose(t, [0.1, 0.2, 0.3])
    np.testing.assert_allclose(b, [0.0, 1.0, -1.0])
