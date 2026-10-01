import numpy as np
import pytest
from strata360.gps.overview import ascent_descent, overview

class TestAscentDescent:
    def test_empty_or_single_point(self):
        up, down = ascent_descent(np.array([]))
        assert up == 0.0 and down == 0.0
        up, down = ascent_descent(np.array([100.0]))
        assert up == 0.0 and down == 0.0

    def test_hysteresis(self):
        # goes up 3m, down 3m, up 3m (all within default 4.0 hysteresis)
        alt = np.array([100.0, 103.0, 100.0, 103.0])
        up, down = ascent_descent(alt)
        assert up == 0.0 and down == 0.0

        # goes up 5m (record), down 2m (ignore), down 3m (total down 5m from 105 -> record)
        alt = np.array([100.0, 105.0, 103.0, 100.0])
        up, down = ascent_descent(alt)
        assert up == 5.0 and down == 5.0

        # monotonic climb
        alt = np.array([100.0, 105.0, 110.0, 115.0, 120.0])
        up, down = ascent_descent(alt)
        assert up == 20.0 and down == 0.0

    def test_nans_ignored(self):
        alt = np.array([100.0, np.nan, 110.0, np.nan, 100.0])
        up, down = ascent_descent(alt)
        assert up == 10.0 and down == 10.0

class TestOverview:
    def make_track(self, valid_positions=True):
        n = 1000
        # t increases by 1s usually, but we inject a gap > 10s at index 500
        t = np.arange(1000.0, 1000.0 + n)
        t[501:] += 15.0 # gap of 16s between 500 and 501

        lat = np.linspace(50.0, 50.1, n)
        lon = np.linspace(4.0, 4.1, n)
        if not valid_positions:
            lat = np.full(n, np.nan)
            lon = np.full(n, np.nan)

        alt = np.linspace(100.0, 200.0, n) # up=100
        speed = np.ones(n) * 3.0 # 3 m/s = 10.8 km/h
        # 10 points have 0 speed
        speed[:10] = 0.0

        hr = np.ones(n) * 150.0
        hr[-1] = 180.0
        cadence = np.ones(n) * 80.0
        dist = np.linspace(0, 10000.0, n)

        return dict(t=t, lat=lat, lon=lon, alt=alt, speed=speed, hr=hr, cadence=cadence, dist=dist)

    def test_no_positions(self, monkeypatch):
        called = False
        def mock_load(path):
            nonlocal called
            called = True
            return self.make_track(valid_positions=False)
        monkeypatch.setattr('strata360.gps.overview.track.load', mock_load)

        res = overview("fake.gpx")
        assert called
        assert res['present'] is True
        assert res['error'] == 'the file has no positions'

    def test_happy_path(self, monkeypatch):
        def mock_load(path):
            return self.make_track(valid_positions=True)
        monkeypatch.setattr('strata360.gps.overview.track.load', mock_load)

        # request 10 points for line
        res = overview("fake.gpx", points=10)

        assert res['present'] is True
        assert 'error' not in res
        assert res['file'] == 'fake.gpx'
        assert res['samples'] == 1000
        assert res['start_utc'] == '1970-01-01T00:16:40Z'
        # duration is 1000s + 14s gap = 1014s = 0.28h
        assert res['duration_h'] == 0.28
        # moving time is 990 points = 990/3600 = 0.28h
        assert np.isclose(res['moving_h'], 0.28)
        assert res['distance_km'] == 10.0
        # Hysteresis requires 4m delta before registering climb.
        # altitude goes from 100 to 200 linearly over 1000 points.
        # it counts chunks. 100 - 4 = 96m recorded?
        assert res['ascent_m'] == 96.0
        assert res['descent_m'] == 0.0
        assert res['avg_speed_kmh'] == 10.8
        assert res['avg_pace_min_km'] == 5.56
        assert res['max_altitude_m'] == 200.0
        assert res['min_altitude_m'] == 100.0
        assert res['avg_hr'] == 150.0 # ~150 with one 180 point
        assert res['max_hr'] == 180.0
        assert res['gaps_over_10s'] == 1

        assert res['bbox'] == [50.0, 4.0, 50.1, 4.1]
        assert len(res['line']) == 10
        assert res['line'][0] == [50.0, 4.0]
        assert res['line'][-1] == [50.1, 4.1]

    def test_handles_nans_and_missing_fields(self, monkeypatch):
        def mock_load(path):
            tr = self.make_track(valid_positions=True)
            n = len(tr['t'])
            nan = np.full(n, np.nan)
            tr['alt'] = nan
            tr['dist'] = nan
            tr['hr'] = nan
            tr['speed'] = nan
            return tr
        monkeypatch.setattr('strata360.gps.overview.track.load', mock_load)

        res = overview("fake.gpx", points=10)
        assert res['distance_km'] is None
        assert res['avg_speed_kmh'] is None
        assert res['avg_pace_min_km'] is None
        assert res['max_altitude_m'] is None
        assert res['min_altitude_m'] is None
        assert res['avg_hr'] is None
        assert res['max_hr'] is None
