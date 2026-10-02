"""Gaps in the footage and the synthetic clips planned for them (implementation plan N1)."""
import numpy as np
import pytest
from strata360.gps import gaps as G
from strata360.edit import synthetic as SY

T0 = 1_771_700_000.0          # 21 Feb 2026, 18:53 UTC


def track(hours=12, step=10.0):
    """Runs at 3 m/s except for a stop in hour 6; 1 m of path per metre of distance; climbs 100 m an hour."""
    n = int(hours * 3600 / step); t = T0 + step * np.arange(n); sp = np.where((t - T0 > 6 * 3600) & (t - T0 < 7 * 3600), 0.0, 3.0); dist = np.concatenate([[0], np.cumsum(sp[1:] * step)]); nan = np.full(n, np.nan)
    return dict(t=t, lat=50.0 + dist * 5.4e-6, lon=5.0 + dist * 1.119e-5, alt=100 + (t - T0) / 36.0, speed=sp, hr=nan, cadence=nan, dist=dist, temp=nan, power=nan)


def span(i, a, b): return dict(id=i, t0=T0 + a, t1=T0 + b)


def test_a_gap_is_the_time_between_clips_that_lasts_long_enough_and_lies_on_the_track():
    spans = [span('A', 600, 700), span('B', 4000, 4100), span('C', 4500, 4600), span('D', 30000, 30060)]
    g = G.find_gaps(spans, track(12))
    assert [x['id'] for x in g] == ['G01', 'G02'] and (g[0]['before'], g[0]['after']) == ('A', 'B') and (g[1]['before'], g[1]['after']) == ('C', 'D')                  # B to C is 400 s: too short
    assert g[0]['t0'] == T0 + 700 and g[0]['t1'] == T0 + 4000 and g[0]['duration_s'] == 3300.0


def test_overlapping_clips_are_one_stretch_of_footage_and_spans_off_the_track_are_not_gaps():
    spans = [span('A', 600, 2000), span('B', 1500, 2600), span('C', 9000, 9100), span('Z', 50 * 3600, 50 * 3600 + 60)]                  # A and B overlap; Z is long after the track ends
    g = G.find_gaps(spans, track(12)); assert [(x['before'], x['after']) for x in g] == [('B', 'C'), ('C', 'Z')] and g[0]['t0'] == T0 + 2600
    assert g[1]['t1'] == pytest.approx(T0 + 12 * 3600 - 10, abs=11)                                                                              # cut at the end of the track
    assert G.find_gaps([span('A', 100, 200)], track(12)) == [] and G.find_gaps([], track(12)) == []                                             # nothing before the first clip or after the last


def test_a_gap_says_how_far_how_long_moving_how_much_climb_and_what_light():
    g, = G.find_gaps([span('A', 600, 700), span('B', 8 * 3600, 8 * 3600 + 60)], track(12))               # 700 s to 8 h: includes the hour standing still
    assert g['km_start'] == pytest.approx(2.1, abs=0.1) and g['km_end'] == pytest.approx(7 * 3600 * 3 / 1000, abs=0.2) and g['distance_km'] == pytest.approx(g['km_end'] - g['km_start'], abs=0.11)
    assert g['moving_share'] == pytest.approx(1 - 3600 / (8 * 3600 - 700), abs=0.02) and g['ascent_m'] == pytest.approx(100 * (8 * 3600 - 700) / 3600, abs=10) and g['daylight_start'] in ('day', 'golden hour', 'twilight', 'night') and g['local_start'][:3] in ('Sat', 'Fri')


def test_gap_ids_and_keys_are_the_same_for_the_same_footage_and_change_with_the_span():
    spans = [span('A', 600, 700), span('B', 4000, 4100)]; a, b = G.find_gaps(spans, track(12)), G.find_gaps(spans, track(12)); assert a[0]['key'] == b[0]['key']
    assert G.find_gaps([span('A', 600, 700), span('B', 5000, 5100)], track(12))[0]['key'] != a[0]['key']
    assert [x['id'] for x in G.find_gaps(spans, track(12), min_s=60)] == ['G01']


def test_the_spans_of_a_project_come_from_the_clips_files(project):
    project.add_clip('CAM_20260221190000_0001_D', start_utc='2026-02-21T19:00:00+00:00', source_frames=3000, fps=30.0); project.add_clip('CAM_20260221180000_0002_D', start_utc='2026-02-21T18:00:00+00:00', source_frames=900, fps=30.0)
    s = G.load_spans(project.folder); assert [x['id'][-6:-2] for x in s][-2:] == ['0002', '0001'] and s[-1]['t1'] - s[-1]['t0'] == pytest.approx(100.0) and [x['t0'] for x in s] == sorted(x['t0'] for x in s)


GAP = dict(id='G01', t0=T0, t1=T0 + 7200)


def test_a_synthetic_clip_is_shown_for_the_seconds_given_or_by_a_speed_up_or_by_default():
    a = SY.make(GAP, seconds=24); assert a['seconds'] == 24 and a['speedup'] == 300.0 and a['duration_s'] == 7200.0 and a['kind'] == 'map' and a['status'] == 'planned' and a['t0'].endswith('Z')
    b = SY.make(GAP, speedup=120); assert b['seconds'] == 60.0
    c = SY.make(GAP); assert c['seconds'] == SY.default_seconds(7200) and 6 <= c['seconds'] <= 45
    assert SY.default_seconds(3600) == pytest.approx(12.0, abs=0.1) and SY.default_seconds(36000) < 45 and SY.default_seconds(60) == pytest.approx(6.1, abs=0.05) and SY.default_seconds(0) == 6.0 and SY.default_seconds(10 ** 7) == 45.0


def test_a_stretch_of_a_gap_can_be_made_and_bad_requests_are_refused():
    s = SY.make(GAP, seconds=10, t0=T0 + 1800, t1=T0 + 3600, id='G01a'); assert s['id'] == 'G01a' and s['gap'] == 'G01' and s['duration_s'] == 1800.0 and s['speedup'] == 180.0
    for kw in (dict(seconds=5, speedup=10), dict(t0=T0 - 10), dict(t1=T0 + 99999), dict(speedup=0.5), dict(seconds=1), dict(kind='3d')):
        with pytest.raises(ValueError): SY.make(GAP, **kw)


def test_the_key_names_what_would_be_rendered_and_changes_when_it_changes():
    a = SY.make(GAP, seconds=20); assert SY.make(GAP, seconds=20)['key'] == a['key'] and SY.make(GAP, seconds=21)['key'] != a['key'] and SY.make(GAP, seconds=20, style=dict(zoom=2))['key'] != a['key'] and SY.make(GAP, seconds=20, fps=25)['key'] != a['key']


def test_a_flyover_is_4k_by_default_and_a_map_keeps_its_old_key():
    f = SY.make(GAP, seconds=20, kind='flyover'); m = SY.make(GAP, seconds=20); assert f['kind'] == 'flyover' and f['size'] == '3840x2160' and 'size' not in m
    assert f['key'] != m['key'] and SY.make(GAP, seconds=20, kind='flyover', size='1920x1080')['key'] != f['key'] and SY.make(GAP, seconds=20, kind='flyover', size='3840X2160')['key'] == f['key']
    assert SY.make(GAP, seconds=20, kind='flyover', style=dict(imagery='topo'))['key'] != f['key']
    for bad in ('big', '3840', '100x100'):
        with pytest.raises(ValueError): SY.make(GAP, kind='flyover', size=bad)


def test_changing_the_kind_of_a_planned_clip_forgets_its_render(project):
    m = SY.make(GAP, seconds=20); SY.upsert(project.folder, m); doc = SY.load(project.folder); doc['clips'][0].update(status='ready', file='synthetic/G01.mp4'); SY.save(project.folder, doc)
    c = SY.upsert(project.folder, SY.make(GAP, seconds=20, kind='flyover')); assert c['status'] == 'planned' and 'file' not in c and SY.load(project.folder)['clips'][0]['kind'] == 'flyover'


def test_planned_clips_are_kept_in_time_order_and_a_render_stays_valid_until_the_key_changes(project):
    f = project.folder; assert SY.load(f) == dict(clips=[])
    later = dict(id='G02', t0=T0 + 20000, t1=T0 + 30000); SY.upsert(f, SY.make(later, seconds=10)); first = SY.upsert(f, SY.make(GAP, seconds=20)); assert [c['id'] for c in SY.load(f)['clips']] == ['G01', 'G02']
    done = dict(SY.load(f)['clips'][0], status='rendered', file='synthetic/G01.mp4'); SY.save(f, dict(clips=[done, SY.load(f)['clips'][1]]))
    kept = SY.upsert(f, SY.make(GAP, seconds=20)); assert kept['status'] == 'rendered' and kept['file'] == 'synthetic/G01.mp4'                       # same key: the render is still right
    changed = SY.upsert(f, SY.make(GAP, seconds=30)); assert changed['status'] == 'planned' and 'file' not in changed                                    # another length: it must be rendered again
    assert SY.remove(f, 'G02') and not SY.remove(f, 'G02') and [c['id'] for c in SY.load(f)['clips']] == ['G01'] and first['key'] != changed['key']
