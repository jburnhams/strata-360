import numpy as np
import pytest
from hypothesis import given, strategies as st
from strata360.gps.clock import step_series, step_windows, estimate, sun_elevation_deg, scene_brightness

class TestStepWindows:
    def test_finds_dominant_frequency(self):
        fps = 50.0
        t = np.arange(0, 10.0, 1 / fps)
        # generate a signal at 2.5 Hz (within 1.2-3.5 Hz range)
        acc = np.sin(2 * np.pi * 2.5 * t) * 10.0 + 9.8
        windows = step_windows(acc, t, fps)
        # 10s gives 6 windows of 4s moving by 1s (centers: 2.0, 3.0, 4.0, 5.0, 6.0, 7.0)
        assert len(windows) == 6
        assert np.allclose(windows[:, 0], np.arange(2.0, 8.0))
        # frequency should be close to 2.5
        assert np.all(np.abs(windows[:, 1] - 2.5) < 0.1)
        # strength should be high
        assert np.all(windows[:, 2] > 0.8)

    def test_ignores_signal_outside_human_cadence(self):
        fps = 50.0
        t = np.arange(0, 10.0, 1 / fps)
        # 5 Hz is outside 1.2-3.5 Hz
        acc = np.sin(2 * np.pi * 5.0 * t) * 10.0 + 9.8
        windows = step_windows(acc, t, fps)
        # strength for anything in 1.2-3.5 should be low or empty
        # If there's a peak, it might get selected but strength will be near 0
        if len(windows) > 0:
            assert np.all(windows[:, 2] < 0.25)

    def test_empty_or_short_input(self):
        fps = 50.0
        t = np.arange(0, 2.0, 1 / fps)
        acc = np.ones_like(t) * 9.8
        windows = step_windows(acc, t, fps)
        assert len(windows) == 0

class TestStepSeries:
    def test_calls_step_windows_correctly(self, monkeypatch):
        called = []
        def mock_read_frames(osv):
            called.append(osv)
            return {'ts_us': np.arange(0, 10000000, 20000), 'acc': np.ones((500, 3))} # 50 fps, 10 seconds
        monkeypatch.setattr('strata360.gps.clock.read_frames', mock_read_frames)

        res = step_series("test.mp4")
        assert "test.mp4" in called
        # Constant acceleration -> no AC component -> no valid steps found
        assert len(res) == 0

class TestEstimate:
    def make_track(self):
        n = 100
        t = np.arange(1000.0, 1100.0) # 100 seconds
        cadence = np.ones(n) * 150.0 # 2.5 Hz = 150 spm
        speed = np.ones(n) * 3.0 # > 0.3
        return {'t': t, 'cadence': cadence, 'speed': speed}

    def test_perfect_match(self):
        track = self.make_track()
        track['cadence'] = np.ones(100) * 75.0 # 2.5 Hz
        # camera recorded a clip starting at true time 1020, but it thinks it's 1010
        # true = camera + offset -> 1020 = 1010 + 10 -> offset = 10
        # series is at offset 0 relative to clip start
        windows = np.array([
            [2.0, 2.5, 0.9],
            [3.0, 2.5, 0.9],
        ])
        series = [(1010.0, windows)]
        offsets = np.array([0.0, 10.0, 20.0])

        # We need > 30 samples to get a valid score. Let's make 40 samples
        windows_large = np.array([[float(i), 2.5, 0.9] for i in range(40)])
        series_large = [(1010.0, windows_large)]

        scores, n = estimate(series_large, track, offsets)
        assert n == 40
        # At offset 10, true UTC is 1010+10 = 1020.
        # Watch at 1020 has cadence 75 (2.5Hz).
        # Diff = 0.
        assert np.isfinite(scores[1])
        assert scores[1] < 1e-3

    def test_no_valid_observations(self):
        track = self.make_track()
        # min strength is 0.25, these have 0.1
        series = [(1010.0, np.array([[2.0, 2.5, 0.1]]))]
        scores, n = estimate(series, track, [0.0])
        assert n == 0
        assert np.isnan(scores[0])

    def test_not_enough_points_for_score(self):
        track = self.make_track()
        # Only 5 points
        windows = np.array([[float(i), 2.5, 0.9] for i in range(5)])
        series = [(1010.0, windows)]
        scores, n = estimate(series, track, [0.0])
        assert n == 5
        assert np.isnan(scores[0])

class TestSunElevation:
    def test_sun_elevation_known_values(self):
        # 2024-03-20 12:00:00 UTC (Vernal Equinox roughly)
        # Lat 0, Lon 0 -> Sun should be near zenith (90 degrees)
        t = 1710936000.0
        elev = sun_elevation_deg(0, 0, t)
        assert 88.0 < elev <= 90.0

        # Lat 90 (North Pole) -> Sun should be near horizon (0 degrees)
        elev = sun_elevation_deg(90, 0, t)
        assert -1.0 < elev < 1.0

        # Takes arrays
        elevs = sun_elevation_deg(0, 0, [t, t])
        assert len(elevs) == 2

    @given(lat=st.floats(-90, 90), lon=st.floats(-180, 180), t=st.floats(0, 2e9))
    def test_sun_elevation_bounds(self, lat, lon, t):
        elev = sun_elevation_deg(lat, lon, t)
        assert -90.5 <= elev <= 90.5

class TestSceneBrightness:
    def test_calculates_stops_correctly(self):
        doc = {
            'frames': [
                {'t_s': 0.1, 'camera': {'shutter_den': [100, 100], 'iso': [100, 100]}},
                {'t_s': 0.2, 'camera': {'shutter_den': [200, 200], 'iso': [100, 100]}},
                {'t_s': 0.3, 'camera': {'shutter_den': [100, 100], 'iso': [200, 200]}},
            ]
        }
        t, b = scene_brightness(doc)
        assert np.array_equal(t, [0.1, 0.2, 0.3])
        # shutter / ISO:
        # frame 0: 100 / 100 = 1 -> log2(1) = 0
        # frame 1: 200 / 100 = 2 -> log2(2) = 1
        # frame 2: 100 / 200 = 0.5 -> log2(0.5) = -1
        assert np.allclose(b, [0.0, 1.0, -1.0])

    def test_handles_zeros(self):
        doc = {
            'frames': [
                {'t_s': 0.1, 'camera': {'shutter_den': [0, 0], 'iso': [0, 0]}},
            ]
        }
        t, b = scene_brightness(doc)
        assert len(b) == 1
        assert b[0] == 0.0 # log2(max(0,1)) - log2(max(0,1)) = 0
