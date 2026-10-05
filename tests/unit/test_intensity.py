"""edit/intensity.py on synthetic signals: the level changes only on phrase boundaries, one loud window does not change it, marked moments get the top level, speech makes it sparser."""
import numpy as np
import pytest
from strata360.edit import intensity as I

BAR = 2.0


def sig(values, w=1.0): return dict(t=[(i + 0.5) * BAR for i in range(len(values))], v=list(values), weight=w)


def test_the_level_changes_only_on_phrase_boundaries():
    v = np.concatenate([np.zeros(10), np.ones(14), np.zeros(8)]); lv = I.curve(32, BAR, [sig(v)])['levels']
    assert len(lv) == 32 and all(len(set(lv[i:i + 4])) == 1 for i in range(0, 32, 4)) and lv[0] == I.LEVELS[0] and lv[16] == I.LEVELS[-1]


def test_one_loud_bar_does_not_change_the_level():
    v = np.zeros(32); v[13] = 1.0; v[0] = v[31] = 0.0; assert set(I.curve(32, BAR, [sig(np.r_[v, [1.0] * 0])], phrase_bars=4)['levels'][8:20]) == {I.LEVELS[0]}


def test_a_flat_signal_stays_at_one_level_and_no_signal_is_the_middle():
    assert len(set(I.curve(16, BAR, [sig(np.full(16, 3.0))])['levels'])) == 1
    assert len(set(I.curve(16, BAR, [])['levels'])) == 1


def test_a_value_hovering_at_a_boundary_does_not_flicker():
    v = np.tile([0.58, 0.66], 16); lv = I.curve(32, BAR, [sig(v)], smooth_bars=1)['phrases']; assert len(set(lv)) <= 2 and sum(a != b for a, b in zip(lv, lv[1:])) <= 1


def test_the_start_and_finish_get_the_top_level_when_marked():
    r = I.curve(32, BAR, [sig(np.zeros(32))], marks=[(1.0, 1.0, 0.0), (62.0, 1.0, 0.0)]); assert r['levels'][0] == I.LEVELS[-1] == r['levels'][-1] and r['levels'][12] == I.LEVELS[0]


def test_speech_makes_the_music_sparser():
    v = np.r_[np.zeros(4), np.ones(28)]; a = I.curve(32, BAR, [sig(v)])['levels']; b = I.curve(32, BAR, [sig(v)], speech=[(16.0, 40.0)])['levels']
    assert b[8] < a[8] and b[0:4] == a[0:4] and b[30] == a[30]


def test_signals_are_weighted_and_the_curve_is_deterministic():
    up = np.linspace(0, 1, 32); down = up[::-1]; a = I.curve(32, BAR, [sig(up, 3), sig(down, 1)])['levels']; assert a[-1] > a[0] and a == I.curve(32, BAR, [sig(up, 3), sig(down, 1)])['levels']


def test_a_last_short_phrase_is_still_covered():
    assert len(I.curve(10, BAR, [sig(np.arange(10))])['levels']) == 10
