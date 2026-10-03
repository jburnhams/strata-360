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
    assert 880 <= c['stopped_s'] <= 900 and c['zone_s'] >= c['stopped_s'] and c['zone_s'] < 900 + 2 * 300 / 3 + 60 and c['arrived'] > c['zone_in'] and c['left'] < c['zone_out']        # the run-in and run-out at 3 m/s inside the zone are not counted
    cp = [p for p in TK.listing(rd)['pois'] if p['sym'] == 'checkpoint'][0]; assert cp['stop']['stopped_s'] == c['stopped_s']
    assert TK.checkpoint_stops(str(tmp_path / 'none')) == {}
