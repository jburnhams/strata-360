"""Street view stages: road stretches of the run, the sections of imagery on them from each provider, the staleness rule, and the pictures. No network: the providers' answers are scripted."""
import json, math

import numpy as np
import pytest

from strata360 import streetview as SV

LAT0, LON0 = 50.42, 5.63
M = 1 / 111320.0


def lonm(m): return m * M / math.cos(math.radians(LAT0))


def track(km=2.0):
    d = np.arange(0, km * 1000, 5.0); return dict(lat=LAT0 + d * M, lon=np.full_like(d, LON0), dist=d)


class Svc:
    def __init__(self, ways): self.ways = ways
    def query_many(self, qs): return [{'elements': self.ways} for _ in qs]


def road(i, m0, m1, highway='residential', name='Rue A'):
    return dict(type='way', id=i, tags=dict(highway=highway, name=name), geometry=[dict(lat=LAT0 + m0 * M, lon=LON0), dict(lat=LAT0 + m1 * M, lon=LON0)])


@pytest.fixture
def rdoc():
    return SV.find_roads(track(), '/x', svc=Svc([road(1, 200, 900), road(2, 1200, 1700, 'secondary', 'N66')]), log=lambda *_: None)


def test_roads_stage_lists_stretches_with_their_line_and_the_run_for_the_map(rdoc):
    assert [(s['id'], s['km0'], s['km1'], s['highways'], s['names']) for s in rdoc['stretches']] == [('R1', 0.2, 0.9, ['residential'], ['Rue A']), ('R2', 1.2, 1.7, ['secondary'], ['N66'])]
    assert rdoc['stretches'][0]['line'][0] == [round(LAT0 + 200 * M, 5), LON0] and len(rdoc['run']) == 20 and rdoc['total_km'] == 1.98 and len(rdoc['id']) == 10


def test_directions_are_relative_to_the_way_the_runner_went():
    assert [SV.direction(r) for r in (0, 30, -44, 60, 120, -90, 180, -170)] == ['forward', 'forward', 'forward', 'right', 'right', 'left', 'back', 'back']
    assert SV._rel(10, 350) == 20 and SV._rel(350, 10) == -20


def frames_answer(items):
    return lambda url, params: {'data': items}


def mly(i, north_m, east_m=0.0, seq='s1', angle=0, pano=False, t=1700000000000, w=4096, h=2160, make='GoPro', model='HERO'):
    return dict(id=f'm{i}', sequence=seq, compass_angle=angle, is_pano=pano, computed_geometry=dict(coordinates=[LON0 + lonm(east_m), LAT0 + north_m * M]), captured_at=t, width=w, height=h, make=make, model=model)


def test_mapillary_sections_split_on_gaps_group_by_sequence_and_tell_2d_from_360(rdoc):
    items = [mly(i, 250 + 10 * i, angle=0) for i in range(10)] + [mly(20 + i, 700 + 10 * i, angle=0) for i in range(3)]           # one sequence with a hole in it (340..700 m)
    items += [mly(40 + i, 300 + 20 * i, seq='s2', angle=180) for i in range(5)]                                                  # another, facing back at the runner
    items += [mly(60 + i, 300 + 25 * i, seq='p', pano=True, w=5760, h=2880, east_m=3) for i in range(6)]                       # a 360 camera, 3 m to the side
    items += [mly(90, 400, east_m=60)]                                                                                            # too far from the road: ignored
    secs = SV.find_mapillary(rdoc, 'tok', frames_answer(items), lambda *_: None)
    r1 = [s for s in secs if s['stretch'] == 'R1']
    assert len(r1) == 4 and {s['kind'] for s in r1} == {'360', '2d'} and not [s for s in secs if s['stretch'] == 'R2']
    by = {(s['seq'], s['km0']): s for s in r1}
    s1 = by[('s1', 0.25)]; assert (s1['frames'], s1['length_m'], s1['spacing_m'], s1['kind'], s1['angles'], s1['years'], s1['camera'], s1['size']) == (10, 90, 10.0, '2d', {'forward': 10}, [2023], 'GoPro HERO', [4096, 2160])
    assert by[('s1', 0.7)]['frames'] == 3
    assert next(s for s in r1 if s['seq'] == 's2')['angles'] == {'back': 5}
    p = next(s for s in r1 if s['seq'] == 'p'); assert p['kind'] == '360' and p['angles'] is None and p['frames'] == 6 and p['size'] == [5760, 2880]
    assert [s['id'] for s in secs] == ['M1', 'M2', 'M3', 'M4'] and secs[0]['km0'] <= secs[-1]['km0']
    assert s1['items'][0]['id'] == 'm0' and s1['items'][0]['a'] == 0 and s1['items'][0]['b'] == 0 and s1['items'][0]['km'] == 0.25


def test_a_flat_camera_across_the_road_is_right_or_left(rdoc):
    items = [mly(i, 250 + 10 * i, angle=90) for i in range(4)] + [mly(10 + i, 400 + 10 * i, angle=270, seq='s2') for i in range(4)]
    secs = SV.find_mapillary(rdoc, 't', frames_answer(items), lambda *_: None)
    assert sorted(json.dumps(s['angles']) for s in secs) == ['{"left": 4}', '{"right": 4}']


def pmx(i, north_m, seq='c1', az=0, size=(5760, 2880), fov=360, dt='2025-04-10T07:04:45+00:00'):
    return dict(id=f'p{i}', collection=seq, geometry=dict(coordinates=[LON0, LAT0 + north_m * M]), assets=dict(sd=dict(href=f'https://pmx.example/{i}/sd.jpg')),
                properties={'datetime': dt, 'view:azimuth': az, 'pers:interior_orientation': {'field_of_view': fov, 'sensor_array_dimensions': list(size), 'camera_manufacturer': 'GoPro', 'camera_model': 'Max'}})


def test_panoramax_sections_use_the_collection_and_the_picture_address(rdoc):
    feats = [pmx(i, 300 + 15 * i) for i in range(5)] + [pmx(10 + i, 300 + 15 * i, seq='c2', az=90, size=(1512, 2688), fov=70) for i in range(4)]
    secs = SV.find_panoramax(rdoc, lambda url, params: {'features': feats}, lambda *_: None)
    assert sorted((s['kind'], s['frames'], json.dumps(s['angles'])) for s in secs) == [('2d', 4, '{"right": 4}'), ('360', 5, 'null')]
    p = next(s for s in secs if s['kind'] == '360'); assert p['items'][0]['u'] == 'https://pmx.example/0/sd.jpg' and p['camera'] == 'GoPro Max' and p['years'] == [2025]


def test_google_sections_come_from_a_metadata_question_per_point(rdoc):
    def get(url, params):
        lat, lon = (float(x) for x in params['location'].split(',')); north = round((lat - LAT0) / M / 25) * 25                  # panoramas every 25 m
        if 400 <= north <= 600: return dict(status='OK', pano_id=f'g{north}', location=dict(lat=LAT0 + north * M, lng=lon), date='2019-06')
        return dict(status='ZERO_RESULTS')
    secs = SV.find_google(rdoc, 'k', get, lambda *_: None)
    assert [(s['provider'], s['kind'], s['stretch'], s['years']) for s in secs] == [('google', '360', 'R1', [2019])] and secs[0]['frames'] == 9 and secs[0]['km0'] == 0.4 and secs[0]['km1'] == 0.6


def test_google_refusal_is_an_error_with_the_reason(rdoc):
    with pytest.raises(RuntimeError, match='REQUEST_DENIED'): SV.find_google(rdoc, 'k', lambda u, p: dict(status='REQUEST_DENIED', error_message='API not activated'), lambda *_: None)


def test_run_makes_missing_stages_redoes_stale_ones_and_needs_the_keys(tmp_path, monkeypatch):
    rd = str(tmp_path); calls = []
    monkeypatch.setattr(SV, 'find_roads', lambda *a, **k: dict(schema=1, id='r1', stretches=[dict(id='R1', km0=0.2, km1=0.9, length_m=700, highways=[], names=[], line=[[1, 1], [1, 2]])], run=[], total_km=1))
    monkeypatch.setattr(SV, 'find_panoramax', lambda rdoc, get, log: calls.append('px') or [])
    monkeypatch.setattr(SV, 'find_mapillary', lambda rdoc, tok, get, log: calls.append('mly') or [])
    monkeypatch.setattr(SV, '_key', lambda n: None)
    with pytest.raises(RuntimeError, match='roads stage first'): SV.run(rd, {}, ['panoramax'])
    assert SV.run(rd, {}, ['roads', 'panoramax']) == ['roads', 'panoramax'] and SV.run(rd, {}, ['roads', 'panoramax']) == [] and calls == ['px']
    with pytest.raises(RuntimeError, match='MAPILLARY_TOKEN'): SV.run(rd, {}, ['mapillary'])
    with pytest.raises(RuntimeError, match='GOOGLE_MAPS_API_KEY'): SV.run(rd, {}, ['google'])
    with pytest.raises(ValueError, match='unknown'): SV.run(rd, {}, ['nope'])
    st = SV.status(rd); assert st['panoramax'] == dict(done=True, stale=False, sections=0, frames=0, km=0) and st['mapillary']['done'] is False and st['roads'] == dict(done=True, stretches=1, km=0.7)
    monkeypatch.setattr(SV, 'find_roads', lambda *a, **k: dict(schema=1, id='r2', stretches=[], run=[], total_km=1))
    assert SV.run(rd, {}, ['roads'], force=True) == ['roads'] and SV.status(rd)['panoramax']['stale'] is True
    assert SV.run(rd, {}, ['panoramax']) == ['panoramax'] and calls == ['px', 'px']


def sec_doc(item): return dict(sections=[dict(items=[item])])


def test_pictures_are_kept_for_mapillary_and_panoramax_but_never_for_google(tmp_path, monkeypatch):
    rd = str(tmp_path); fetched = []
    monkeypatch.setattr(SV, '_key', lambda n: 'KEY')
    fetch = lambda url, params=None: fetched.append((url, params)) or b'JPEG:' + url.encode()
    get = lambda url, params: {'thumb_1024_url': 'https://cdn/m1_1024.jpg'}
    doc = sec_doc(dict(id='m1', km=1, lat=1, lon=1, b=90))
    assert SV.image(rd, 'mapillary', doc, 'm1', 800, fetch, get) == b'JPEG:https://cdn/m1_1024.jpg' and SV.image(rd, 'mapillary', doc, 'm1', 800, fetch, get) and len(fetched) == 1
    assert (tmp_path / 'streetview' / 'img' / 'm-m1-1024.jpg').exists()
    pd = sec_doc(dict(id='p1', km=1, lat=1, lon=1, b=0, u='https://pmx/p1.jpg')); assert SV.image(rd, 'panoramax', pd, 'p1', 100, fetch, get) == b'JPEG:https://pmx/p1.jpg' and (tmp_path / 'streetview' / 'img' / 'p-p1-256.jpg').exists()
    gd = sec_doc(dict(id='g1', km=1, lat=1, lon=1, b=45))
    SV.image(rd, 'google', gd, 'g1', 640, fetch, get); SV.image(rd, 'google', gd, 'g1', 640, fetch, get)
    assert fetched[-1][1] == dict(size='640x400', pano='g1', heading=45, fov=90, pitch=0, key='KEY') and len(fetched) == 4 and not list((tmp_path / 'streetview' / 'img').glob('g-*'))
    with pytest.raises(KeyError): SV.image(rd, 'mapillary', doc, 'other', 640, fetch, get)
    with pytest.raises(RuntimeError, match='no picture address'): SV.image(rd, 'panoramax', sec_doc(dict(id='x', b=0)), 'x', 640, fetch, get)


class TestWeb:
    """The two ways the stages talk to a provider, with urlopen replaced."""
    def reply(self, monkeypatch, *answers):
        import io, urllib.error
        calls = []
        class R(io.BytesIO):
            def __init__(self, b, status): super().__init__(b); self.status = status
            def __enter__(self): return self
            def __exit__(self, *a): return False
        def urlopen(req, timeout=0):
            calls.append(req.full_url); a = answers[min(len(calls) - 1, len(answers) - 1)]
            if isinstance(a, int): raise urllib.error.HTTPError(req.full_url, a, 'x', {}, io.BytesIO(b'no'))
            if isinstance(a, Exception): raise a
            return R(a, 200)
        monkeypatch.setattr(SV.urllib.request, 'urlopen', urlopen); monkeypatch.setattr(SV.time, 'sleep', lambda s: None); return calls

    def test_get_sends_the_params_and_returns_the_json(self, monkeypatch):
        calls = self.reply(monkeypatch, b'{"a": 1}'); assert SV._get('https://x.example/api', dict(q='1 2', k='v')) == {'a': 1} and calls == ['https://x.example/api?q=1+2&k=v']

    def test_get_tries_again_after_a_failure_and_then_gives_up(self, monkeypatch):
        calls = self.reply(monkeypatch, 500, b'not json', OSError('down'), b'{"ok": true}'); assert SV._get('https://x.example/api', {}, tries=4) == {'ok': True} and len(calls) == 4
        self.reply(monkeypatch, 503)
        with pytest.raises(RuntimeError, match='x.example did not answer'): SV._get('https://x.example/api', {}, tries=2)

    def test_get_does_not_retry_a_refusal(self, monkeypatch):
        calls = self.reply(monkeypatch, 403)
        with pytest.raises(RuntimeError, match=r'refused the request \(403\): no'): SV._get('https://x.example/api', {}, tries=3)
        assert len(calls) == 1

    def test_bytes_returns_the_body_or_says_what_went_wrong(self, monkeypatch):
        self.reply(monkeypatch, b'jpeg'); assert SV._bytes('https://x.example/a.jpg') == b'jpeg'
        self.reply(monkeypatch, 404)
        with pytest.raises(RuntimeError, match='x.example answered 404'): SV._bytes('https://x.example/a.jpg')
        self.reply(monkeypatch, OSError('down'))
        with pytest.raises(RuntimeError, match='answered None'): SV._bytes('https://x.example/a.jpg')
