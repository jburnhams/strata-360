"""overlay/series.py: the track's values at any instant (distance, pace, slope, altitude, heart rate, position), smoothed once over the whole race."""
import math
import numpy as np
import pytest
from hypothesis import given, strategies as st
from overlay_fakes import T0, race_track
from strata360.overlay.series import Series, path_length


class TestValues:
    def test_distance_and_pace_of_a_steady_run(self):
        s = Series(race_track(speed=3.0)); v = s.at(T0 + 100.5)
        assert v['dist_m'] == pytest.approx(301.5) and v['pace_s_km'] == pytest.approx(1000 / 3.0)

    def test_altitude_and_heart_rate(self):
        v = Series(race_track(hr=152.0)).at(T0 + 200); assert v['alt_m'] == pytest.approx(300.0) and v['hr'] == pytest.approx(152.0)

    def test_scalar_gives_floats_and_array_gives_arrays(self):
        s = Series(race_track()); a = s.at(np.array([T0 + 10, T0 + 20]))
        assert isinstance(s.at(T0 + 10)['dist_m'], float) and a['dist_m'] == pytest.approx([30.0, 60.0])

    def test_outside_the_track_is_nan(self):
        s = Series(race_track()); assert all(math.isnan(x) for x in s.at(T0 - 5).values()) and all(math.isnan(x) for x in s.at(T0 + 10_000).values())

    def test_pace_is_nan_when_stopped(self):
        tr = race_track(); tr['speed'][:] = 0.2; assert math.isnan(Series(tr).at(T0 + 100)['pace_s_km'])

    def test_pace_is_smoothed(self):
        tr = race_track(); tr['speed'][300] = 30.0                                         # one wild sample
        assert Series(tr, pace_s=21).at(T0 + 300)['pace_s_km'] == pytest.approx(1000 / (3.0 + 27.0 / 21), rel=1e-6)

    def test_gpx_without_distance_or_speed_measures_the_path(self):
        v = Series(race_track(speed=3.0, fit=False)).at(T0 + 300)
        assert v['dist_m'] == pytest.approx(900.0, rel=1e-3) and v['pace_s_km'] == pytest.approx(1000 / 3.0, rel=1e-3)

    def test_short_gap_is_bridged_and_long_gap_is_nan(self):
        tr = race_track(); tr['hr'][100:105] = np.nan; tr['hr'][200:240] = np.nan; s = Series(tr, max_gap_s=10)
        assert s.at(T0 + 102)['hr'] == pytest.approx(150.0) and math.isnan(s.at(T0 + 220)['hr'])


class TestSlope:
    def test_steady_climb(self):
        assert Series(race_track(grade=0.05)).at(T0 + 300)['slope_pct'] == pytest.approx(5.0)

    def test_descent_is_negative(self):
        assert Series(race_track(grade=-0.08)).at(T0 + 300)['slope_pct'] == pytest.approx(-8.0)

    def test_nan_until_the_span_is_covered(self):
        s = Series(race_track(grade=0.05), slope_m=60.0); assert math.isnan(s.at(T0 + 5)['slope_pct']) and math.isfinite(s.at(T0 + 15)['slope_pct'])

    def test_clipped_to_sixty_percent(self):
        assert Series(race_track(grade=2.0)).at(T0 + 300)['slope_pct'] == pytest.approx(60.0)

    def test_no_altitude_gives_nan(self):
        tr = race_track(); tr['alt'][:] = np.nan; assert math.isnan(Series(tr).at(T0 + 300)['slope_pct'])

    def test_standing_still_gives_nan(self):
        tr = race_track(); tr['dist'][:] = 5.0; assert math.isnan(Series(tr).at(T0 + 300)['slope_pct'])


class TestPosition:
    def test_interpolated_between_samples(self):
        tr = race_track(); lat, lon = Series(tr).position(T0 + 10.5); assert lat == pytest.approx((tr['lat'][10] + tr['lat'][11]) / 2) and lon == pytest.approx(5.79)

    def test_held_at_the_ends(self):
        tr = race_track(); s = Series(tr); assert s.position(T0 - 100)[0] == pytest.approx(tr['lat'][0]) and s.position(T0 + 1e6)[0] == pytest.approx(tr['lat'][-1])

    def test_route_skips_points_without_a_position(self):
        tr = race_track(n=50); tr['lat'][3] = np.nan; assert len(Series(tr).route_lat) == 49


def test_track_shorter_than_the_smoothing_window():
    v = Series(race_track(n=8)).at(T0 + 4); assert v['pace_s_km'] == pytest.approx(1000 / 3.0) and v['dist_m'] == pytest.approx(12.0)


class TestErrors:
    def test_too_short(self):
        with pytest.raises(ValueError, match='fewer than two'): Series(race_track(n=1))

    def test_no_positions(self):
        tr = race_track(); tr['lat'][:] = np.nan
        with pytest.raises(ValueError, match='no positions'): Series(tr)


def test_path_length_of_one_degree_of_latitude():
    assert path_length(np.array([50.0, 51.0]), np.array([5.0, 5.0]))[-1] == pytest.approx(111_195, rel=1e-4)


@given(st.lists(st.floats(min_value=0, max_value=599, allow_nan=False), min_size=2, max_size=30))
def test_distance_never_goes_backwards(offsets):
    d = Series(race_track(fit=False)).at(T0 + np.sort(offsets))['dist_m']; assert np.all(np.diff(d) >= -1e-9)
