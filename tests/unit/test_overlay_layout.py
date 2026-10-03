"""overlay/layout.py and overlay/__init__.py: what the overlay shows and where, at any frame size, at the exact time of a frame; settings from race.json; the final film's cache key."""
import json, os
import numpy as np
import pytest
from overlay_fakes import T0, TileServer, race_track, tile_colour
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
        st = LY.settings(); assert st['elements'] == [e for e in LY.ELEMENTS if e != 'credit'] and 'credit' in LY.ELEMENTS and st['style'] is None and st['map_opacity'] == 0.6 and st['auto_zoom'] is True

    def test_unknown_element(self):
        with pytest.raises(ValueError, match='unknown overlay element.*speedo'): LY.settings({'elements': ['clock', 'speedo']})

    def test_unknown_layout_override(self):
        with pytest.raises(ValueError, match='typo'): LY.settings({'layout': {'typo': {'x': 1}}})


class TestShows:
    def test_the_values_at_the_frame_time(self, series, tiles, texts):
        overlay(series, tiles).patches(T0 + 300)                             # 900 m, 5:33 /km, 5 %, 345 m, 147 bpm; 08:05:00 in Brussels
        for s in ('2025/09/16  08:05:00', '0:05:00', 'DAY 1', '0.9', 'km', '5:33', 'min/km', '345', '5', '147', 'ALT (m)', 'SLOPE (%)', 'BPM'): assert s in texts
        assert '© OpenStreetMap contributors' not in texts                                    # no credit on the picture: it goes with the film's distribution

    def test_time_zone(self, series, tiles, texts):
        LY.Overlay(series, (1920, 1080), {'style': 'osm', 'elements': ['clock']}, tz='UTC', tiles=tiles).patches(T0 + 1.6); assert '2025/09/16  06:00:01' in texts and '0:00:01' in texts

    def test_outside_the_track_shows_dashes(self, series, tiles, texts):
        overlay(series, tiles, elements=['pace', 'heart_rate']).patches(T0 + 5000); assert '-:--' in texts and LY.DASH in texts

    def test_only_the_chosen_elements(self, series, tiles):
        ov = overlay(series, tiles, elements=['clock', 'heart_rate']); assert [type(w).__name__ for w in ov.widgets] == ['Clock', 'Stat'] and len(ov.patches(T0 + 10)) == 6

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
        hx, hy, _ = self.corner(ov, 'altitude'); assert (hx, hy) == pytest.approx((16 - D.icon('mountain', 64)[1], 850 - D.icon('mountain', 64)[1]))

    def test_scale_setting(self, series, tiles):
        assert self.corner(overlay(series, tiles, scale=1.5), 'local_map')[2][:2] == (384, 384)

    def test_layout_override(self, series, tiles):
        x, y, _ = self.corner(overlay(series, tiles, layout={'route_map': {'y': 100, 'size': 200}}), 'route_map'); assert y == 100 and self.corner(overlay(series, tiles, layout={'route_map': {'size': 200}}), 'route_map')[2][:2] == (200, 200)


class TestMaps:
    def test_route_map_is_built_once_and_the_marker_moves(self, series, tiles):
        ov = overlay(series, tiles, elements=['route_map']); a = ov.patches(T0); n = len(tiles.fetch.urls); b = ov.patches(T0 + 600)
        assert len(tiles.fetch.urls) == n and a[0][2] is b[0][2] and b[2][1] < a[2][1]                            # same base picture; running north moves the marker up

    def test_route_fills_the_route_map(self, series, tiles):
        ov = overlay(series, tiles, elements=['route_map']); y_start = ov.patches(T0)[2][1]; y_end = ov.patches(T0 + 899)[2][1]
        assert abs(y_start - y_end) == pytest.approx(256 * 0.86, abs=2)

    def test_the_part_already_run_is_a_darker_line_over_the_whole_route(self, series, tiles):
        ov = overlay(series, tiles, elements=['route_map']); first = ov.patches(T0 - 100)[1][2]; mid = ov.patches(T0 + 450)[1][2]; end = ov.patches(T0 + 899)[1][2]
        covered = lambda p: int((p[..., 3] > 0).sum())
        assert covered(first) == 0 and 0 < covered(mid) < covered(end) and tuple(mid[mid[..., 3] > 0][0][:3]) == LY.DONE_DARK                                   # nothing run yet; more run later
        base = ov.patches(T0)[0][2]; assert base[..., 3].max() > 0 and ov.patches(T0 + 450)[0][2] is base                                                        # the whole route (medium red) is in the base picture, drawn once

    def test_local_map_draws_the_run_part_stronger_than_the_part_to_come(self, series, tiles):
        ov = overlay(series, tiles, elements=['local_map']); pic = ov.patches(T0 + 450)[0][2]
        rgb = pic[..., :3].reshape(-1, 3).astype(int); strong = (np.abs(rgb - np.array(LY.RUN_COLOUR)).sum(1) < 30).sum(); pale = (np.abs(rgb - np.array(LY.TODO_COLOUR)).sum(1) < 30).sum()
        assert strong > 0 and pale > 0

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


class TestMapStyles:
    def factory(self, made, tmp_path):
        def make(style): made.append(style); return TL.Tiles(style, key='k', cache_dir=str(tmp_path / 't'), fetch=TileServer(512 if TL.STYLES[style]['retina'] else 256))
        return make

    def test_plain_overview_and_detailed_close_up(self, series, tmp_path, texts):
        made = []; ov = LY.Overlay(series, (1920, 1080), {'elements': list(LY.ELEMENTS)}, tiles=self.factory(made, tmp_path)); ov.patches(T0)                  # (the credit is only drawn when asked for: it is not in the default elements)
        assert made == ['tf-landscape', 'tf-outdoors'] and texts.count('Maps © Thunderforest, data © OpenStreetMap contributors') == 1

    def test_one_style_for_both(self, series, tmp_path):
        made = []; LY.Overlay(series, (1920, 1080), {'style': 'tf-atlas'}, tiles=self.factory(made, tmp_path)); assert made == ['tf-atlas']

    def test_per_map_style_and_one_credit_line_each(self, series, tmp_path, texts):
        made = []; ov = LY.Overlay(series, (1920, 1080), {'elements': list(LY.ELEMENTS), 'layout': {'route_map': {'style': 'osm'}}}, tiles=self.factory(made, tmp_path)); ov.patches(T0)
        assert made == ['osm', 'tf-outdoors'] and '© OpenStreetMap contributors' in texts and 'Maps © Thunderforest, data © OpenStreetMap contributors' in texts

    def test_missing_key_for_the_default_styles(self, series):
        with pytest.raises(TL.TileError, match='tf-landscape needs a key'): LY.Overlay(series, (1920, 1080), {})


class TestLocalMap:
    def test_centre_shows_the_tile_under_the_runner(self, series, tiles):
        ov = overlay(series, tiles, elements=['local_map'], auto_zoom=False, local_zoom=14.3, map_opacity=1.0); t = T0 + 300
        (X, Y, m), _ = ov.patches(t); wx, wy = TL.world(*series.position(t)); n = 2 ** 14; k = 2 ** 14.3; wx += 20 / k        # 20 px east of the runner, off the route line
        assert tuple(m[128, 148, :3]) == tile_colour(14, int(wx * n / 256), int(wy * n / 256))

    def test_pans_by_fractions_of_a_pixel(self, tiles):
        ov = overlay(Series(race_track(n=900, speed=0.5)), tiles, elements=['local_map'], auto_zoom=False)    # walking: well under a pixel a frame
        a = ov.patches(T0 + 300)[0][2].copy(); b = ov.patches(T0 + 300.04)[0][2]; assert not np.array_equal(a, b) and np.abs(a.astype(int) - b).max() < 60

    def test_reused_while_standing_still(self, tiles):
        tr = race_track(n=900); tr['lat'][400:500] = tr['lat'][400]; tr['dist'][400:500] = tr['dist'][400]
        ov = overlay(Series(tr), tiles, elements=['local_map']); a = ov.patches(T0 + 420)[0][2]; assert ov.patches(T0 + 470)[0][2] is a

    def test_follows_the_auto_zoom(self, series, tmp_path):
        tiles = TL.Tiles('osm', cache_dir=str(tmp_path / 'plain'), fetch=TileServer(colour=(220, 220, 210))); on = overlay(series, tiles, elements=['local_map']).widgets[0]; off = overlay(series, tiles, elements=['local_map'], auto_zoom=False).widgets[0]
        assert on.zoom_at(T0 + 450) == pytest.approx(13.1, abs=0.01) and off.zoom_at(T0 + 450) == 14 and off._zoom is None


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
        ov = for_project(p.folder, (1920, 1080), tiles=tiles); ov.patches(T0); assert '2025/09/16  06:00:00' in texts and ov.st['style'] == 'osm'


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
        sig = json.loads(LY.signature({'scale': 2}, None)); assert sig[0]['scale'] == 2 and sig[0]['local_zoom'] == 14 and sig[1] is None



class TestProfile:
    """The elevation profile of the whole race along the bottom, with the runner's place on it: the same on every shot."""
    def patches(self, series, tiles, t, size=(1920, 1080)):
        ov = overlay(series, tiles, size=size, elements=['profile']); return ov.widgets[0].patches(t, series.at(t)), ov.widgets[0]

    def test_it_is_a_default_element_drawn_first_so_the_numbers_sit_on_top_and_the_bottom_row_clears_it(self):
        assert list(LY.ELEMENTS)[0] == 'profile' and LY.ELEMENTS['profile']['height'] == 120 and LY.ELEMENTS['altitude']['y'] + 64 <= 1080 - 120 and LY.ELEMENTS['pace']['y'] + 56 + 16 <= 1080 - 120 and LY.ELEMENTS['heart_rate']['y'] + 52 <= 1080 - 120

    def test_the_part_run_is_light_the_part_to_come_dark_with_a_cursor_and_a_dot_at_the_runners_distance(self, series, tiles):
        out, w = self.patches(series, tiles, T0 + 450); done, todo, cur, dot = out; x = done[2].shape[1] - 1
        assert done[:2] == (0, 1080 - 120) and todo[0] == x + 1 and done[2].shape[0] == 120 and done[2].shape[1] + todo[2].shape[1] == 1920 and abs(x / 1919 - series.at(T0 + 450)['dist_m'] / w.d1) < 0.01
        assert done[2][..., 3].max() == 255 and done[2][..., :3].max() == 255 and todo[2][..., :3].max() == 255 and todo[2][..., 3].max() == 150 and cur[2][0, 0, 3] == 235                    # the done fill is light, the line bright; the to-come part dark
        assert abs(dot[0] + dot[2].shape[1] / 2 - cur[0] - cur[2].shape[1] / 2) < 1 and 1080 - 120 <= dot[1] <= 1080

    def test_the_cursor_moves_with_the_runner_and_is_clamped_to_the_ends(self, series, tiles):
        a, _ = self.patches(series, tiles, T0 + 100); b, _ = self.patches(series, tiles, T0 + 500); assert b[2][0] > a[2][0]
        end, _ = self.patches(series, tiles, T0 + 899); assert end[0][2].shape[1] >= 1900

    def test_before_the_track_starts_and_after_it_ends_the_profile_is_still_there_with_its_cursor_at_the_start_or_the_end(self, series, tiles):
        before, _ = self.patches(series, tiles, T0 - 3600); after, _ = self.patches(series, tiles, T0 + 86400)
        assert before and after and before[0][2].shape[1] <= 2 and after[0][2].shape[1] >= 1918                                  # the done part is empty at the start and the whole width at the end

    def test_without_altitude_or_distance_nothing_is_drawn_and_it_scales_with_the_frame(self, series, tiles):
        flat = Series(dict(race_track(n=600), alt=np.full(600, np.nan))); ov = overlay(flat, tiles, elements=['profile']); assert ov.widgets[0].patches(T0 + 100, flat.at(T0 + 100)) == []
        out, _ = self.patches(series, tiles, T0 + 300, size=(960, 540)); assert out[0][2].shape[0] == 60 and out[0][1] == 540 - 60 and out[0][2].shape[1] + out[1][2].shape[1] == 960


def test_no_credit_is_drawn_unless_it_is_asked_for(series, tiles, texts):
    ov = overlay(series, tiles); ov.patches(T0 + 300); assert not any('©' in t for t in texts) and not any(type(w).__name__ == 'Credit' for w in ov.widgets)                                           # credits go with the film's distribution
    ov = overlay(series, tiles, elements=['route_map', 'credit']); ov.patches(T0 + 300); assert any('OpenStreetMap' in t for t in texts)


class TestRaceDay:
    """Calendar days from the start, except that a first day shorter than an hour goes on into the next calendar day."""
    def at(self, y, mo, d, h, mi, tz='UTC'):
        import datetime as dt
        from zoneinfo import ZoneInfo
        return dt.datetime(y, mo, d, h, mi, tzinfo=ZoneInfo(tz)).timestamp()

    def test_a_start_in_the_afternoon_has_day_2_from_midnight(self):
        from zoneinfo import ZoneInfo
        z = ZoneInfo('Europe/Brussels'); st = self.at(2026, 2, 19, 16, 0, 'Europe/Brussels')
        assert [LY.race_day(st, self.at(2026, 2, d, h, m, 'Europe/Brussels'), z) for d, h, m in ((19, 16, 0), (19, 23, 59), (20, 0, 0), (20, 23, 59), (21, 0, 0))] == [1, 1, 2, 2, 3]
        assert LY.race_day(st, st - 3600, z) == 1                                                  # before the start

    def test_a_start_within_an_hour_of_midnight_keeps_day_1_through_the_next_day(self):
        from zoneinfo import ZoneInfo
        z = ZoneInfo('UTC'); st = self.at(2026, 2, 19, 23, 30)
        assert [LY.race_day(st, self.at(2026, 2, d, h, m), z) for d, h, m in ((19, 23, 45), (20, 0, 0), (20, 23, 59), (21, 0, 0), (21, 12, 0))] == [1, 1, 1, 2, 2]
        st = self.at(2026, 2, 19, 22, 59); assert LY.race_day(st, self.at(2026, 2, 20, 0, 0), z) == 2             # an hour or more before midnight: the day counts

    def test_elapsed_time_runs_past_24_hours(self):
        assert [LY.elapsed_text(x) for x in (-5, 0, 59, 3661, 26 * 3600 + 14 * 60 + 5, 130 * 3600)] == ['0:00:00', '0:00:00', '0:00:59', '1:01:01', '26:14:05', '130:00:00']


class TestStageText:
    def test_the_stage_follows_the_schedule_and_is_upper_case(self, series, tiles, texts):
        stages = [(float('-inf'), 'Before Race'), (T0 + 10, 'At Start'), (T0 + 100, 'Stage 1'), (T0 + 400, 'Checkpoint 1'), (T0 + 600, 'After Race')]
        ov = LY.Overlay(series, (1920, 1080), {'style': 'osm', 'elements': ['stage']}, tz='UTC', tiles=tiles, stages=stages)
        for dt_, want, n in ((-5, 'BEFORE RACE', 2), (10, 'AT START', 1), (99, 'AT START', 1), (100, 'STAGE 1', 2), (450, 'CHECKPOINT 1', 2), (900, 'AFTER RACE', 2)):
            texts.clear(); ov.c._text.clear(); assert len(ov.patches(T0 + dt_)) == n and want in texts                 # (drawn text is kept for reuse: cleared so the spy sees it)

    def test_nothing_is_drawn_without_a_schedule(self, series, tiles):
        assert LY.Overlay(series, (1920, 1080), {'style': 'osm', 'elements': ['stage']}, tz='UTC', tiles=tiles).patches(T0 + 5) == []

    def test_a_stage_shows_the_distance_and_time_so_far_over_its_whole_and_a_checkpoint_the_distance_from_the_start_and_the_time_there(self, series, tiles, texts):
        stages = [(float('-inf'), 'Before Race'), (T0, 'At Start'), (T0 + 100, 'Stage 1'), (T0 + 400, 'Checkpoint 1'), (T0 + 460, 'Stage 2'), (T0 + 800, 'After Race')]
        ov = LY.Overlay(series, (1920, 1080), {'style': 'osm', 'elements': ['stage']}, tz='UTC', tiles=tiles, stages=stages)       # the track runs 3 m/s
        ov.patches(T0 + 250); assert '0.5/0.9 km  ·  2m / 5m' in texts                                                          # 150 s of 300 s: 450 m of 900 m
        ov.patches(T0 + 430); assert '1.2 km  ·  0m / 1h' not in texts and any(x.startswith('1.2 km  ·  0m / 1m') for x in texts)   # at the checkpoint: 1200 m from the start; 30 s in of 60 s
        assert [LY._hm(x) for x in (0, 59, 60, 23 * 60, 3 * 3600 + 4 * 60, 7 * 3600 + 3 * 60)] == ['0m', '0m', '1m', '23m', '3h4m', '7h3m']

    def test_before_the_race_counts_down_to_the_start_and_after_it_counts_up_from_the_end(self, series, tiles, texts):
        stages = [(float('-inf'), 'Before Race'), (T0, 'At Start'), (T0 + 100, 'Stage 1'), (T0 + 800, 'After Race')]
        ov = LY.Overlay(series, (1920, 1080), {'style': 'osm', 'elements': ['stage']}, tz='UTC', tiles=tiles, stages=stages)
        for t, want in ((T0 - (4 * 3600 + 3 * 60), '-4h3m'), (T0 - 30, '0m'), (T0 + 800 + 34 * 3600 + 4 * 60, '+34h4m'), (T0 + 805, '0m')):
            texts.clear(); ov.c._text.clear(); ov.patches(t); assert want in texts, (t, texts)


class TestDistanceHolds:
    def test_before_the_run_it_is_zero_and_after_it_the_distance_reached(self, series, tiles, texts):
        ov = LY.Overlay(series, (1920, 1080), {'style': 'osm', 'elements': ['distance']}, tz='UTC', tiles=tiles)
        ov.patches(T0 - 100); assert '0.0' in texts
        texts.clear(); ov.c._text.clear(); ov.patches(T0 + 100000); assert any(x not in ('0.0', 'km', LY.DASH) for x in texts) and LY.DASH not in texts


class TestClimb:
    def test_running_totals_ignore_small_wiggles(self):
        from strata360.overlay.series import running_climb
        up, down = running_climb(np.array([100, 101, 99, 100, 110, 112, 105, np.nan, 105, 90.0]))
        assert list(up) == [0, 0, 0, 0, 10, 10, 10, 10, 10, 10] and list(down) == [0, 0, 0, 0, 0, 0, 5, 5, 5, 20]          # (the reference moves only on a change of 4 m or more: 105 is 5 m under 110, 90 is 15 m under 105)

    def test_the_line_shows_ascent_and_descent_so_far(self, series, tiles, texts):
        ov = LY.Overlay(series, (1920, 1080), {'style': 'osm', 'elements': ['climb']}, tz='UTC', tiles=tiles)
        ov.patches(T0 - 50); assert 'ASCENT 0 m   DESCENT 0 m' in texts
        texts.clear(); ov.c._text.clear(); ov.patches(T0 + 600); assert any(x.startswith('ASCENT ') and x != 'ASCENT 0 m   DESCENT 0 m' for x in texts)           # the track climbs 5 %


class TestArrow:
    def test_the_marker_on_the_route_map_points_the_way_the_route_goes_on(self, series, tiles):
        ov = overlay(series, tiles, elements=['route_map']); ov.patches(T0); w = ov.widgets[0]
        assert w._bearing(T0 + 300, *w._xy(T0 + 300)) in (0.0, 355.0, 5.0)                          # the test track runs due north: up the map
        end = w._bearing(T0 + 899, *w._xy(T0 + 899)); assert end in (0.0, 355.0, 5.0)                 # at the end it keeps its direction
