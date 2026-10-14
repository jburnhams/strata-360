import numpy as np

from strata360.analysis import palette as P
from strata360.render import titles as TT


def _frame(rgb, h=60, w=120):
    return np.full((h, w, 3), rgb, np.uint8)


def _blocks(*rgbs):
    """One frame made of vertical blocks of the given colours."""
    f = np.zeros((60, 120, 3), np.uint8); n = len(rgbs); step = 120 // n
    for i, c in enumerate(rgbs): f[:, i * step:(i + 1) * step if i < n - 1 else 120] = c
    return f


def _hue_gap(a, b):
    d = abs(a - b) % 360; return min(d, 360 - d)


def test_lch_roundtrip_keeps_hue_and_lightness():
    rgb = P.lch_to_rgb(60.0, 40.0, 140.0); L, C, h = P.lch_of(rgb)
    assert abs(L - 60.0) < 1.5 and _hue_gap(h, 140.0) < 3.0


def test_out_of_gamut_chroma_is_lowered_not_clipped_in_hue():
    rgb = P.lch_to_rgb(50.0, 200.0, 300.0)
    assert all(0.0 <= v <= 1.0 for v in rgb) and _hue_gap(P.lch_of(rgb)[2], 300.0) < 8.0


def test_green_forest_gets_a_magenta_ish_complement():
    doc = P.analyse_pixels([_blocks((30, 110, 40), (20, 70, 30), (120, 160, 90))] * 3); s = doc['scheme']
    assert s['found'] and 100 < s['hue'] < 170
    assert _hue_gap(s['complement_hue'], s['hue']) == 180.0
    assert _hue_gap(P.lch_of(TT.hex_rgb(s['accent']))[2], s['complement_hue']) < 25.0


def test_base_and_accent_read_against_two_toned_footage():
    s = P.analyse_pixels([_blocks((20, 20, 30), (40, 50, 70))] * 2)['scheme']
    assert s['contrast']['base'] >= P.MIN_CONTRAST and s['contrast']['accent'] >= P.MIN_CONTRAST


def test_swatches_follow_the_colour_wheel():
    sw = P.swatches(120.0, 50.0); hues = {s['role']: s['hue'] for s in sw if s['role'] != 'neutral'}
    assert hues['base'] == 120.0 and hues['accent'] == 300.0 and hues['support'] == 270.0 and hues['analogous'] == 150.0 and hues['triad'] == 240.0
    assert {s['tone'] for s in sw if s['role'] == 'base'} == {'light', 'dark', 'mid_light', 'mid_dark'} and sum(s['role'] == 'neutral' for s in sw) == 2


def test_each_word_picks_the_swatch_that_reads_on_its_own_area():
    sw = P.analyse_pixels([_blocks((30, 110, 40), (120, 160, 90))] * 2)['scheme']['swatches']
    for area in ((0.05, 0.05, 0.08), (0.93, 0.93, 0.9), (0.5, 0.5, 0.5)):
        hex_, ct, _ = P.choose(sw, np.tile(np.array(area, np.float32), (50, 1)))
        assert ct >= 4.0 and ct >= 0.85 * max(P.pixel_contrast(s["hex"], P.region_lum(np.tile(np.array(area, np.float32), (50, 1)))) for s in sw)


def test_a_black_and_white_area_picks_the_best_it_can_and_an_exclusion_is_honoured():
    sw = P.swatches(30.0, 50.0); px = np.concatenate([np.zeros((50, 3)), np.ones((50, 3))]).astype(np.float32)
    best, _, _ = P.choose(sw, px); other, _, _ = P.choose(sw, px, exclude=(best,))
    assert other != best


def test_dark_footage_gets_light_text_and_bright_footage_dark():
    dark = P.analyse_pixels([_blocks((20, 25, 40), (30, 40, 60))] * 2); bright = P.analyse_pixels([_blocks((230, 225, 200), (240, 235, 215))] * 2)
    assert dark['mood']['tone'] == 'dark' and P.lch_of(TT.hex_rgb(dark['scheme']['base']))[0] > 55
    assert bright['mood']['tone'] == 'bright' and P.lch_of(TT.hex_rgb(bright['scheme']['base']))[0] < 55


def test_grey_footage_falls_back_to_amber_and_teal():
    doc = P.analyse_pixels([_frame((90, 90, 92))] * 2); s = doc['scheme']
    assert not s['found'] and s['hue'] == P.FALLBACK_HUE and doc['mood']['temperature'] == 'neutral'
    assert _hue_gap(s['complement_hue'], s['hue']) > 120


def test_a_speck_of_colour_does_not_decide_the_hue():
    f = _frame((120, 120, 120)); f[:2, :2] = (255, 0, 0)
    assert not P.analyse_pixels([f] * 2)['scheme']['found']


def test_scheme_is_complete_and_hex():
    s = P.analyse_pixels([_blocks((200, 80, 30), (60, 40, 30))] * 2)['scheme']
    for k in ('base', 'accent', 'support', 'light', 'dark', 'outline'): assert len(s[k]) == 7 and s[k][0] == '#'
    assert s['gradient'] == [s['base'], s['accent']] and s['outline'] in (s['light'], s['dark'])


def test_no_frames_is_an_error():
    import pytest
    with pytest.raises(RuntimeError): P.analyse_pixels([])


def test_load_and_prompt(tmp_path):
    assert P.load(str(tmp_path)) is None and P.for_prompt(None) == ''
    doc = P.analyse_pixels([_blocks((30, 110, 40), (120, 160, 90))] * 2)
    import json
    (tmp_path / P.FILE).write_text(json.dumps(doc)); got = P.load(str(tmp_path))
    text = P.for_prompt(got)
    assert doc['scheme']['base'] in text and doc['scheme']['accent'] in text and 'complement' in text
