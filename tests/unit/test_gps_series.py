"""Data for the race map and charts: the decimated series, the line for the map in view, and where each clip is on the track."""
import numpy as np
import pytest
from strata360.gps import series as S

T0 = 1_771_700_000.0     # 22 Feb 2026, about 19:00 UTC


def track(n=3600, step=10.0, with_speed=True):
    """10 hours at 10 s: runs for the first 3 hours (3 m/s), stands still for hours 3 to 4, runs again (2 m/s); climbs 100 m an hour; heads north-east at 1 m of path per metre of distance."""
    t = T0 + step * np.arange(n); sp = np.where((t - T0 > 3 * 3600) & (t - T0 < 4 * 3600), 0.0, np.where(t - T0 <= 3 * 3600, 3.0, 2.0)); dist = np.concatenate([[0], np.cumsum(sp[1:] * step)])
    nan = np.full(n, np.nan); return dict(t=t, lat=50.0 + dist * 5.4e-6, lon=5.0 + dist * 1.119e-5, alt=100 + (t - T0) / 36.0, speed=sp if with_speed else nan, hr=np.full(n, 140.0), cadence=nan, dist=dist if with_speed else nan, temp=nan, power=nan)


def test_series_keeps_the_shape_of_the_race_in_a_few_points():
    s = S.series(track(), 100); assert s['points'] == 100 and len(s['t']) == len(s['km']) == len(s['alt']) == len(s['pace']) == 100
    assert s['t'][0] < 400 and s['t'][-1] > 35000 and s['t'] == sorted(s['t']) and abs(s['distance_km'] - 75.6) < 0.5 and s['duration_s'] == 35990
    assert all(lo <= a <= hi for lo, a, hi in zip(s['alt_lo'], s['alt'], s['alt_hi']))                                  # each bin's mean lies between its lowest and highest


def test_pace_is_for_the_moving_part_and_a_stop_has_none():
    s = S.series(track(), 100); i_run, i_stop, i_late = 10, 33, 80
    assert abs(s['pace'][i_run] - 1000 / 3 / 60) < 0.05 and s['pace'][i_stop] is None and s['moving'][i_stop] == 0.0 and abs(s['pace'][i_late] - 1000 / 2 / 60) < 0.05 and s['moving'][i_run] == 1.0


def test_a_track_without_distance_or_speed_gets_them_from_its_positions():
    gpx = track(with_speed=False); assert np.isnan(gpx['dist']).all()
    p = S.prepare(gpx); assert abs(p['dist'][-1] / 1000 - 75.6) < 2 and np.nanmedian(p['speed'][:600]) == pytest.approx(3.0, rel=0.15)
    s = S.series(p, 100); assert s['pace'][10] is not None and abs(s['pace'][10] - 1000 / 3 / 60) < 0.4
    fit = track(); assert S.prepare(fit)['dist'] is fit['dist'] or np.array_equal(S.prepare(fit)['dist'], fit['dist'])                               # a FIT's own values are kept


def test_the_line_is_the_whole_track_or_the_part_in_the_box_in_order_and_never_too_long():
    tr = track(); whole = S.line(tr, None, 500); assert len(whole['lat']) <= 500 and whole['t'] == sorted(whole['t']) and whole['t'][0] == 0
    box = (50.0, 5.0, 50.1, 5.15); part = S.line(tr, box, 100000); assert 0 < len(part['lat']) < 3600 and part['lat'][1] <= 50.1 + 1e-3
    inside = [i for i, (la, lo) in enumerate(zip(part['lat'], part['lon'])) if box[0] <= la <= box[2] and box[1] <= lo <= box[3]]; assert len(inside) >= len(part['lat']) - 2         # at most the two neighbours outside, so the line crosses the edge
    assert S.line(tr, (10.0, 10.0, 11.0, 11.0))['lat'] == []


def test_each_clip_is_placed_at_its_middle_with_the_stretch_it_covers_and_the_facts_for_its_card():
    tr = track(); spans = [dict(id='A', t0=T0 + 600, t1=T0 + 660), dict(id='B', t0=T0 - 3600, t1=T0 - 3500), dict(id='C', t0=T0 + 2 * 3600, t1=T0 + 2 * 3600 + 20)]
    a, b, c = S.clips(tr, spans)
    assert a['covered'] and a['t_mid'] == 630.0 and a['t0'] == 600.0 and abs(a['lat'] - (50.0 + 3.0 * 630 * 5.4e-6)) < 1e-4 and len(a['stretch']) >= 2 and a['facts']['local'] and 'heart_rate' in a['facts']
    assert b['covered'] is False and 'lat' not in b                                                                      # before the start: no marker
    assert c['covered'] and len(c['stretch']) >= 2 and abs(a['facts']['pace_min_km'] - 1000 / 3 / 60) < 0.05


def test_a_clip_shorter_than_the_sample_gap_still_gets_a_stretch_to_draw():
    c, = S.clips(track(), [dict(id='A', t0=T0 + 601, t1=T0 + 603)]); assert c['covered'] and len(c['stretch']) == 2
