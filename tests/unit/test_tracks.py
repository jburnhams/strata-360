"""gps/tracks.py: several FIT / GPX tracks per project, runs merged into the one race track, routes for the overview map only."""
import json, os
import numpy as np
import pytest

from strata360.gps import tracks as TK
from strata360.pipeline import config


def gpx(points, wpts=(), route=False, timed=True, t0=1_770_000_000):
    """A GPX document: points are (lat, lon) one second apart (or without times); wpts are (name, lat, lon)."""
    from datetime import datetime, timezone
    def pt(i, la, lo, tag):
        tm = f'<time>{datetime.fromtimestamp(t0 + i, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}</time>' if timed else ''
        return f'<{tag} lat="{la}" lon="{lo}"><ele>10</ele>{tm}</{tag}>'
    body = ''.join(f'<wpt lat="{la}" lon="{lo}"><name>{n}</name></wpt>' for n, la, lo in wpts)
    pts = ''.join(pt(i, la, lo, 'rtept' if route else 'trkpt') for i, (la, lo) in enumerate(points))
    pad = '<!--' + 'x' * 120 + '-->'                                                       # files under 100 bytes are refused
    inner = f'<rte>{pts}</rte>' if route else f'<trk><trkseg>{pts}</trkseg></trk>'
    return f'<?xml version="1.0"?><gpx version="1.1" creator="t" xmlns="http://www.topografix.com/GPX/1/1">{body}{inner}{pad}</gpx>'.encode()


def line(n, lat0=50.0, lon0=5.0): return [(lat0 + i * 1e-4, lon0) for i in range(n)]


def test_first_upload_is_a_run_and_later_ones_routes(tmp_path):
    rd = str(tmp_path)
    a = TK.add(rd, 'race.gpx', gpx(line(60))); b = TK.add(rd, 'course.gpx', gpx(line(60, 51.0), route=True, timed=False))
    assert (a['kind'], b['kind']) == ('run', 'route') and b['timed'] is False
    assert [e['kind'] for e in TK.entries(rd)] == ['run', 'route']
    assert TK.current_path(rd) == TK.runs(rd)[0]['file']                                    # one run: its own file


def test_a_run_needs_times(tmp_path):
    rd = str(tmp_path)
    with pytest.raises(ValueError, match='times'): TK.add(rd, 'c.gpx', gpx(line(30), route=True, timed=False), kind='run')
    assert os.listdir(os.path.join(rd, 'tracks')) == ['t1-c.gpx.bad'] or any(n.endswith('.bad') for n in os.listdir(os.path.join(rd, 'tracks')))
    assert TK.entries(rd) == []
    with pytest.raises(ValueError): TK.add(rd, 'x.txt', b'x' * 200)


def test_merge_joins_runs_and_keeps_the_higher_run_where_both_recorded():
    def tr(t, lat):
        n = len(t); nan = np.full(n, np.nan); return dict(t=np.asarray(t, float), lat=np.asarray(lat, float), lon=np.full(n, 5.0), alt=nan, speed=nan, hr=nan, cadence=nan, dist=nan, temp=nan, power=nan)
    hi = tr(np.arange(0, 100), 50 + np.arange(0, 100) * 1e-4)
    lo = tr(np.arange(50, 300), 50 + np.arange(50, 300) * 1e-4 + 1e-6)                      # overlaps 50..99, goes on to 299
    m = TK.merge([hi, lo])
    assert m['t'][0] == 0 and m['t'][-1] == 299 and len(m['t']) == 300 and np.all(np.diff(m['t']) > 0)
    assert m['lat'][60] == hi['lat'][60]                                                    # the overlap is from the higher run
    assert m['dist'][0] == 0 and np.all(np.diff(m['dist']) >= 0) and 30 * 1000 > m['dist'][-1] > 30


def test_a_break_in_the_higher_run_is_filled_by_the_lower():
    def tr(t): t = np.asarray(t, float); k = np.full(len(t), np.nan); return dict(t=t, lat=50 + t * 1e-4, lon=np.full(len(t), 5.0), alt=k, speed=k, hr=k, cadence=k, dist=k, temp=k, power=k)
    hi = tr(list(range(0, 20)) + list(range(200, 220))); lo = tr(range(0, 220, 2))
    m = TK.merge([hi, lo]); t = m['t']
    assert 100 in t and len(t) == 20 + 20 + 90                                              # lo fills the break (20..200) only; inside hi's recording hi alone is kept


def test_two_runs_make_the_race_track_and_routes_do_not(tmp_path, monkeypatch):
    monkeypatch.setenv('STRATA_RACES', str(tmp_path)); rd = config.race_dir('r'); os.makedirs(rd)
    TK.add(rd, 'a.gpx', gpx(line(60), t0=1_770_000_000)); assert config.track_path('r') == TK.runs(rd)[0]['file']
    TK.add(rd, 'b.gpx', gpx(line(60, 50.01), t0=1_770_001_000), kind='run'); TK.add(rd, 'c.gpx', gpx(line(60, 52.0), route=True, timed=False))
    p = config.track_path('r'); assert p.endswith(TK.MERGED)
    tr = TK.read(p); assert len(tr['t']) == 120 and tr['lat'].max() < 51                    # the route is not in it
    ls = TK.listing(rd); assert ls['runs'] == 2 and ls['merged']['samples'] == 120 and [t['kind'] for t in ls['tracks']] == ['run', 'run', 'route']
    TK.set_kind(rd, 't1', 'route'); assert config.track_path('r') == TK.runs(rd)[0]['file'] and not os.path.exists(os.path.join(rd, TK.MERGED))     # back to one run
    TK.remove(rd, 't1'); assert [e['id'] for e in TK.entries(rd)] == ['t2', 't3'] and os.path.exists(os.path.join(rd, 'tracks', 'removed'))


def test_the_older_single_file_is_the_first_run(tmp_path):
    rd = str(tmp_path); open(os.path.join(rd, 'track.gpx'), 'wb').write(gpx(line(60)))
    assert [(e['id'], e['kind']) for e in TK.entries(rd)] == [('main', 'run')]
    TK.add(rd, 'b.gpx', gpx(line(60, 50.01), t0=1_770_001_000), kind='run'); assert TK.current_path(rd).endswith(TK.MERGED)
    TK.set_kind(rd, 'main', 'route'); assert json.load(open(os.path.join(rd, TK.MANIFEST)))['main_kind'] == 'route'
    with pytest.raises(KeyError): TK.set_kind(rd, 'nope', 'run')


def test_points_of_interest_from_waypoints_and_named_route_points(tmp_path):
    p = tmp_path / 'c.gpx'; p.write_bytes(gpx(line(10), wpts=[('Aid station', 50.0005, 5.0), ('Summit', 50.0008, 5.0)]))
    out = TK.pois(str(p)); assert [q['name'] for q in out] == ['Aid station', 'Summit'] and out[0]['lat'] == 50.0005
    assert os.path.exists(str(p) + '.pois.json') and TK.pois(str(p)) == out
    rd = str(tmp_path / 'proj'); os.makedirs(rd); TK.add(rd, 'c.gpx', p.read_bytes()); assert [q['name'] for q in TK.listing(rd)['pois']] == ['Aid station', 'Summit']


def test_divergences_are_wrong_turns_not_offsets_alongside_the_route(tmp_path):
    rd = str(tmp_path)
    # the route goes north 400 points (11 m apiece). The run: a detour east and back at 100-160 (up to ~290 m away, heading across the route), a smaller one at 250-290 (~110 m),
    # and a stretch at 330-399 where it runs level with the route 150 m to the side (an offset, not a wrong turn)
    def run(i):
        if 100 <= i < 160: return 5.0 + 4.0e-3 * (1 - abs(i - 130) / 30.0), 50.0 + 100 * 1e-4 + (min(i, 130) - 100) * 1e-4
        if 250 <= i < 290: return 5.0 + 1.5e-3 * (1 - abs(i - 270) / 20.0), 50.0 + 250 * 1e-4 + (min(i, 270) - 250) * 1e-4
        return 5.0 + (2.1e-3 if i >= 330 else 0.0), 50.0 + i * 1e-4
    pts = []
    for i in range(400):
        lon, lat = run(i); pts.append((lat, lon))
    TK.add(rd, 'run.gpx', gpx(pts)); TK.add(rd, 'course.gpx', gpx([(50.0 + i * 1e-4, 5.0) for i in range(400)], route=True, timed=False))
    d = TK.divergences(rd); assert len(d) >= 1 and d[0]['peak_m'] > 200 and d[0]['wrong'] > 0.6 and d[0]['length_m'] >= 300 and len(d[0]['line']) > 1 and d[0]['km'] > 1
    assert all(abs(x['lon'] - 5.0021) > 1e-4 or x['lat'] < 50.032 for x in d)                    # nothing at the offset stretch (lat from 50.033)
    assert [x['score'] for x in d] == sorted((x['score'] for x in d), reverse=True) and TK.listing(rd)['divergences'][0]['peak_m'] == d[0]['peak_m']
    assert TK.divergences(str(tmp_path / 'none')) == []


def test_routes_are_put_in_race_order_with_a_numbered_checkpoint_where_they_join(tmp_path):
    rd = str(tmp_path); north = lambda a, b, lon=5.0: [(50.0 + i * 1e-4, lon) for i in range(a, b)]                    # 11 m per point; the run goes north for 900 points
    TK.add(rd, 'run.gpx', gpx(north(0, 900)))
    TK.add(rd, 'c.gpx', gpx(north(600, 900), route=True, timed=False)); TK.add(rd, 'a.gpx', gpx(north(0, 300), route=True, timed=False))             # uploaded out of order
    TK.add(rd, 'b.gpx', gpx(north(300, 600, 5.0002)[::-1], route=True, timed=False))                                    # the middle one is drawn the other way and ends ~14 m to the side
    ls = TK.listing(rd); routes = [t for t in ls['tracks'] if t['kind'] == 'route']
    assert [(t['name'], t.get('order')) for t in routes] == [('a.gpx', 1), ('b.gpx', 2), ('c.gpx', 3)] and routes[1]['reversed'] and not routes[0]['reversed']
    assert routes[0]['km_start'] < 0.1 and 3.2 < routes[0]['km_end'] < 3.5
    cps = [p for p in ls['pois'] if p['sym'] == 'checkpoint']; assert [(p['name'], p['n']) for p in cps] == [('Checkpoint 1', 1), ('Checkpoint 2', 2)]                 # none at the start of a.gpx or the end of c.gpx
    assert abs(cps[0]['lat'] - 50.03) < 5e-4 and 'a.gpx → b.gpx' in cps[0]['desc'] and abs(cps[0]['lon'] - 5.0001) < 5e-5                                    # halfway between the ends that do not meet
    assert TK.route_order(str(tmp_path / 'none')) == ([], [])


def test_a_race_that_passes_the_same_place_twice_still_puts_the_routes_in_order(tmp_path):
    rd = str(tmp_path); out = [(50.0 + i * 1e-4, 5.0) for i in range(300)]; back = [(50.0 + i * 1e-4, 5.0006) for i in range(300, 0, -1)]            # out and back, start and finish together
    TK.add(rd, 'run.gpx', gpx(out + [(50.03, 5.0003)] + back))
    TK.add(rd, 'second.gpx', gpx(back, route=True, timed=False)); TK.add(rd, 'first.gpx', gpx(out, route=True, timed=False))
    routes = [t for t in TK.listing(rd)['tracks'] if t['kind'] == 'route']
    assert [(t['name'], t['order']) for t in routes] == [('first.gpx', 1), ('second.gpx', 2)] and not routes[1]['reversed'] and routes[1]['km_start'] > 3


def test_stops_at_a_checkpoint_count_only_the_time_standing_still(tmp_path):
    from datetime import datetime, timezone
    rd = str(tmp_path); t0 = 1_770_000_000
    # the run goes north at 3 m/s for 1200 s (to 3600 m), stands still 900 s, then goes on at 3 m/s; one sample a second, 0.0000270 deg of lat ~ 3 m
    pts = []; y = 0.0
    for i in range(1200 + 900 + 1200):
        if not (1200 <= i < 2100): y += 3.0
        pts.append((50.0 + y / 110540.0, 5.0))
    body = ''.join(f'<trkpt lat="{la}" lon="{lo}"><time>{datetime.fromtimestamp(t0 + i, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}</time></trkpt>' for i, (la, lo) in enumerate(pts))
    TK.add(rd, 'run.gpx', f'<?xml version="1.0"?><gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1"><trk><trkseg>{body}</trkseg></trk><!--{"x" * 100}--></gpx>'.encode())
    route = lambda a, b: gpx([(50.0 + k * 30 / 110540.0, 5.0) for k in range(a, b)], route=True, timed=False)
    TK.add(rd, 'one.gpx', route(0, 121)); TK.add(rd, 'two.gpx', route(121, 241))                                         # they join at 3600 m, where the run stood
    s = TK.checkpoint_stops(rd); assert list(s) == [1]; c = s[1]
    assert 880 <= c['stopped_s'] <= 900        # the run-in and run-out at 3 m/s inside the zone are not counted
    cp = [p for p in TK.listing(rd)['pois'] if p['sym'] == 'checkpoint'][0]; assert cp['stop']['stopped_s'] == c['stopped_s']
    assert TK.checkpoint_stops(str(tmp_path / 'none')) == {}


def test_only_one_visit_counts_when_the_run_comes_back_to_the_same_place(tmp_path):
    from datetime import datetime, timezone
    rd = str(tmp_path); t0 = 1_770_000_000; pts = []; y = 0.0
    # north at 3 m/s; stand 600 s at 3600 m; go on; after 1800 s come back (south) to 3600 m and stand 900 s there (a loop back to the same place)
    for i in range(1200): y += 3.0; pts.append(y)
    pts += [y] * 600
    for i in range(600): y += 3.0; pts.append(y)
    for i in range(1000): y -= 3.0; pts.append(y)              # back down to ~3600 m... 
    pts += [y] * 900
    body = ''.join(f'<trkpt lat="{50.0 + m / 110540.0}" lon="5.0"><time>{datetime.fromtimestamp(t0 + i, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}</time></trkpt>' for i, m in enumerate(pts))
    TK.add(rd, 'run.gpx', f'<?xml version="1.0"?><gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1"><trk><trkseg>{body}</trkseg></trk><!--{"x" * 100}--></gpx>'.encode())
    route = lambda a, b: gpx([(50.0 + k * 30 / 110540.0, 5.0) for k in range(a, b)], route=True, timed=False)
    TK.add(rd, 'one.gpx', route(0, 121)); TK.add(rd, 'two.gpx', route(121, 241))
    c = TK.checkpoint_stops(rd)[1]; assert 580 <= c['stopped_s'] <= 600                                                  # the first stop, not the 900 s one after the return nor the two together


def test_a_paused_watch_at_the_stop_is_still_one_visit_and_counts_as_standing_still(tmp_path):
    from datetime import datetime, timezone
    rd = str(tmp_path); t0 = 1_770_000_000; rows = []; y = 0.0
    for i in range(1200): y += 3.0; rows.append((i, y))
    rows += [(1200 + k, y) for k in range(60)]                                                                           # 1 min still, then the watch is off for 20 min
    base = 1200 + 60 + 1200; rows += [(base + k, y) for k in range(60)]
    for k in range(600): y += 3.0; rows.append((base + 60 + k, y))
    body = ''.join(f'<trkpt lat="{50.0 + m / 110540.0}" lon="5.0"><time>{datetime.fromtimestamp(t0 + i, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}</time></trkpt>' for i, m in rows)
    TK.add(rd, 'run.gpx', f'<?xml version="1.0"?><gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1"><trk><trkseg>{body}</trkseg></trk><!--{"x" * 100}--></gpx>'.encode())
    route = lambda a, b: gpx([(50.0 + k * 30 / 110540.0, 5.0) for k in range(a, b)], route=True, timed=False)
    TK.add(rd, 'one.gpx', route(0, 121)); TK.add(rd, 'two.gpx', route(121, 241))
    assert 1300 <= TK.checkpoint_stops(rd)[1]['stopped_s'] <= 1400


def test_route_times_and_checkpoint_times_add_up_to_the_run_time(tmp_path):
    from datetime import datetime, timezone
    rd = str(tmp_path); t0 = 1_770_000_000; pts = []; y = 0.0
    for i in range(1200): y += 3.0; pts.append(y)                                    # 3 m/s to the first checkpoint at 3600 m, 400 s there, on, and the run ends before the end of the second route
    pts += [y] * 400
    for i in range(900): y += 3.0; pts.append(y)
    body = ''.join(f'<trkpt lat="{50.0 + m / 110540.0}" lon="5.0"><ele>{100 + min(m, 3600) / 60.0}</ele><time>{datetime.fromtimestamp(t0 + i, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}</time></trkpt>' for i, m in enumerate(pts))
    TK.add(rd, 'run.gpx', f'<?xml version="1.0"?><gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1"><trk><trkseg>{body}</trkseg></trk><!--{"x" * 100}--></gpx>'.encode())
    route = lambda a, b: gpx([(50.0 + k * 30 / 110540.0, 5.0) for k in range(a, b)], route=True, timed=False)
    TK.add(rd, 'one.gpx', route(0, 121)); TK.add(rd, 'two.gpx', route(121, 361)); TK.add(rd, 'three.gpx', route(361, 481))                                    # the run ends on the second; the third is not reached
    tm = TK.timing(rd); assert tm['consistent'] and tm['total_s'] == 2499 and 3590 <= tm['ran_m'][list(tm['sections'])[0]] <= 3640 and list(tm['checkpoints']) == [1]
    assert sum(tm['checkpoints'].values()) + sum(tm['sections'].values()) == tm['total_s'] and 370 <= tm['checkpoints'][1] <= 400 and len(tm['sections']) == 2
    ls = TK.listing(rd); r = {t['name']: t.get('time_s') for t in ls['tracks'] if t['kind'] == 'route'}; assert r['one.gpx'] > 1150 and r['two.gpx'] > 800 and r['three.gpx'] is None and ls['timing']['total_s'] == 2499
    assert TK.timing(str(tmp_path / 'none')) == {}
    one = next(x for x in ls['tracks'] if x['name'] == 'one.gpx'); assert 3.5 <= one['ran_km'] <= 3.7 and 300 <= one['pace_s_km'] <= 340 and 55 <= one['ascent_m'] <= 62 and one['descent_m'] == 0 and 55 <= ls['timing']['ascent_m'] <= 62 and ls['timing']['descent_m'] == 0
    ar = tm['arrivals'][1]; assert ar['elapsed_s'] == round(ar['t'] - tm['start']) and 3.5 <= ar['km'] <= 3.7 and 1190 <= ar['elapsed_s'] <= 1230                  # at the first checkpoint: km and time from the start of the run


def test_start_finish_and_end_of_the_run_markers(tmp_path):
    rd = str(tmp_path); north = lambda a, b: [(50.0 + i * 1e-4, 5.0) for i in range(a, b)]
    assert TK.end_markers(rd) is None
    TK.add(rd, 'run.gpx', gpx(north(0, 500)))
    m = TK.end_markers(rd); assert m['finish'] is None and m['start']['lat'] == 50.0 and abs(m['end']['lat'] - 50.0499) < 1e-6 and 5.4 < m['end']['km'] < 5.6 and m['end']['elapsed_s'] == 499
    TK.add(rd, 'one.gpx', gpx(north(0, 300), route=True, timed=False)); TK.add(rd, 'two.gpx', gpx(north(300, 800), route=True, timed=False))                     # the second route is longer than the run: the finish line is its end
    m = TK.end_markers(rd); assert abs(m['finish']['lat'] - 50.0799) < 1e-4 and m['end']['lat'] < m['finish']['lat'] and TK.listing(rd)['markers']['finish'] == m['finish']


def _stop_run(rd, routes):
    from datetime import datetime, timezone
    t0 = 1_770_000_000; pts = []; y = 0.0
    for i in range(1200): y += 3.0; pts.append(y)                                   # 3 m/s to 3600 m, 400 s standing there, on to 6300 m
    pts += [y] * 400
    for i in range(900): y += 3.0; pts.append(y)
    body = ''.join(f'<trkpt lat="{50.0 + m / 110540.0}" lon="5.0"><time>{datetime.fromtimestamp(t0 + i, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}</time></trkpt>' for i, m in enumerate(pts))
    TK.add(rd, 'run.gpx', f'<?xml version="1.0"?><gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1"><trk><trkseg>{body}</trkseg></trk><!--{"x" * 100}--></gpx>'.encode())
    for name, (a, b) in routes: TK.add(rd, name, gpx([(50.0 + k * 30 / 110540.0, 5.0) for k in range(a, b)], route=True, timed=False))
    return t0


def test_stage_schedule_runs_from_before_the_race_to_after_it(tmp_path):
    rd = str(tmp_path); t0 = _stop_run(rd, [('one.gpx', (0, 121)), ('two.gpx', (121, 361))])                               # the run ends before the end of the second route
    s = TK.stage_schedule(rd); assert [l for _, l in s] == ['Before Race', 'At Start', 'Stage 1', 'Checkpoint 1', 'Stage 2', 'After Race']
    assert s[0][0] == float('-inf') and s[1][0] == t0 and 90 <= s[2][0] - t0 <= 110 and 1190 <= s[3][0] - t0 <= 1210 and 380 <= s[4][0] - s[3][0] <= 400 and s[-1][0] == t0 + 2499 and [a for a, _ in s] == sorted(a for a, _ in s)


def test_the_finish_stage_only_when_the_run_got_to_the_end_of_the_last_route(tmp_path):
    rd = str(tmp_path); _stop_run(rd, [('one.gpx', (0, 121)), ('two.gpx', (121, 211))])                                    # the second route ends where the run does
    assert [l for _, l in TK.stage_schedule(rd)] == ['Before Race', 'At Start', 'Stage 1', 'Checkpoint 1', 'Stage 2', 'At Finish', 'After Race']


def test_without_routes_the_stage_between_start_and_end_is_on_course(tmp_path):
    rd = str(tmp_path); _stop_run(rd, []); assert [l for _, l in TK.stage_schedule(rd)] == ['Before Race', 'At Start', 'On Course', 'After Race']
    assert TK.stage_schedule(str(tmp_path / 'none')) == []


def test_progress_along_the_route_holds_where_the_run_left_it_while_the_run_is_off_course(tmp_path):
    from datetime import datetime, timezone
    rd = str(tmp_path); t0 = 1_770_000_000; rows = []; y = 0.0
    for i in range(600): y += 3.0; rows.append((i, y, 0.0))                                                                 # along the route to 1800 m
    for i in range(300): rows.append((600 + i, y, 0.0045 * (i + 1) / 300))                                                  # then east, off it by up to ~320 m
    body = ''.join(f'<trkpt lat="{50.0 + m / 110540.0}" lon="{5.0 + x}"><time>{datetime.fromtimestamp(t0 + i, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}</time></trkpt>' for i, m, x in rows)
    TK.add(rd, 'run.gpx', f'<?xml version="1.0"?><gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1"><trk><trkseg>{body}</trkseg></trk><!--{"x" * 100}--></gpx>'.encode())
    TK.add(rd, 'only.gpx', gpx([(50.0 + k * 30 / 110540.0, 5.0) for k in range(0, 201)], route=True, timed=False))             # 6000 m long
    p = TK.stage_progress(rd)['Stage 1']; assert 5990 <= p['route_m'] <= 6010 and len(p['t']) > 100
    on = p['prog'][p['t'] < t0 + 580]; assert on[-1] > 1600 and np.all(np.diff(on) >= -1)                                       # moving along the route
    off = p['prog'][p['t'] > t0 + 800]; assert off.max() - off.min() < 50 and 1700 <= off[-1] <= 1900                          # then it stays where the run left the route
    assert TK.stage_progress(str(tmp_path / 'none')) == {}


def test_the_finish_entry_is_the_routes_finish_and_says_whether_the_run_got_there(tmp_path):
    rd = str(tmp_path); _stop_run(rd, [('one.gpx', (0, 121)), ('two.gpx', (121, 361))])                                     # the run ends 2670 m into the second route (7170 m long)
    f = TK.finish_info(rd); assert f['reached'] is False and f['t'] is None and f['time_s'] is None and 3590 + 7170 - 40 <= f['route_m'] <= 3600 + 7170 + 40
    assert 3590 + 2640 <= f['covered_m'] <= 3600 + 2700 and TK.listing(rd)['finish'] == f
    rd2 = str(tmp_path / 'fin'); os.makedirs(rd2); _stop_run(rd2, [('one.gpx', (0, 121)), ('two.gpx', (121, 211))])        # it got to the end
    g = TK.finish_info(rd2); assert g['reached'] is True and 0 <= g['time_s'] < 200 and 2300 < g['elapsed_s'] < 2499 and 5.5 < g['km'] < 6.4 and abs(g['covered_m'] - g['route_m']) < 100
    assert TK.finish_info(str(tmp_path / 'none')) is None


def test_the_race_story_gives_the_script_writer_the_course_the_checkpoints_and_the_cut_offs(tmp_path):
    rd = str(tmp_path); t0 = _stop_run(rd, [('one.gpx', (0, 121)), ('two.gpx', (121, 361))])                                    # the run stood 400 s at the first checkpoint, ended 2670 m into a 7170 m second route
    TK.set_cutoff(rd, 'cp:1', '1h')                                                                                            # 3600 s after the start: reached at about 1200 s
    st = TK.race_story(rd)
    assert [s['n'] for s in st['stages']] == [1, 2] and st['stages'][0]['complete'] and not st['stages'][1]['complete'] and st['stages'][1]['off_course'] is None
    c = st['checkpoints'][0]; assert c['n'] == 1 and 1190 <= c['elapsed_s'] <= 1215 and c['cutoff_s'] == 3600 and 2300 < c['margin_s'] < 2450 and 3.5 < c['km'] < 3.7 and 370 <= c['stopped_s'] <= 400
    assert st['finish']['reached'] is False
    text = '\n'.join(TK.story_text(st)); assert 'Course: 2 stages with 1 checkpoints' in text and 'checkpoint 1: reached after 20m' in text and 'to spare' in text and 'finish: NOT reached' in text and 'against' not in text      # (nothing off course: not mentioned)
    p = TK.story_at(st, t0 + 1500); assert p['stage'] == 2 and p['checkpoints_done'] == 1 and p['next'] == 'the finish' and p['left_s'] is None and p['last_margin_s'] == c['margin_s'] and p['off_course'] is None
    q = TK.story_at(st, t0 + 600); assert q['stage'] == 1 and q['checkpoints_done'] == 0 and q['next'] == 'checkpoint 1' and q['left_s'] == 3000 and 1.7 < q['stage_km_done'] < 1.9 and q['km_to_next'] > 1.7
    line = TK.story_line(q); assert 'stage 1 of 2' in line and '0 of 1 checkpoints done' in line and '50m left to the cut-off for checkpoint 1' in line
    assert TK.race_story(str(tmp_path / 'none')) is None


def test_the_race_story_mentions_an_off_course_stage_only_when_the_distance_run_is_more_than_10_percent_off(tmp_path):
    from datetime import datetime, timezone
    rd = str(tmp_path); t0 = 1_770_000_000; rows = []; y = 0.0
    for i in range(600): y += 3.0; rows.append((i, y, 0.0))
    for i in range(300): rows.append((600 + i, y, 0.02 * (i + 1) / 300))
    body = ''.join(f'<trkpt lat="{50.0 + m / 110540.0}" lon="{5.0 + x}"><time>{datetime.fromtimestamp(t0 + i, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}</time></trkpt>' for i, m, x in rows)
    TK.add(rd, 'run.gpx', f'<?xml version="1.0"?><gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1"><trk><trkseg>{body}</trkseg></trk><!--{"x" * 100}--></gpx>'.encode())
    TK.add(rd, 'only.gpx', gpx([(50.0 + k * 30 / 110540.0, 5.0) for k in range(0, 201)], route=True, timed=False))
    st = TK.race_story(rd); s = st['stages'][0]; assert s['off_course'] and s['off_course']['ran_km'] > s['off_course']['route_km'] * 1.1
    assert 'against' in '\n'.join(TK.story_text(st)); late = TK.story_at(st, t0 + 800); assert late['off_course'] and late['off_course']['ran_km'] > late['off_course']['route_km'] * 1.1
    assert TK.story_at(st, t0 + 300)['off_course'] is None                                                                   # on the route at that time: nothing to say


def _run_with_pause(pause_s, drift_m=5.0, pause_at_m=3000.0, area=None):
    """A run at 3 m/s north along a meridian that stands (drifting a little) for `pause_s` seconds at `pause_at_m` metres; one point a second."""
    pts = []; m = 0.0; t = 0
    while m < pause_at_m: pts.append((50.0 + m / 110540.0, 5.0)); m += 3.0; t += 1
    for k in range(pause_s): pts.append((50.0 + (m + drift_m * np.sin(k / 30.0)) / 110540.0, 5.0)); t += 1
    for _ in range(600): pts.append((50.0 + m / 110540.0, 5.0)); m += 3.0
    return pts


def test_a_stop_of_ten_minutes_in_one_small_place_away_from_the_checkpoints_is_found_with_when_and_how_long(tmp_path):
    rd = str(tmp_path / 'proj'); os.makedirs(rd); TK.add(rd, 'race.gpx', gpx(_run_with_pause(15 * 60))); s, = TK.other_stops(rd)
    assert 880 <= s['stopped_s'] <= 970 and s['arrived'] < s['left'] and 2.5 < s['km'] < 3.6 and s['radius_m'] == 60 and abs(s['lat'] - (50.0 + 3000 / 110540.0)) < 0.002
    pois = [p for p in TK.listing(rd)['pois'] if p['sym'] == 'stop']; assert len(pois) == 1 and pois[0]['name'] == 'Stop 1' and pois[0]['stop']['stopped_s'] == s['stopped_s'] and 'km' in pois[0]['desc']


def test_a_shorter_stop_or_one_that_wanders_off_or_is_at_the_start_or_end_is_not_another_stop(tmp_path):
    rd = str(tmp_path / 'a'); os.makedirs(rd); TK.add(rd, 'race.gpx', gpx(_run_with_pause(8 * 60))); assert TK.other_stops(rd) == []                                     # 8 minutes: too short
    rd = str(tmp_path / 'b'); os.makedirs(rd); TK.add(rd, 'race.gpx', gpx(_run_with_pause(15 * 60, drift_m=150.0))); assert TK.other_stops(rd) == []                      # wanders 150 m about: not one small place
    rd = str(tmp_path / 'c'); os.makedirs(rd); TK.add(rd, 'race.gpx', gpx(_run_with_pause(15 * 60, pause_at_m=30.0))); assert TK.other_stops(rd) == []                    # at the start: that is the start's
    rd = str(tmp_path / 'd'); os.makedirs(rd); assert TK.other_stops(rd) == []                                                                                            # no track
