"""overlay/gapoverlay.py: the film's overlay for a generated gap clip: the same elements, the bottom row lifted above an elevation profile with a cursor, and a caption saying what is shown."""
import numpy as np
import pytest
from overlay_fakes import T0, TileServer, race_track
from strata360.edit import llm_remote as L
from strata360.overlay import gapoverlay as GO, layout as LY, tiles as TL
from strata360.overlay.series import Series

INFO = dict(local_start='Fri 20 Feb 06:12', local_end='Fri 20 Feb 07:29', km_start=69.1, km_end=75.3, ascent_m=121)


@pytest.fixture(autouse=True)
def no_keys(tmp_path, monkeypatch):
    monkeypatch.setattr(L, 'VARS_FILE', str(tmp_path / 'secrets.env')); monkeypatch.delenv('THUNDERFOREST_API_KEY', raising=False)


@pytest.fixture
def series(): return Series(race_track(n=3600, speed=3.0, grade=0.05))


@pytest.fixture
def tiles(tmp_path): return TL.Tiles('osm', cache_dir=str(tmp_path / 'tiles'), fetch=TileServer(colour=(90, 120, 90)))


def test_the_caption_says_when_where_and_how_much_and_that_it_was_not_filmed():
    assert GO.caption(INFO) == 'Fri 20 Feb 06:12 → Fri 20 Feb 07:29  ·  km 69.1–75.3  ·  +121 m  ·  not filmed' and GO.caption({}) == 'not filmed' and GO.caption(dict(km_start=0.0, km_end=2.5)) == 'km 0–2.5  ·  not filmed'


def test_the_film_overlay_is_all_there_with_the_bottom_row_lifted_clear_of_the_profile():
    assert {'clock', 'distance', 'pace', 'altitude', 'slope', 'heart_rate', 'route_map', 'credit'} == set(GO.ELEMENTS) and 'local_map' not in GO.ELEMENTS
    for k in ('pace', 'altitude', 'slope', 'heart_rate'): assert GO.LAYOUT[k]['y'] == LY.ELEMENTS[k]['y'] - GO.LIFT                                                       # the same places, raised by the profile's height
    assert GO.LIFT >= GO.PROFILE_H * LY.REF_H


def test_the_profile_follows_the_altitude_of_the_stretch(series):
    strip, (x, y) = GO.profile_strip(series, T0 + 300, T0 + 3300, 640, 360, 1 / 3); assert strip.shape == (int(round(360 * GO.PROFILE_H)), 640, 4) and x[0] == 0 and x[-1] == pytest.approx(639) and y[-1] < y[0]       # a climb: the line rises (smaller y)
    assert GO.profile_strip(Series(dict(race_track(n=100), alt=np.full(100, np.nan))), T0, T0 + 90, 640, 360, 1 / 3) == (None, None)


def test_a_frame_has_the_strip_the_cursor_the_caption_and_the_overlay_and_the_cursor_moves(series, tiles):
    ov = GO.GapOverlay(series, (960, 540), T0 + 300, T0 + 3300, 'UTC', tiles, info=INFO, credit=['Imagery: someone'])
    a = ov.apply(np.full((540, 960, 3), 120, np.uint8), T0 + 600); b = ov.apply(np.full((540, 960, 3), 120, np.uint8), T0 + 2700)
    bottom = slice(540 - ov.h, 540); assert (a[bottom] != 120).any() and (a[:80] != 120).any()                                                          # the strip, and the clock and caption at the top
    col = lambda im: np.flatnonzero((im[bottom] >= 235).all(axis=2).sum(axis=0) >= 0.6 * ov.h)                                                       # the cursor: a bright line most of the strip's height
    ca, cb = col(a), col(b); assert len(ca) and len(cb) and cb.mean() > ca.mean() + 400 and abs(ca.mean() - (600 - 300) / 3000 * 959) < 4
    assert any(w.lines == ['Imagery: someone'] for w in ov.overlay.widgets if hasattr(w, 'lines'))


def test_the_overlay_uses_the_tiles_style_for_its_maps_and_has_no_caption_when_there_is_nothing_to_say(series, tiles):
    ov = GO.GapOverlay(series, (960, 540), T0 + 300, T0 + 3300, 'UTC', tiles); assert ov.overlay.st['style'] == 'osm' and ov.caption is not None                                  # "not filmed" is always said
