import numpy as np
import pytest
from strata360.gps import overview

def test_ascent_descent():
    alt = np.array([
        100.0,
        105.0,
        104.0,
        106.0,
        110.0,
        106.0,
        100.0,
    ])
    up, down = overview.ascent_descent(alt, hysteresis=4.0)
    assert up == 10.0
    assert down == 10.0

def test_ascent_descent_too_short():
    assert overview.ascent_descent(np.array([100.0])) == (0.0, 0.0)

def test_overview(monkeypatch, tmp_path):
    t = np.arange(1000.0, 2000.0, 10.0)
    lat = np.full_like(t, 50.0)
    lat[0] = 49.0
    lat[-1] = 51.0
    lon = np.full_like(t, 4.0)
    alt = np.linspace(100.0, 200.0, len(t))
    speed = np.full_like(t, 2.5)
    hr = np.full_like(t, 150.0)
    dist = np.linspace(0.0, 2500.0, len(t))

    tr = dict(t=t, lat=lat, lon=lon, alt=alt, speed=speed, hr=hr, dist=dist)
    monkeypatch.setattr('strata360.gps.track.load', lambda path: tr)

    out = overview.overview(str(tmp_path / 'fake.gpx'))
    assert out['present']
    assert out['samples'] == 100
    assert out['duration_h'] == 0.28
    assert out['moving_h'] == 0.03
    assert out['distance_km'] == 2.5
    assert out['ascent_m'] == 97
    assert out['descent_m'] == 0
    assert out['avg_speed_kmh'] == 9.0
    assert out['avg_pace_min_km'] == 6.67
    assert out['max_altitude_m'] == 200
    assert out['min_altitude_m'] == 100
    assert out['avg_hr'] == 150
    assert out['max_hr'] == 150
    assert out['gaps_over_10s'] == 0
    assert out['bbox'] == [49.0, 4.0, 51.0, 4.0]
    assert len(out['line']) <= 400

def test_overview_no_positions(monkeypatch, tmp_path):
    tr = dict(t=np.array([1000.0]), lat=np.array([np.nan]), lon=np.array([np.nan]))
    monkeypatch.setattr('strata360.gps.track.load', lambda path: tr)
    out = overview.overview(str(tmp_path / 'fake.gpx'))
    assert out['present']
    assert 'error' in out

def test_overview_missing_fields(monkeypatch, tmp_path):
    t = np.arange(1000.0, 2000.0, 10.0)
    nan_array = np.full_like(t, np.nan)
    tr = dict(t=t, lat=np.full_like(t, 50.0), lon=np.full_like(t, 4.0),
              alt=nan_array, speed=nan_array, hr=nan_array, dist=nan_array)

    monkeypatch.setattr('strata360.gps.track.load', lambda path: tr)
    out = overview.overview(str(tmp_path / 'fake.gpx'))

    assert out['present']
    assert out['distance_km'] is None
    assert out['avg_speed_kmh'] is None
    assert out['avg_pace_min_km'] is None
    assert out['max_altitude_m'] is None
    assert out['min_altitude_m'] is None
    assert out['avg_hr'] is None
    assert out['max_hr'] is None
