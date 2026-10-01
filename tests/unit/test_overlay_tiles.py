"""overlay/tiles.py: Web Mercator maths, fetching and caching tiles (a fake tile service, never the network), the key, and the map picture around a place."""
import os, urllib.error
import numpy as np
import pytest
from hypothesis import given, strategies as st
from overlay_fakes import TileServer, png, tile_colour
from strata360.edit import llm_remote as L
from strata360.overlay import tiles as T


@pytest.fixture(autouse=True)
def no_keys(tmp_path, monkeypatch):
    monkeypatch.setattr(L, 'VARS_FILE', str(tmp_path / 'secrets.env')); monkeypatch.delenv('THUNDERFOREST_API_KEY', raising=False)


def make(tmp_path, style='osm', size=None, **kw):
    srv = TileServer(size or (512 if T.STYLES[style]['retina'] else 256)); return T.Tiles(style, cache_dir=str(tmp_path / 'tiles'), fetch=srv, **kw), srv


class TestWorld:
    def test_origin_and_corners(self):
        assert T.world(0, 0) == pytest.approx((128, 128)) and T.world(0, -180)[0] == pytest.approx(0) and T.world(0, 180)[0] == pytest.approx(256)

    def test_poles_are_clamped(self):
        assert T.world(90, 0)[1] == pytest.approx(0, abs=1e-3) and T.world(-90, 0)[1] == pytest.approx(256, abs=1e-3)

    @given(st.floats(-80, 79), st.floats(0.01, 5))
    def test_north_is_up(self, lat, d):
        assert T.world(lat + d, 0)[1] < T.world(lat, 0)[1]


class TestTile:
    def test_fetched_once_then_read_from_the_cache(self, tmp_path):
        t, srv = make(tmp_path); a = np.asarray(t.tile(3, 2, 1)); b = np.asarray(t.tile(3, 2, 1))
        assert len(srv.urls) == 1 and t.fetched == 1 and tuple(a[0, 0]) == tile_colour(3, 2, 1) and (a == b).all()
        assert os.path.exists(tmp_path / 'tiles' / 'osm' / '3' / '2' / '1.png')

    def test_cache_is_shared_between_instances(self, tmp_path):
        make(tmp_path)[0].tile(4, 5, 6); t, srv = make(tmp_path); srv.fail = AssertionError('should not fetch'); assert tuple(np.asarray(t.tile(4, 5, 6))[3, 3]) == tile_colour(4, 5, 6)

    def test_url_of_a_keyed_retina_style(self, tmp_path):
        t, srv = make(tmp_path, 'tf-outdoors', key='KEY123'); t.tile(14, 8500, 5500)
        assert srv.urls == ['https://tile.thunderforest.com/outdoors/14/8500/5500@2x.png?apikey=KEY123'] and t.px == 512 and t.dir.endswith('tf-outdoors@2x')

    def test_x_wraps_round_the_world(self, tmp_path):
        t, srv = make(tmp_path); t.tile(2, 5, 1); assert srv.urls[0].endswith('/2/1/1.png')

    def test_rows_off_the_map_are_blank_and_not_fetched(self, tmp_path):
        t, srv = make(tmp_path); im = t.tile(2, 0, -1); assert srv.urls == [] and im.getpixel((0, 0)) == (200, 200, 200)

    def test_wrong_size_tile_is_resized(self, tmp_path):
        t, _ = make(tmp_path, size=100); assert t.tile(1, 0, 0).size == (256, 256)

    def test_offline_without_the_tile(self, tmp_path):
        t, _ = make(tmp_path, offline=True)
        with pytest.raises(T.TileError, match='not in the cache'): t.tile(1, 0, 0)

    def test_rejected_key_is_reported_without_the_key(self, tmp_path):
        t, srv = make(tmp_path, 'tf-outdoors', key='SECRETKEY'); srv.fail = urllib.error.HTTPError('u?apikey=SECRETKEY', 403, 'no', {}, None)
        with pytest.raises(T.TileError, match='HTTP 403.*map key') as e: t.tile(1, 0, 0)
        assert 'SECRETKEY' not in str(e.value)

    def test_unreachable_service(self, tmp_path):
        t, srv = make(tmp_path); srv.fail = urllib.error.URLError('no route')
        with pytest.raises(T.TileError, match='no route'): t.tile(1, 0, 0)

    def test_not_an_image(self, tmp_path):
        t, _ = make(tmp_path); t.fetch = lambda url: b'<html>quota</html>'
        with pytest.raises(T.TileError, match='not an image'): t.tile(1, 0, 0)
        assert not os.path.exists(tmp_path / 'tiles' / 'osm' / '1' / '0' / '0.png')


class TestKey:
    def test_missing_key_says_where_to_put_it(self, tmp_path):
        with pytest.raises(T.TileError, match='THUNDERFOREST_API_KEY=... in secrets.env'): T.Tiles('tf-outdoors', cache_dir=str(tmp_path))

    def test_key_from_the_environment(self, tmp_path, monkeypatch):
        monkeypatch.setenv('THUNDERFOREST_API_KEY', 'envkey'); assert T.Tiles('tf-outdoors', cache_dir=str(tmp_path)).key == 'envkey'

    def test_key_from_secrets_env(self, tmp_path):
        open(L.VARS_FILE, 'w').write('THUNDERFOREST_API_KEY=filekey\n'); assert T.Tiles('tf-landscape', cache_dir=str(tmp_path)).key == 'filekey'

    def test_offline_needs_no_key(self, tmp_path):
        assert T.Tiles('tf-outdoors', cache_dir=str(tmp_path), offline=True).key is None

    def test_style_without_a_key(self, tmp_path):
        assert not T.needs_key('osm') and T.needs_key('tf-outdoors') and T.Tiles('osm', cache_dir=str(tmp_path)).key is None

    def test_unknown_style(self):
        with pytest.raises(T.TileError, match='unknown map style'): T.Tiles('nope')


class TestPicture:
    def test_centred_on_a_tile_corner_shows_four_tiles(self, tmp_path):
        t, srv = make(tmp_path); k = 2.0 ** 3                                     # zoom 3 exactly: one picture pixel per tile pixel
        im = np.asarray(t.picture(3 * 32, 2 * 32, k, 64, 64))                    # the corner shared by tiles (2,1), (3,1), (2,2), (3,2)
        assert im.shape == (64, 64, 3) and tuple(im[10, 10]) == tile_colour(3, 2, 1) and tuple(im[10, 54]) == tile_colour(3, 3, 1)
        assert tuple(im[54, 10]) == tile_colour(3, 2, 2) and tuple(im[54, 54]) == tile_colour(3, 3, 2) and len(srv.urls) == 4

    def test_picks_the_zoom_with_enough_detail(self, tmp_path):
        t, srv = make(tmp_path, 'tf-outdoors', key='k'); t.picture(*T.world(50.13, 5.79), 2.0 ** 15, 32, 32)
        assert all('/14/' in u for u in srv.urls)                                # 512-pixel tiles at zoom 14 give scale 2**15

    def test_between_zooms_uses_the_finer_one(self, tmp_path):
        t, srv = make(tmp_path); t.picture(128, 128, 2.0 ** 5.3, 16, 16); assert all('/6/' in u for u in srv.urls)

    def test_zoom_is_capped(self, tmp_path):
        t, srv = make(tmp_path); t.picture(128, 128, 2.0 ** 25, 8, 8); assert all(f'/{T.MAX_ZOOM}/' in u for u in srv.urls)


def test_default_fetch_sends_a_user_agent(fake_urlopen):
    fake_urlopen.reply(png((1, 2, 3))); assert T._get('https://tile.example/1/0/0.png') == png((1, 2, 3)) and 'strata360' in fake_urlopen.calls[0]['headers']['user-agent']


def test_secret_reads_environment_then_file(monkeypatch):
    open(L.VARS_FILE, 'w').write('X_KEY="fromfile"\n'); assert L.secret('X_KEY') == 'fromfile'
    monkeypatch.setenv('X_KEY', ' fromenv '); assert L.secret('X_KEY') == 'fromenv' and L.secret('NOT_SET') is None
