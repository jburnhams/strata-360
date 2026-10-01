"""gps/track.py: interpolating a position along a track, writing GPX, and the cache. Pure numpy on synthetic tracks (no FIT/GPX libraries needed except where noted)."""
import datetime as dt, re
import numpy as np
import pytest
from hypothesis import given, strategies as st
from strata360.gps import track as T


def make_track(n=10, t0=1_700_000_000.0, step=10.0, lat0=51.0, lon0=4.0, alt=True):
    t = t0 + step * np.arange(n); nan = np.full(n, np.nan)
    return dict(t=t, lat=lat0 + 0.001 * np.arange(n), lon=lon0 + 0.002 * np.arange(n), alt=100 + np.arange(n, dtype=float) if alt else nan.copy(), speed=nan, hr=nan, cadence=nan, dist=nan, temp=nan, power=nan)


class TestAt:
    def test_exact_at_a_sample(self):
        tr = make_track(); lat, lon = T.at(tr, tr['t'][3]); assert (lat, lon) == pytest.approx((tr['lat'][3], tr['lon'][3]))

    def test_halfway_between_two_samples(self):
        tr = make_track(); lat, lon = T.at(tr, tr['t'][3] + 5); assert (lat, lon) == pytest.approx((tr['lat'][3] + 0.0005, tr['lon'][3] + 0.001))

    def test_clamps_outside_the_track(self):
        tr = make_track(); assert T.at(tr, tr['t'][0] - 1000)[0] == pytest.approx(tr['lat'][0]) and T.at(tr, tr['t'][-1] + 1000)[0] == pytest.approx(tr['lat'][-1])

    def test_samples_without_a_position_are_skipped(self):
        tr = make_track(); tr['lat'][4] = np.nan
        assert T.at(tr, tr['t'][4])[0] == pytest.approx((tr['lat'][3] + tr['lat'][5]) / 2)

    def test_takes_arrays(self):
        tr = make_track(); lat, lon = T.at(tr, tr['t'][:3]); assert lat.shape == lon.shape == (3,)

    @given(st.floats(min_value=0, max_value=90, allow_nan=False))
    def test_always_inside_the_track_bounds(self, offset):
        tr = make_track(); lat, lon = T.at(tr, tr['t'][0] + offset)
        assert tr['lat'].min() <= lat <= tr['lat'].max() and tr['lon'].min() <= lon <= tr['lon'].max()

    @given(st.lists(st.floats(min_value=0, max_value=90, allow_nan=False), min_size=2, max_size=20))
    def test_moves_monotonically_along_a_monotonic_track(self, offsets):
        tr = make_track(); lat, _ = T.at(tr, tr['t'][0] + np.sort(offsets)); assert np.all(np.diff(lat) >= -1e-12)


class TestToGpx:
    def test_writes_one_point_per_sample_with_time_and_elevation(self, tmp_path):
        tr = make_track(3); out = tmp_path / 't.gpx'; T.to_gpx(tr, str(out)); xml = out.read_text()
        assert xml.count('<trkpt') == 3 and '<ele>100.0</ele>' in xml
        assert re.findall(r'<time>(.*?)</time>', xml)[0] == dt.datetime.fromtimestamp(tr['t'][0], dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

    def test_every_nth_point(self, tmp_path):
        out = tmp_path / 't.gpx'; T.to_gpx(make_track(10), str(out), every=3); assert out.read_text().count('<trkpt') == 4

    def test_points_without_a_position_are_dropped_and_missing_elevation_is_omitted(self, tmp_path):
        tr = make_track(4, alt=False); tr['lat'][1] = np.nan; out = tmp_path / 't.gpx'; T.to_gpx(tr, str(out)); xml = out.read_text()
        assert xml.count('<trkpt') == 3 and '<ele>' not in xml


class TestLoadCache:
    def test_a_fresh_cache_is_used_instead_of_parsing(self, tmp_path, monkeypatch):
        src = tmp_path / 'x.gpx'; src.write_text('<gpx/>'); tr = make_track(5)
        np.savez_compressed(str(src) + '.npz', **tr)                         # newer than the source
        monkeypatch.setattr(T, 'load_gpx', lambda p: pytest.fail('parsed although the cache is fresh'))
        got = T.load(str(src)); assert np.array_equal(got['t'], tr['t']) and set(got) == set(T.FIELDS)

    def test_loading_sorts_by_time_and_writes_the_cache(self, tmp_path, monkeypatch):
        src = tmp_path / 'x.gpx'; src.write_text('<gpx/>'); tr = make_track(5); shuffled = {k: v[::-1] for k, v in tr.items()}
        monkeypatch.setattr(T, 'load_gpx', lambda p: shuffled)
        got = T.load(str(src)); assert np.all(np.diff(got['t']) > 0) and (tmp_path / 'x.gpx.npz').exists()

    def test_no_cache_option_writes_nothing(self, tmp_path, monkeypatch):
        src = tmp_path / 'x.fit'; src.write_text('x'); monkeypatch.setattr(T, 'load_fit', lambda p: make_track(3))
        T.load(str(src), cache=False); assert not (tmp_path / 'x.fit.npz').exists()

    def test_fit_or_gpx_is_chosen_by_extension(self, tmp_path, monkeypatch):
        called = []; monkeypatch.setattr(T, 'load_fit', lambda p: called.append('fit') or make_track(2)); monkeypatch.setattr(T, 'load_gpx', lambda p: called.append('gpx') or make_track(2))
        for n in ('a.FIT', 'b.gpx'): (tmp_path / n).write_text('x'); T.load(str(tmp_path / n), cache=False)
        assert called == ['fit', 'gpx']
