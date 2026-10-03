"""The street view nearest to a point clicked on the map: from each provider, nearest capture runs first, with the rules that would rule each out."""
import datetime as dt, math

import numpy as np
import pytest

from strata360 import streetview as SV

LAT0, LON0 = 50.13, 5.79
M = 1 / 111320.0
T0 = dt.datetime(2026, 2, 20, 19, 0, tzinfo=dt.timezone.utc).timestamp()            # the run starts at 19:00 UTC in February: dark


def track():
    n = 4000; d = 3.0 * np.arange(n); return dict(t=T0 + np.arange(n), lat=LAT0 + d * M, lon=np.full(n, LON0), dist=d)


def lonm(m): return m * M / math.cos(math.radians(LAT0))


def mfr(i, north, east=0.0, seq='s1', angle=0, pano=False, captured=dt.datetime(2024, 7, 1, 12, tzinfo=dt.timezone.utc).timestamp(), make='GoPro', model='HERO'):
    return dict(id=f'm{i}', sequence=seq, compass_angle=angle, is_pano=pano, computed_geometry=dict(coordinates=[LON0 + lonm(east), LAT0 + north * M]), captured_at=captured * 1000, width=4000, height=3000, make=make, model=model)


def pfr(i, north, east=0.0, seq='c1', az=0, pano=True):
    return dict(id=f'p{i}', collection=seq, geometry=dict(coordinates=[LON0 + lonm(east), LAT0 + north * M]), assets=dict(sd=dict(href=f'https://pmx/{i}.jpg')),
                properties={'datetime': '2025-04-10T07:00:00+00:00', 'view:azimuth': az, 'pers:interior_orientation': {'field_of_view': 360 if pano else 70, 'sensor_array_dimensions': [5760, 2880] if pano else [1000, 600], 'camera_manufacturer': 'GoPro', 'camera_model': 'Max'}})


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    from strata360.gps import osm
    monkeypatch.setattr(osm, 'pool', lambda cache_dir: (_ for _ in ()).throw(AssertionError('a test asked the real road data')))


class Net:
    def __init__(self, mly=(), pmx=(), google=None): self.mly, self.pmx, self.google, self.calls = list(mly), list(pmx), google or {}, []
    def __call__(self, url, params):
        self.calls.append((url.split('/')[2], params.get('bbox') or params.get('location')))
        if 'graph.mapillary' in url:
            w, s, e, n = (float(x) for x in params['bbox'].split(','))
            return {'data': [f for f in self.mly if s <= f['computed_geometry']['coordinates'][1] <= n and w <= f['computed_geometry']['coordinates'][0] <= e]}
        if 'panoramax' in url:
            w, s, e, n = (float(x) for x in params['bbox'].split(','))
            return {'features': [f for f in self.pmx if s <= f['geometry']['coordinates'][1] <= n and w <= f['geometry']['coordinates'][0] <= e]}
        la, lo = (float(x) for x in params['location'].split(',')); dist = lambda p: math.hypot((p[1] - la) * 111320, (p[2] - lo) * 111320 * math.cos(math.radians(la))); best = min(self.google.get('panos', []), key=dist, default=None)
        return dict(status='OK', pano_id=best[0], location=dict(lat=best[1], lng=best[2]), date='2024-09') if best and self.google.get('ok', True) and dist(best) <= params.get('radius', 50) else dict(status='ZERO_RESULTS')


def roads_doc(rd, km0=0.0, km1=9.0):
    SV._save(rd, 'roads', dict(schema=1, id='r', stretches=[dict(id='R1', km0=km0, km1=km1, length_m=int((km1 - km0) * 1000), highways=[], names=[], line=[[LAT0, LON0], [LAT0 + 0.01, LON0]])], run=[], total_km=12))


class Osm:
    """The road data: one road running north from the start for `metres`."""
    def __init__(self, metres=3000.0, name='Rue A'): self.metres, self.name, self.asked = metres, name, 0
    def query(self, ql):
        self.asked += 1; return {'elements': [dict(type='way', id=1, tags=dict(highway='residential', name=self.name), geometry=[dict(lat=LAT0, lon=LON0), dict(lat=LAT0 + self.metres * M, lon=LON0)])]}


def near(tmp_path, net, lat=LAT0 + 600 * M, lon=LON0, n=3, **kw):
    kw.setdefault('tr', track()); kw.setdefault('osm_svc', Osm()); return SV.near_point(str(tmp_path), lat, lon, n, get=net, token='tok', gkey='gk', **kw)


def test_the_nearest_capture_runs_come_first_one_per_sequence_with_how_far_and_what_camera(tmp_path):
    net = Net(mly=[mfr(i, 600 + 5 * i, east=3, seq='near') for i in range(6)] + [mfr(20 + i, 640 + 5 * i, east=40, seq='far') for i in range(3)] + [mfr(30, 650, east=70, seq='farthest', pano=True)])
    r = near(tmp_path, net)['providers']['mapillary']; ids = [i['sequence'] for i in r['items']]
    assert ids == ['near', 'far', 'farthest'] and r['radius_m'] == 100.0 and r['items'][0]['pictures'] == 6 and r['items'][0]['distance_m'] == pytest.approx(3.0, abs=0.2) and r['items'][0]['kind'] == '2d' and r['items'][2]['kind'] == '360'
    assert r['items'][0]['camera'] == 'GoPro HERO' and r['items'][0]['size'] == [4000, 3000] and r['items'][0]['spacing_m'] == pytest.approx(5.0, abs=0.2)
    assert len(near(tmp_path, net, n=2)['providers']['mapillary']['items']) == 2


def test_the_search_widens_until_there_are_enough_capture_runs_and_gives_what_it_has_at_the_end(tmp_path):
    net = Net(mly=[mfr(1, 600, east=30, seq='a'), mfr(2, 600, east=200, seq='b'), mfr(3, 600, east=400, seq='c')])
    r = near(tmp_path, net)['providers']['mapillary']; assert [i['sequence'] for i in r['items']] == ['a', 'b', 'c'] and r['radius_m'] == 500.0
    r = near(tmp_path, Net(mly=[mfr(1, 600, east=30, seq='a')]))['providers']['mapillary']; assert [i['sequence'] for i in r['items']] == ['a'] and r['radius_m'] == 500.0
    assert near(tmp_path, Net())['providers']['mapillary']['items'] == []


def rules(item): return {r['key']: r for r in item['rules']}


def test_each_item_says_what_would_rule_it_out_the_run_the_road_the_direction_the_pictures_the_light_and_the_footage(tmp_path):
    roads_doc(str(tmp_path), 0.0, 1.0)
    osm = Osm(1000.0)                                                                                                                      # the road runs for the first kilometre only
    net = Net(mly=[mfr(i, 600 + 5 * i, east=3, seq='good', captured=T0 - 86400 * 365 + 600) for i in range(40)] + [mfr(100 + i, 1500 + 5 * i, east=30, seq='off', angle=180) for i in range(3)])
    r = near(tmp_path, net, lat=LAT0 + 900 * M, n=2, clips=[], gaps=[], osm_svc=osm)['providers']['mapillary']['items']; good = next(i for i in r if i['sequence'] == 'good'); r0 = rules(good)
    assert r0['near_run']['ok'] is True and r0['on_road']['ok'] is True and 'Rue A' in r0['on_road']['text'] and r0['direction']['ok'] is True and 'forward' in r0['direction']['text'] and r0['pictures']['ok'] is True and '40 pictures' in r0['pictures']['text'] and r0['footage']['ok'] is True
    off = next(i for i in near(tmp_path, net, lat=LAT0 + 1500 * M, n=2, clips=[], gaps=[], osm_svc=osm)['providers']['mapillary']['items'] if i['sequence'] == 'off'); r1 = rules(off)
    assert r1['near_run']['ok'] is False and 'm from the run' in r1['near_run']['text'] and r1['on_road']['ok'] is False and 'no road within 12 m of the run there' in r1['on_road']['text'] and r1['direction']['ok'] is False and 'back' in r1['direction']['text'] and r1['pictures']['ok'] is False and '3 pictures' in r1['pictures']['text'] and '(a clip needs 30' in r1['pictures']['text']
    assert off['usable'] is False and len(off['ruled_out']) >= 4 and off['ruled_out'][0] == r1['near_run']['text']


def test_the_light_rule_uses_the_sun_at_the_real_dates_and_a_section_already_found_is_named(tmp_path):
    summer_day = dt.datetime(2024, 7, 1, 12, tzinfo=dt.timezone.utc).timestamp()
    net = Net(mly=[mfr(i, 600 + 5 * i, east=3, seq='dayview', captured=summer_day) for i in range(40)]); roads_doc(str(tmp_path))
    item = near(tmp_path, net, n=1)['providers']['mapillary']['items'][0]; lt = rules(item)['light']; assert lt['ok'] is False and 'above the horizon (daylight)' in lt['text'] and 'below the horizon (dark)' in lt['text'] and item['usable'] is False
    dark = Net(mly=[mfr(i, 600 + 5 * i, east=3, seq='nightview', captured=dt.datetime(2024, 2, 20, 18, 30, tzinfo=dt.timezone.utc).timestamp()) for i in range(40)])
    assert rules(near(tmp_path, dark, n=1)['providers']['mapillary']['items'][0])['light']['ok'] is True
    SV._save(str(tmp_path), 'mapillary', SV.provider_doc('mapillary', [dict(id='M7', provider='mapillary', stretch='R1', kind='2d', km0=0.58, km1=0.8, length_m=220, frames=40, spacing_m=5.0, years=[2024], camera=None, size=None, seq='dayview', angles=None, items=[dict(id='m0', km=0.58, lat=LAT0, lon=LON0, b=0, t=summer_day)])], SV.load(str(tmp_path), 'roads')))
    named = rules(near(tmp_path, net, n=1)['providers']['mapillary']['items'][0])['pictures']; assert named['ok'] is True and 'part of section M7' in named['text']


def test_the_footage_rule_says_whether_the_place_is_in_a_gap_or_on_a_camera_clip(tmp_path):
    net = Net(mly=[mfr(i, 600 + 5 * i, east=3, seq='s') for i in range(5)]); at = T0 + 600 / 3.0
    covered = near(tmp_path, net, n=1, clips=[dict(label='0021', t0=at - 60, t1=at + 60)], gaps=[])['providers']['mapillary']['items'][0]; f = rules(covered)['footage']; assert f['ok'] is False and 'overlaps camera clip 0021' in f['text']
    gap = near(tmp_path, net, n=1, clips=[dict(label='0021', t0=at - 900, t1=at - 600)], gaps=[dict(id='G07', t0=at - 500, t1=at + 500)])['providers']['mapillary']['items'][0]; assert rules(gap)['footage'] == dict(key='footage', ok=True, text='fills gap G07')
    assert 'footage' not in rules(near(tmp_path, net, n=1)['providers']['mapillary']['items'][0])                                    # without the clips the rule is left out


def test_panoramax_is_searched_by_collection_and_google_panoramas_are_grouped_into_runs_followed_along_the_road(tmp_path):
    road = [(f'g{i}', LAT0 + (560 + 12 * i) * M, LON0) for i in range(10)]                                                              # ten panoramas 12 m apart along the road
    other = [(f'h{i}', LAT0 + (600 + 12 * i) * M, LON0 + lonm(70)) for i in range(4)]                                                   # another run 70 m to the east
    net = Net(pmx=[pfr(i, 600 + 7 * i, east=2, seq='c1') for i in range(4)] + [pfr(9, 610, east=50, seq='c2', az=90, pano=False)], google=dict(panos=road + other))
    res = near(tmp_path, net, n=2)['providers']; assert [i['sequence'] for i in res['panoramax']['items']] == ['c1', 'c2'] and res['panoramax']['items'][0]['url'] == 'https://pmx/0.jpg' and res['panoramax']['items'][1]['kind'] == '2d'
    g = res['google']; first, second = g['items']; assert g['radius_m'] == 110.0 and first['pictures'] == 10 and first['spacing_m'] == pytest.approx(12.0, abs=0.5) and first['distance_m'] < 8 and first['sequence'].startswith('g:') and first['kind'] == '360'
    assert second['pictures'] >= 3 and second['distance_m'] > 50 and second['sequence'] != first['sequence']                                  # one entry for the run, not ten for its panoramas
    r = rules(first); assert 'terms' not in r and 'pictures' in r and r['light']['ok'] is None and 'month' in r['light']['text'] and '10 pictures' in r['pictures']['text']


def test_a_lone_google_panorama_is_a_run_of_one_and_nothing_is_invented(tmp_path):
    g = near(tmp_path, Net(google=dict(panos=[('only', LAT0 + 604 * M, LON0)])), n=3)['providers']['google']; assert [i['pictures'] for i in g['items']] == [1] and g['items'][0]['spacing_m'] is None and 'picture ' in rules(g['items'][0])['pictures']['text']


def test_a_provider_that_cannot_answer_says_why_and_the_others_still_do(tmp_path):
    net = Net(mly=[mfr(1, 600, seq='a')])
    r = SV.near_point(str(tmp_path), LAT0 + 600 * M, LON0, 2, tr=track(), get=net, token=None, gkey=None, osm_svc=Osm())['providers']; assert 'MAPILLARY_TOKEN' in r['mapillary']['error'] and 'GOOGLE_MAPS_API_KEY' in r['google']['error'] and r['panoramax']['error'] is None if 'error' in r['panoramax'] else True
    def failing(url, params):
        if 'mapillary' in url: raise RuntimeError('graph.mapillary.com did not answer')
        return net(url, params)
    r = SV.near_point(str(tmp_path), LAT0 + 600 * M, LON0, 2, tr=track(), get=failing, token='t', gkey=None, osm_svc=Osm())['providers']; assert r['mapillary']['error'] == 'graph.mapillary.com did not answer' and r['mapillary']['items'] == [] and 'panoramax' in r and not r['panoramax'].get('error')
    r = SV.near_point(str(tmp_path), LAT0 + 600 * M, LON0, 2, tr=track(), get=Net(google=dict(ok=False)), token='t', gkey='k', osm_svc=Osm())['providers']['google']; assert r['items'] == []


def test_without_a_race_track_the_run_rules_are_unknown(tmp_path):
    item = SV.near_point(str(tmp_path), LAT0, LON0, 1, tr=None, get=Net(mly=[mfr(1, 0, seq='a')]), token='t')['providers']['mapillary']['items'][0]; r = rules(item)
    assert r['near_run']['ok'] is None and 'no race track' in r['near_run']['text'] and r['light']['ok'] is None and r['on_road']['ok'] is None and item['run_distance_m'] is None and item['usable'] is False and item['ruled_out'] == [r['pictures']['text']]


def test_pictures_found_here_are_fetched_and_kept_for_every_provider(tmp_path, monkeypatch):
    monkeypatch.setattr(SV, '_key', lambda n: 'KEY'); rd = str(tmp_path); fetched = []; fetch = lambda url, params=None: fetched.append((url, params)) or b'JPEG'
    get = lambda url, params: {'thumb_256_url': 'https://cdn/m.jpg'}
    assert SV.image_near(rd, 'mapillary', dict(id='m1'), 256, fetch, get) == b'JPEG' and SV.image_near(rd, 'mapillary', dict(id='m1'), 100, fetch, get) == b'JPEG' and len(fetched) == 1
    assert SV.image_near(rd, 'panoramax', dict(id='p1', url='https://pmx/1.jpg'), 256, fetch, get) == b'JPEG' and fetched[-1][0] == 'https://pmx/1.jpg'
    SV.image_near(rd, 'google', dict(id='g1', compass=45), 256, fetch, get); SV.image_near(rd, 'google', dict(id='g1', compass=None), 256, fetch, get)
    assert fetched[-1][1] == dict(size='640x400', pano='g1', heading=45, fov=90, pitch=0, key='KEY') and len(fetched) == 3
    with pytest.raises(RuntimeError, match='no picture address'): SV.image_near(rd, 'panoramax', dict(id='p2'), 256, fetch, get)


def test_a_capture_run_found_near_a_click_is_made_a_section_kept_and_taken_out_again(tmp_path):
    rd = str(tmp_path); roads_doc(rd); net = Net(mly=[mfr(i, 1000 + 8 * i, seq='s1', pano=True) for i in range(60)])
    s = SV.promote(rd, 'mapillary', 'm10', 's1', LAT0 + 1080 * M, LON0, track(), token='t', get=net)
    assert s['manual'] and s['id'] == 'M+1' and s['frames'] >= 50 and any(i['id'] == 'm10' for i in s['items']) and s['road']['line']
    assert SV.promote(rd, 'mapillary', 'm10', 's1', LAT0 + 1080 * M, LON0, track(), token='t', get=net)['id'] == 'M+1' and len(SV.manual_sections(rd)) == 1      # not made twice
    out = SV.annotate(rd, {p: SV.load(rd, p) for p in SV.PROVIDERS}); assert [x['id'] for x in out if x.get('manual')] == ['M+1'] and SV.road_of(rd, s)['line'] == s['road']['line']
    assert SV.unpromote(rd, SV.section_key(s)) is True and SV.manual_sections(rd) == [] and SV.unpromote(rd, 'nope') is False


def test_a_capture_run_far_from_the_run_cannot_be_made_a_section(tmp_path):
    rd = str(tmp_path); net = Net(mly=[mfr(i, 1000 + 8 * i, east=300.0, seq='s1', pano=True) for i in range(60)])
    with pytest.raises(ValueError, match='within'): SV.promote(rd, 'mapillary', 'm10', 's1', LAT0 + 1080 * M, LON0 + lonm(300), track(), token='t', get=net)
