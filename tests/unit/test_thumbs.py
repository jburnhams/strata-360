"""analysis/thumbs.py (the overlay thumbnail; choosing the moment needs video and is covered by the integration suite) and the `thumb_overlay` stage's wiring."""
import datetime as dt, json, os
import numpy as np
import pytest
from PIL import Image
from overlay_fakes import T0, TileServer, race_track
from projects import CLIP_ID
from strata360.analysis import thumbs as TH
from strata360.edit import llm_remote as L
from strata360.gps import track as TR
from strata360.overlay import tiles as TL
from strata360.pipeline import config, stages as ST


@pytest.fixture
def clip(make_project, monkeypatch, tmp_path):
    """A clip starting at T0 with a 960x540 grey thumbnail at 100 s, a track file whose contents are race_track(), and no map key."""
    monkeypatch.setattr(L, 'VARS_FILE', str(tmp_path / 'secrets.env')); monkeypatch.delenv('THUNDERFOREST_API_KEY', raising=False)
    p = make_project(config=True); d = p.add_clip(CLIP_ID, start_utc=dt.datetime.fromtimestamp(T0, dt.timezone.utc).isoformat())
    Image.new('RGB', (960, 540), (90, 90, 90)).save(os.path.join(d, 'thumb.jpg')); json.dump(dict(kind='best', t_s=100.0), open(os.path.join(d, 'thumb.json'), 'w'))
    track = p.path('track.fit'); open(track, 'wb').close(); monkeypatch.setattr(TR, 'load', lambda path: race_track(n=900)); return p, d, track


def tiles(tmp_path): return TL.Tiles('osm', cache_dir=str(tmp_path / 'tiles'), fetch=TileServer())


def test_overlay_drawn_at_the_thumbnail_moment(clip, tmp_path):
    p, d, track = clip; out = TH.with_overlay(d, {'overlay': {'style': 'osm'}, 'timezone': 'UTC'}, track, tiles(tmp_path))
    im = np.asarray(Image.open(os.path.join(d, 'thumb_overlay.jpg')))
    assert im.shape == (540, 960, 3) and out == dict(source='thumb.jpg', source_mtime=os.path.getmtime(os.path.join(d, 'thumb.jpg')), t_s=100.0, utc='2025-09-16T06:01:40+00:00', maps=True, why=None)
    assert np.abs(im[150:280, 820:950].astype(int) - 90).mean() > 20 and np.abs(im[270, 480].astype(int) - 90).max() < 6       # a map top right; the middle untouched
    assert TH.overlay_fresh(d) and json.load(open(os.path.join(d, 'thumb_overlay.json')))['maps'] is True


def test_without_a_map_key_it_fails_loudly_and_writes_nothing(clip):
    from strata360.overlay.tiles import MissingKey
    p, d, track = clip
    with pytest.raises(MissingKey, match='THUNDERFOREST_API_KEY'): TH.with_overlay(d, {}, track)
    assert not os.path.exists(os.path.join(d, 'thumb_overlay.jpg')) and not os.path.exists(os.path.join(d, 'thumb_overlay.json'))


def test_uses_the_quick_thumbnail_when_there_is_no_best(clip, tmp_path):
    p, d, track = clip; os.rename(os.path.join(d, 'thumb.jpg'), os.path.join(d, 'thumb_quick.jpg')); os.remove(os.path.join(d, 'thumb.json'))
    json.dump(dict(kind='quick', t_s=5.0), open(os.path.join(d, 'thumb_quick.json'), 'w'))
    assert TH.with_overlay(d, {'overlay': {'style': 'osm'}}, track, tiles(tmp_path))['source'] == 'thumb_quick.jpg' and TH.current(d)[0] == 'thumb_quick.jpg'


def test_no_thumbnail(clip):
    p, d, track = clip; os.remove(os.path.join(d, 'thumb.jpg'))
    with pytest.raises(RuntimeError, match='no thumbnail'): TH.with_overlay(d, {}, track)
    assert TH.current(d) == (None, None) and not TH.overlay_fresh(d)


def test_stale_when_the_thumbnail_changes_and_dropped_when_a_new_one_is_made(clip, tmp_path):
    p, d, track = clip; TH.with_overlay(d, {'overlay': {'style': 'osm'}}, track, tiles(tmp_path)); os.utime(os.path.join(d, 'thumb.jpg'), (5, 5)); assert not TH.overlay_fresh(d)
    TH._drop_overlay(d); assert not os.path.exists(os.path.join(d, 'thumb_overlay.jpg')) and not os.path.exists(os.path.join(d, 'thumb_overlay.json')); TH._drop_overlay(d)


class TestStage:
    def test_wiring(self):
        s = ST.STAGES['thumb_overlay']
        assert s.deps == ('thumb',) and s.soft_deps == ('thumb_best',) and s.needs_track and set(s.keys) == {'overlay', 'timezone'} and s.outputs == ('thumb_overlay.jpg',)
        assert ST.ORDER.index('thumb_overlay') > ST.ORDER.index('thumb_best') and config.DEFAULTS['stages'][-1] == 'thumb_overlay'

    def test_older_projects_get_the_stage(self, make_project):
        p = make_project(config={'stages': ['ingest', 'transcribe', 'thumb_best', 'scenes']}); st = config.load(p.folder)['stages']; assert st[st.index('thumb_best') + 1] == 'thumb_overlay' and st[-1] == 'scenes'

    def test_runs_with_the_project_track(self, clip, tmp_path, monkeypatch):
        p, d, track = clip; seen = {}
        monkeypatch.setattr(TH, 'with_overlay', lambda dd, cfg, tp: seen.update(d=dd, tp=tp))
        ST.thumb_overlay(ST.Ctx(None, {}, d, print)); assert seen == dict(d=d, tp=track)

    def test_without_a_track(self, make_project):
        p = make_project(config=True); d = p.add_clip(CLIP_ID)
        with pytest.raises(RuntimeError, match='no race track'): ST.thumb_overlay(ST.Ctx(None, {}, d, print))

def test_corner_stretch():
    import math
    from strata360.analysis.thumbs import corner_stretch, ASPECT

    # Check mathematically
    hfov = 100.0
    t = math.tan(math.radians(hfov) / 2) * math.sqrt(1 + (1 / ASPECT) ** 2)
    expected = 1 + t * t
    assert corner_stretch(hfov) == expected

def test_fov_for_person():
    from strata360.analysis.thumbs import fov_for_person, MIN_HFOV, MAX_HFOV

    hfov, why = fov_for_person(40.0)
    assert MIN_HFOV <= hfov <= MAX_HFOV
    assert "body 40 deg tall:" in why
    assert "deg across so the whole body fits with margin" in why

    hfov, why = fov_for_person(100.0)
    assert hfov == MAX_HFOV
    assert why == "body 100 deg tall would need 142 deg across: capped at 105 to limit distortion (some of the body is cropped)"


def test_thumb_helper(monkeypatch):
    from strata360.analysis import thumbs as TH
    from strata360.analysis import views as V

    called_proxy = []
    called_render = []

    def fake_render_thumb_proxy(proxy, osv, t, yaw, pitch, hfov):
        called_proxy.append((proxy, osv, t, yaw, pitch, hfov))
        return b'proxy'

    def fake_render_thumb(osv, t, yaw, pitch, hfov):
        called_render.append((osv, t, yaw, pitch, hfov))
        return b'render'

    monkeypatch.setattr(V, 'render_thumb_proxy', fake_render_thumb_proxy)
    monkeypatch.setattr(V, 'render_thumb', fake_render_thumb)

    # Test proxy available
    monkeypatch.setattr(V, 'proxy_available', lambda proxy: True)
    res = TH._thumb('osv', 'd', 1.0, 0.0, 0.0, 100.0)
    assert res == b'proxy'
    assert len(called_proxy) == 1
    assert called_proxy[0] == (os.path.join('d', 'proxy.mp4'), 'osv', 1.0, 0.0, 0.0, 100.0)
    assert len(called_render) == 0

    called_proxy.clear()

    # Test proxy not available
    monkeypatch.setattr(V, 'proxy_available', lambda proxy: False)
    res = TH._thumb('osv', 'd', 1.0, 0.0, 0.0, 100.0)
    assert res == b'render'
    assert len(called_proxy) == 0
    assert len(called_render) == 1
    assert called_render[0] == ('osv', 1.0, 0.0, 0.0, 100.0)


def test_quick_no_motion(monkeypatch, make_project):
    from strata360.analysis import thumbs as TH
    monkeypatch.setattr(TH, '_thumb', lambda osv, d, t, yaw, pitch, hfov: b'jpeg')

    p = make_project()
    d = p.add_clip('clip1')
    json.dump({'video': {'source_frames': 1000, 'nominal_fps': 10}}, open(os.path.join(d, 'clip.json'), 'w'))

    info = TH.quick('osv', d)

    assert info['kind'] == 'quick'
    assert info['t_s'] == 50.0
    assert info['yaw'] == 0.0
    assert info['fov'] == 100.0
    assert info['why'] == 'steadiest moment near the middle, looking ahead, wide view'

    assert os.path.exists(os.path.join(d, 'thumb_quick.jpg'))
    assert os.path.exists(os.path.join(d, 'thumb_quick.json'))

def test_quick_with_motion(monkeypatch, make_project):
    from strata360.analysis import thumbs as TH
    monkeypatch.setattr(TH, '_thumb', lambda osv, d, t, yaw, pitch, hfov: b'jpeg')

    p = make_project()
    d = p.add_clip('clip1')
    json.dump({'video': {'source_frames': 1000, 'nominal_fps': 10}}, open(os.path.join(d, 'clip.json'), 'w'))

    # 10s is outside 0.1-0.9 window (10s to 90s, so > 10.0 is needed)
    # wait, 0.1*100 = 10.0, so > 10.0 and < 90.0
    # Let's use 20.0, 50.0, 80.0
    # Score for 20: steady=exp(-0/25)=1.0, score = 1.0 - 0.6*(abs(20-50))/100 = 1.0 - 0.6*30/100 = 1.0 - 0.18 = 0.82
    # Score for 50: steady=exp(-50/25)=exp(-2)=0.135, score = 0.135 - 0.6*0 = 0.135
    # So 20 should be chosen.
    json.dump({'series': {'t': [20.0, 50.0, 80.0], 'shake_dps': [0.0, 50.0, 0.0]}}, open(os.path.join(d, 'motion.json'), 'w'))

    info = TH.quick('osv', d)

    assert info['kind'] == 'quick'
    assert info['t_s'] == 20.0


def test_best_no_candidates(monkeypatch, make_project):
    from strata360.analysis import thumbs as TH
    monkeypatch.setattr(TH, '_thumb', lambda osv, d, t, yaw, pitch, hfov: b'jpeg')

    p = make_project()
    d = p.add_clip('clip1')
    json.dump({'video': {'source_frames': 1000, 'nominal_fps': 10}}, open(os.path.join(d, 'clip.json'), 'w'))

    # Empty candidates
    json.dump({'candidates': []}, open(os.path.join(d, 'candidates.json'), 'w'))
    info = TH.best('osv', d)
    assert info['kind'] == 'quick'

    # Missing candidates
    os.remove(os.path.join(d, 'candidates.json'))
    info2 = TH.best('osv', d)
    assert info2['kind'] == 'quick'


def test_best_with_candidates_no_faces(monkeypatch, make_project):
    from strata360.analysis import thumbs as TH
    monkeypatch.setattr(TH, '_thumb', lambda osv, d, t, yaw, pitch, hfov: b'jpeg')

    p = make_project()
    d = p.add_clip('clip1')

    # Two candidates
    cand1 = {'id': 'c1', 'quality': 0.5, 'features': {'subject': 1}, 'start_s': 10.0, 'end_s': 15.0}
    # Interest for cand1 = 0.5*0.5 + 0.25*1 = 0.25 + 0.25 = 0.5

    cand2 = {'id': 'c2', 'quality': 0.9, 'features': {'subject': 0}, 'start_s': 20.0, 'end_s': 25.0}
    # Interest for cand2 = 0.5*0.9 + 0 = 0.45

    # Cand1 should be chosen because 0.5 > 0.45. Range is 10.0 to 15.0.
    # ts will be [10.5, 11.0, 11.5, 12.0, 12.5, 13.0, 13.5, 14.0, 14.5]

    json.dump({'candidates': [cand1, cand2]}, open(os.path.join(d, 'candidates.json'), 'w'))

    # Motion
    json.dump({'series': {'t': [10.5, 11.0], 'shake_dps': [50.0, 0.0]}}, open(os.path.join(d, 'motion.json'), 'w'))
    # Scenes
    json.dump({'items': [{'ok': True, 'view': 'front', 't_s': 11.0, 'scenic': 0.9}]}, open(os.path.join(d, 'scenes.json'), 'w'))

    # 11.0 should get the highest score since shake_dps is 0 (steady) and scenic is 0.9
    info = TH.best('osv', d)

    assert info['kind'] == 'best'
    assert info['candidate'] == 'c1'
    assert info['t_s'] == 11.0
    assert info['yaw'] == 0.0
    assert info['pitch'] == 0.0
    assert info['fov'] == 100.0 # AHEAD_HFOV
    assert 'most attractive second, looking ahead, wide view' in info['why']

    assert os.path.exists(os.path.join(d, 'thumb.jpg'))
    assert os.path.exists(os.path.join(d, 'thumb.json'))

def test_best_with_candidates_and_faces(monkeypatch, make_project):
    from strata360.analysis import thumbs as TH
    monkeypatch.setattr(TH, '_thumb', lambda osv, d, t, yaw, pitch, hfov: b'jpeg')

    p = make_project()
    d = p.add_clip('clip1')

    cand1 = {'id': 'c1', 'quality': 0.9, 'features': {}, 'start_s': 10.0, 'end_s': 15.0}
    json.dump({'candidates': [cand1]}, open(os.path.join(d, 'candidates.json'), 'w'))

    # Face at 12.5
    json.dump({'samples': [
        {'t_s': 12.5, 'me': {'how': 'face', 'yaw': 10.0, 'pitch': -5.0, 'sim': 0.9, 'height_deg': 40.0}}
    ]}, open(os.path.join(d, 'identity.json'), 'w'))

    # Score for face = 0.6 + 0.3*0.9 = 0.87. Since motion/scenes are missing, this should dominate.
    info = TH.best('osv', d)

    assert info['kind'] == 'best'
    assert info['candidate'] == 'c1'
    assert info['t_s'] == 12.5
    assert info['yaw'] == 10.0
    assert info['pitch'] == -5.0
    assert info['fov'] < 100.0 # Should be narrowed for face, e.g. based on 40.0 deg height
    assert 'face recognised' in info['why']
