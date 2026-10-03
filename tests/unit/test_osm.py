"""The OpenStreetMap lookup service (mirror pool, cache) and the road stretches built on it. No network: the fetch, sleep and clock are fakes."""
import json, math

import numpy as np
import pytest

from strata360.gps import osm, roads

OK = json.dumps({'elements': []}).encode()


class Net:
    """A scripted network: `plan[url]` is a list of replies (bytes, or an Exception to raise), used in turn, the last one repeating. A fake clock moves only when something sleeps."""
    def __init__(self, plan): self.plan, self.calls, self.now, self.slept = plan, [], 1000.0, 0.0
    def fetch(self, url, data, timeout):
        self.calls.append(url); r = self.plan.get(url, [OK]); r = r[min(sum(1 for c in self.calls if c == url) - 1, len(r) - 1)]
        if isinstance(r, Exception): raise r
        return r
    def sleep(self, s): self.now += s; self.slept += s
    def clock(self): return self.now


def pool(tmp_path, net, mirrors=('http://a', 'http://b', 'http://c'), **kw):
    return osm.Overpass(str(tmp_path), mirrors=list(mirrors), fetch=net.fetch, sleep=net.sleep, clock=net.clock, **kw)


def test_requests_go_round_the_mirrors(tmp_path):
    net = Net({}); p = pool(tmp_path, net)
    for i in range(6): assert p.query(f'q{i}') == {'elements': []}
    assert net.calls == ['http://a', 'http://b', 'http://c'] * 2


def test_a_mirror_is_used_at_most_once_per_gap(tmp_path):
    net = Net({}); p = pool(tmp_path, net, mirrors=['http://a'], min_gap_s=2.0)
    p.query('q1'); p.query('q2')
    assert net.slept == pytest.approx(2.0, abs=0.1)


def test_answers_are_cached_on_disk_and_shared_by_key(tmp_path):
    net = Net({}); p = pool(tmp_path, net)
    p.query('same'); p.query('same'); p.query('other', key='same')
    assert net.calls == ['http://a'] and p.cached == 2
    again = pool(tmp_path, Net({'http://a': [OSError('down')]}))                       # a new pool (a later run) needs no network for it
    assert again.query('same') == {'elements': []} and again.cached == 1


def test_cache_files_are_named_like_the_places_stage_does(tmp_path):
    import hashlib
    pool(tmp_path, Net({})).query('x', key='ovp|k')
    assert (tmp_path / (hashlib.sha1(b'ovp|k').hexdigest()[:20] + '.json')).exists()


def test_a_failing_mirror_is_skipped_and_rests(tmp_path):
    net = Net({'http://a': [OSError('429')]}); p = pool(tmp_path, net)
    assert p.query('q1') == {'elements': []}
    assert net.calls == ['http://a', 'http://b'] and p.stats['http://a'] == dict(ok=0, failed=1)
    for i in range(3): p.query(f'n{i}')
    assert net.calls.count('http://a') == 1                                            # still resting


def test_the_rest_grows_with_each_failure_in_a_row_and_a_success_forgives(tmp_path):
    net = Net({'http://a': [OSError('x')] * 3 + [OK]}); p = pool(tmp_path, net, mirrors=['http://a'], tries=3, min_gap_s=0.0)
    assert p.query('q') is None
    assert p._ready['http://a'] - net.now >= osm.COOLDOWN_S * 4 - 1                    # after 3 failures: 20, 40, 80 s (the last one remaining)
    net.now += 1000; assert p.query('q2') == {'elements': []} and p._bad['http://a'] == 0


def test_bad_replies_count_as_failures(tmp_path):
    for bad in (b'<html>406 Not Acceptable</html>', json.dumps({'elements': [], 'remark': 'runtime error: Query timed out'}).encode(), b'[]'):
        net = Net({'http://a': [bad]}); p = pool(tmp_path / str(len(bad)), net, mirrors=['http://a', 'http://b'])
        assert p.query('q') == {'elements': []} and net.calls == ['http://a', 'http://b']


def test_nothing_is_cached_when_every_try_fails(tmp_path):
    net = Net({m: [OSError('x')] for m in ('http://a', 'http://b')}); p = pool(tmp_path, net, mirrors=['http://a', 'http://b'], tries=4)
    assert p.query('q') is None and list(tmp_path.iterdir()) == []
    assert len(net.calls) == 4 and net.slept >= osm.COOLDOWN_S - 1                      # the tries after the first pair waited for a mirror to rest


def test_query_many_keeps_the_order_and_marks_the_failures(tmp_path):
    net = Net({'http://a': [json.dumps({'elements': [1]}).encode()]}); p = pool(tmp_path, net, mirrors=['http://a'])
    assert p.query_many(['q1', ('q2', 'k2')]) == [{'elements': [1]}, {'elements': [1]}]
    assert p.cached == 0 and net.calls == ['http://a', 'http://a']


def test_pool_is_shared_per_cache_folder(tmp_path):
    assert osm.pool(str(tmp_path)) is osm.pool(str(tmp_path)) and osm.pool(str(tmp_path)) is not osm.pool(str(tmp_path / 'x'))


def test_ways_query_and_parse():
    assert osm.ways_ql((50.0, 5.0, 50.1, 5.1), ('primary', 'service')) == '[out:json][timeout:90];way["highway"~"^(primary|service)$"](50.00000,5.00000,50.10000,5.10000);out tags geom;'
    got = osm.ways({'elements': [dict(type='way', id=7, tags=dict(highway='service', name='Rue'), geometry=[dict(lat=1, lon=2), dict(lat=3, lon=4)]), dict(type='node', id=8), dict(type='way', id=9, tags={})]})
    assert got == [dict(id=7, highway='service', name='Rue', geometry=[(1, 2), (3, 4)])]


# --- roads ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------
LAT0, LON0 = 50.42, 5.63
M = 1 / 111320.0                                    # degrees of latitude per metre


def run_north(km):
    """A track running due north from (LAT0, LON0), a point per 5 m."""
    d = np.arange(0, km * 1000, 5.0); return LAT0 + d * M, np.full_like(d, LON0), d


class Service:
    """Stands in for the pool: answers every tile with the same ways."""
    def __init__(self, ways): self.ways, self.asked = ways, []
    def query_many(self, qs): self.asked += qs; return [{'elements': self.ways} for _ in qs]


def way(i, highway, m0, m1, east_m=0.0, name=None):
    lon = LON0 + east_m * M / math.cos(math.radians(LAT0))
    return dict(type='way', id=i, tags=dict(highway=highway, **({'name': name} if name else {})), geometry=[dict(lat=LAT0 + m0 * M, lon=lon), dict(lat=LAT0 + m1 * M, lon=lon)])


def test_stretches_are_the_runs_on_a_road(tmp_path):
    lat, lon, d = run_north(2.0)                                                       # 2 km north
    svc = Service([way(1, 'residential', 200, 900, name='Rue A'), way(2, 'secondary', 1200, 1700, east_m=3, name='N66'), way(3, 'residential', 1750, 1850, east_m=30)])
    out = roads.stretches(lat, lon, d, str(tmp_path), svc=svc)
    assert [(s['km0'], s['km1'], s['highways'], s['names']) for s in out] == [(0.2, 0.9, ['residential'], ['Rue A']), (1.2, 1.7, ['secondary'], ['N66'])]
    assert out[0]['length_m'] == 700 or 680 <= out[0]['length_m'] <= 720                # (a sample every 20 m)


def test_a_road_beside_the_track_does_not_count(tmp_path):
    lat, lon, d = run_north(1.0)
    assert roads.stretches(lat, lon, d, str(tmp_path), svc=Service([way(1, 'residential', 0, 1000, east_m=25)])) == []


def test_short_stretches_are_dropped(tmp_path):
    lat, lon, d = run_north(1.0)
    svc = Service([way(1, 'residential', 100, 300)])
    assert roads.stretches(lat, lon, d, str(tmp_path), svc=svc) == [] and len(roads.stretches(lat, lon, d, str(tmp_path), min_m=150, svc=svc)) == 1


def test_a_failed_tile_is_an_error_not_an_empty_answer(tmp_path):
    class Down(Service):
        def query_many(self, qs): return [None for _ in qs]
    lat, lon, d = run_north(0.5)
    with pytest.raises(RuntimeError, match='1 of 1 tiles'): roads.stretches(lat, lon, d, str(tmp_path), svc=Down([]))


def test_tiles_cover_every_square_the_track_touches():
    lat = np.array([50.05, 50.15, 50.15]); lon = np.array([5.05, 5.05, 5.15])
    assert len(roads.tiles(lat, lon)) == 3


def test_sample_steps_by_distance_and_drops_missing_fixes():
    lat = np.array([1.0, np.nan, 1.2, 1.3]); lon = np.array([2.0, 2.1, 2.2, 2.3]); dist = np.array([0.0, 10.0, 25.0, 45.0])
    la, lo, d = roads.sample(lat, lon, dist, step_m=20.0)
    assert list(d) == [0.0, 20.0, 40.0] and list(la) == [1.0, 1.2, 1.3]


# --- the places stage uses the pool for the public server only ---------------------------------------------------------------------------------------------------------
def test_places_nearby_uses_the_mirror_pool_for_the_public_server(tmp_path, monkeypatch):
    from strata360.analysis import places
    asked = {}
    class P:
        def query(self, ql, key=None): asked.update(key=key); return {'elements': [dict(type='node', lat=50.001, lon=5.0, tags=dict(name='Ferrières', place='village'))]}
    monkeypatch.setattr(osm, 'pool', lambda cache_dir: P())
    got = places.nearby(50.0, 5.0, str(tmp_path))
    assert got == [dict(name='Ferrières', kind='place=village', distance_m=111)] and asked['key'] == f'ovp|{places.OVERPASS}|50.000|5.000|1000'


def test_places_nearby_asks_only_a_server_of_your_own(tmp_path, monkeypatch):
    from strata360.analysis import places
    monkeypatch.setattr(osm, 'pool', lambda cache_dir: pytest.fail('the pool must not be used'))
    monkeypatch.setattr(places, '_get', lambda url, cache_dir, key, data=None, timeout=40: {'elements': []})
    assert places.nearby(50.0, 5.0, str(tmp_path), url='http://mine/api') == []
