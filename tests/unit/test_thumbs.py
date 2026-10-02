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
