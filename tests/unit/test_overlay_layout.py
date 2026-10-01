"""overlay/layout.py and overlay/__init__.py: what the overlay shows and where, at any frame size, at the exact time of a frame; settings from race.json; the final film's cache key."""
import json, os
import numpy as np
import pytest
from overlay_fakes import T0, TileServer, race_track
from strata360.edit import llm_remote as L
from strata360.overlay import draw as D, for_project, layout as LY, tiles as TL
from strata360.overlay.series import Series


@pytest.fixture(autouse=True)
def no_keys(tmp_path, monkeypatch):
    monkeypatch.setattr(L, 'VARS_FILE', str(tmp_path / 'secrets.env')); monkeypatch.delenv('THUNDERFOREST_API_KEY', raising=False)


@pytest.fixture
def tiles(tmp_path): return TL.Tiles('osm', cache_dir=str(tmp_path / 'tiles'), fetch=TileServer())


@pytest.fixture
def series(): return Series(race_track(n=900, speed=3.0, grade=0.05, hr=147.0))


@pytest.fixture
def texts(monkeypatch):
    """Every string the overlay draws, in order."""
    seen = []; real = D.text
    def spy(s, *a, **kw): seen.append(s); return real(s, *a, **kw)
    monkeypatch.setattr(D, 'text', spy); return seen


def overlay(series, tiles, size=(1920, 1080), **st): return LY.Overlay(series, size, {'style': 'osm', **st}, tiles=tiles)


@pytest.mark.parametrize('metric, v, s', [('dist', 12345.0, '12.3'), ('dist', 0.0, '0.0'), ('pace', 342.4, '5:42'), ('pace', 599.6, '10:00'), ('pace', float('nan'), '-:--'),
                                          ('alt', 1234.6, '1235'), ('slope', -0.4, '0'), ('slope', -3.2, '-3'), ('hr', 147.0, '147'), ('hr', float('nan'), LY.DASH), ('hr', None, LY.DASH)])
def test_fmt(metric, v, s): assert LY.fmt(metric, v) == s


class TestSettings:
    def test_defaults(self):
        st = LY.settings(); assert st['elements'] == list(LY.ELEMENTS) and st['style'] == 'tf-outdoors' and st['map_opacity'] == 0.6

    def test_unknown_element(self):
        with pytest.raises(ValueError, match='unknown overlay element.*speedo'): LY.settings({'elements': ['clock', 'speedo']})

    def test_unknown_layout_override(self):
        with pytest.raises(ValueError, match='typo'): LY.settings({'layout': {'typo': {'x': 1}}})


class TestShows:
    def test_the_values_at_the_frame_time(self, series, tiles, texts):
        overlay(series, tiles).patches(T0 + 300)                             # 900 m, 5:33 /km, 5 %, 345 m, 147 bpm; 08:05:00 in Brussels
        for s in ('2025/09/16', '08:05:00', '0.9', 'km', '5:33', 'min/km', '345', '5', '147', 'ALT (m)', 'SLOPE (%)', 'BPM', '© OpenStreetMap contributors'): assert s in texts

    def test_time_zone(self, series, tiles, texts):
        LY.Overlay(series, (1920, 1080), {'style': 'osm', 'elements': ['clock']}, tz='UTC', tiles=tiles).patches(T0 + 1.6); assert '06:00:01' in texts

    def test_outside_the_track_shows_dashes(self, series, tiles, texts):
        overlay(series, tiles, elements=['pace', 'heart_rate']).patches(T0 + 5000); assert '-:--' in texts and LY.DASH in texts

    def test_only_the_chosen_elements(self, series, tiles):
        ov = overlay(series, tiles, elements=['clock', 'heart_rate']); assert [type(w).__name__ for w in ov.widgets] == ['Clock', 'Stat'] and len(ov.patches(T0 + 10)) == 5

    def test_downhill_icon(self, tiles, texts, monkeypatch):
        names = []; real = D.icon; monkeypatch.setattr(D, 'icon', lambda n, px: names.append(n) or real(n, px))
        overlay(Series(race_track(grade=-0.05)), tiles, elements=['slope']).patches(T0 + 300); assert names == ['slope_down'] and '-5' in texts

    def test_text_is_drawn_once_per_value(self, series, tiles, texts):
        ov = overlay(series, tiles, elements=['distance']); ov.patches(T0 + 300); n = len(texts); ov.patches(T0 + 300.01); assert len(texts) == n


class TestPlacement:
    def corner(self, ov, name, t=T0 + 100):
        w = ov.widgets[ov.st['elements'].index(name)]; x, y, p = w.patches(t, ov.c.series.at(t))[0]; return x, y, p.shape

    def test_4k_is_drawn_at_twice_the_size_not_enlarged(self, series, tiles):
        a = self.corner(overlay(series, tiles), 'route_map'); b = self.corner(overlay(series, tiles, size=(3840, 2160)), 'route_map')
        assert (b[0], b[1]) == pytest.approx((2 * a[0], 2 * a[1])) and b[2][:2] == (512, 512) and a[2][:2] == (256, 256)

    def test_anchored_to_the_right_and_bottom_edges(self, series, tiles):
        ov = overlay(series, tiles, size=(2160, 1080)); x, y, _ = self.corner(ov, 'route_map'); assert (x, y) == pytest.approx((2160 - 276, 24))
        hx, hy, _ = self.corner(ov, 'altitude'); assert (hx, hy) == pytest.approx((16 - D.icon('mountain', 64)[1], 980 - D.icon('mountain', 64)[1]))

    def test_scale_setting(self, series, tiles):
        assert self.corner(overlay(series, tiles, scale=1.5), 'local_map')[2][:2] == (384, 384)

    def test_layout_override(self, series, tiles):
        x, y, _ = self.corner(overlay(series, tiles, layout={'route_map': {'y': 100, 'size': 200}}), 'route_map'); assert y == 100 and self.corner(overlay(series, tiles, layout={'route_map': {'size': 200}}), 'route_map')[2][:2] == (200, 200)


class TestMaps:
    def test_route_map_is_built_once_and_the_marker_moves(self, series, tiles):
        ov = overlay(series, tiles, elements=['route_map']); a = ov.patches(T0); n = len(tiles.fetch.urls); b = ov.patches(T0 + 600)
        assert len(tiles.fetch.urls) == n and a[0][2] is b[0][2] and b[1][1] < a[1][1]                            # same base picture; running north moves the marker up

    def test_route_fills_the_route_map(self, series, tiles):
        ov = overlay(series, tiles, elements=['route_map']); y_start = ov.patches(T0)[1][1]; y_end = ov.patches(T0 + 899)[1][1]
        assert abs(y_start - y_end) == pytest.approx(256 * 0.86, abs=2)

    def test_local_map_keeps_the_marker_in_the_middle(self, series, tiles):
        ov = overlay(series, tiles, elements=['local_map'])
        for t in (T0, T0 + 450):
            (X, Y, m), (mx, my, dot) = ov.patches(t); assert (mx + dot.shape[1] / 2, my + dot.shape[0] / 2) == pytest.approx((X + 128, Y + 128))

    def test_local_map_reuses_its_backing_while_close(self, series, tiles):
        ov = overlay(series, tiles, elements=['local_map']); w = ov.widgets[0]
        for i in range(20): ov.patches(T0 + i)
        assert len(w.backs) == 1

    def test_dissolve_between_two_places_does_not_rebuild(self, tiles):
        ov = overlay(Series(race_track(n=4000, speed=5.0)), tiles, elements=['local_map']); w = ov.widgets[0]
        for i in range(10): ov.patches(T0 + 100 + i * 0.02); ov.patches(T0 + 3900 + i * 0.02)
        assert len(w.backs) == 2

    def test_missing_map_key_is_reported_at_once(self, series):
        with pytest.raises(TL.TileError, match='needs a key'): LY.Overlay(series, (1920, 1080), {'style': 'tf-outdoors'})

    def test_no_map_elements_need_no_key(self, series):
        LY.Overlay(series, (1920, 1080), {'style': 'tf-outdoors', 'elements': ['clock', 'pace']}).patches(T0)


class TestDrawing:
    def test_apply_changes_only_where_the_overlay_is(self, series, tiles):
        f = np.full((1080, 1920, 3), 20000, np.uint16); out = overlay(series, tiles).apply(f, T0 + 100)
        assert out is f and (f[540, 960] == 20000).all() and (f[150, 1770] != 20000).any() and f.dtype == np.uint16

    def test_read_only_frame_is_copied(self, series, tiles):
        f = np.zeros((1080, 1920, 3), np.uint8); f.flags.writeable = False; out = overlay(series, tiles, elements=['clock']).apply(f, T0)
        assert out is not f and out.max() > 0 and f.max() == 0

    def test_still_is_the_overlay_alone(self, series, tiles):
        s = overlay(series, tiles).still(T0 + 100)
        assert s.shape == (1080, 1920, 4) and s[540, 960, 3] == 0 and s[150, 1770, 3] == 153 and s.dtype == np.uint8

    def test_still_cuts_patches_at_the_frame_edge(self, series, tiles):
        s = overlay(series, tiles, elements=['clock'], layout={'clock': {'x': -500}}).still(T0); assert s[..., 3].max() == 0


class TestProject:
    def test_none_without_a_track(self, make_project):
        p = make_project(config=True); assert for_project(p.folder, (1920, 1080)) is None

    def test_none_when_turned_off(self, make_project, monkeypatch):
        p = make_project(config={'overlay': {'enabled': False}}); open(p.path('track.fit'), 'wb').close(); assert for_project(p.folder, (1920, 1080)) is None

    def test_built_from_the_project_track_and_settings(self, make_project, monkeypatch, tiles, texts):
        from strata360.gps import track as TR
        p = make_project(config={'timezone': 'UTC', 'overlay': {'style': 'osm', 'elements': ['clock']}}); open(p.path('track.fit'), 'wb').close()
        monkeypatch.setattr(TR, 'load', lambda path: race_track())
        ov = for_project(p.folder, (1920, 1080), tiles=tiles); ov.patches(T0); assert '06:00:00' in texts and ov.st['style'] == 'osm'


class TestFinalKey:
    def key(self, p):
        from strata360.render.final import final_key
        return final_key({'segments': [{'id': 'w1'}]}, [1920, 1080], 50.0, '100M', p.folder)

    def test_unchanged_without_a_track(self, make_project):
        p = make_project(config=True); k = self.key(p); p.write_json('race.json', {'overlay': {'scale': 2}}); assert self.key(p) == k

    def test_follows_the_overlay_settings_and_track(self, make_project):
        p = make_project(config=True); k0 = self.key(p); open(p.path('track.fit'), 'wb').close(); k1 = self.key(p)
        p.write_json('race.json', {'overlay': {'scale': 1.2}}); k2 = self.key(p); os.utime(p.path('track.fit'), (1, 1)); k3 = self.key(p)
        p.write_json('race.json', {'overlay': {'enabled': False}}); assert len({k0, k1, k2, k3}) == 4 and self.key(p) == k0

    def test_signature_holds_the_merged_settings(self):
        sig = json.loads(LY.signature({'scale': 2}, None)); assert sig[0]['scale'] == 2 and sig[0]['style'] == 'tf-outdoors' and sig[1] is None
