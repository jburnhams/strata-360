"""edit/score.py: the score plan (G2) on plain numbers: quiet bars, sung phrases placed on their own beat, and the fidelity setting."""
import numpy as np
import pytest
from strata360.edit import score as S

BAR = 2.0
LEVELS = [0.9] * 8 + [0.15] * 8 + [0.4] * 8 + [0.65] * 8 + [0.9] * 8
ENERGY = [0.3, 0.45, 0.5, 0.6, 0.85, 0.9, 0.55, 0.4] * 4


def test_quiet_bars_exclude_any_bar_speech_touches():
    q = S.quiet_bars(10, BAR, [(3.0, 4.5), (15.9, 16.1)])
    assert [i for i, v in enumerate(q) if not v] == [1, 2, 7, 8] and S.quiet_bars(4, BAR, []) == [True] * 4


def test_sections_follow_the_level_changes():
    s = S.sections(LEVELS)
    assert [(x['first'], x['end'], x['level']) for x in s] == [(0, 8, 0.9), (8, 16, 0.15), (16, 24, 0.4), (24, 32, 0.65), (32, 40, 0.9)]


def test_a_sung_phrase_starts_on_its_original_beat_in_the_bar():
    d = np.arange(0, 41, 2.0)                                                       # bars of 2 s
    w = S.sung_window(dict(t0=10.5, t1=15.0), d, 20.9, BAR, 40)                    # sung from a quarter into bar 5, 4.5 s long
    assert w['offset'] == pytest.approx(0.25) and w['first'] == 10 and w['shift_s'] == pytest.approx(-0.9) and abs(w['shift_s']) <= BAR / 2
    assert w['phrase_bar'] == 11 and w['end'] == 11 + 3 + 1                         # lead-in, ceil(0.25 + 2.25) = 3 bars of singing, lead-out


def test_the_window_covers_the_phrase_plus_one_bar_each_side():
    d = np.arange(0, 41, 2.0); w = S.sung_window(dict(t0=8.0, t1=12.0), d, 30.0, BAR, 40)
    assert (w['end'] - w['first']) == 1 + 2 + 1


def item(pid, t0, t1, film_t): return dict(phrase=dict(id=pid, t0=t0, t1=t1), film_t=film_t)


def test_placing_rejects_too_many_too_close_and_over_speech():
    d = np.arange(0, 301, 2.0); items = [item(f'P{i}', 20, 24, 20 + 40 * i) for i in range(6)]
    placed, rej = S.place_sung(items, d, BAR, 150)
    assert [p['id'] for p in placed] == ['P0', 'P1', 'P2', 'P3'] and [r['id'] for r in rej] == ['P4', 'P5']
    placed, rej = S.place_sung([item('A', 20, 24, 20), item('B', 20, 24, 40)], d, BAR, 150)
    assert [p['id'] for p in placed] == ['A'] and 'closer' in rej[0]['why']
    placed, rej = S.place_sung([item('A', 20, 24, 20)], d, BAR, 150, speech=[(25.0, 27.0)])
    assert not placed and 'speech' in rej[0]['why']                               # not squeezed in
    placed, rej = S.place_sung([item('A', 20, 24, 296)], d, BAR, 150)
    assert not placed and 'past' in rej[0]['why']


def share(f, **kw): return S.plan(LEVELS, BAR, ENERGY, fidelity=f, **kw)['share_original']


def test_fidelity_one_generates_nothing_and_zero_plays_no_original():
    p1 = S.plan(LEVELS, BAR, ENERGY, 1.0); p0 = S.plan(LEVELS, BAR, ENERGY, 0.0)
    assert {s['source'] for s in p1['sections']} == {'original'} and p1['share_original'] == 1.0
    assert {s['source'] for s in p0['sections']} == {'generate'} and p0['share_original'] == 0.0
    assert all(s['strength'] == 0.0 for s in p0['sections'])                      # no reference audio at 0


def test_the_share_of_original_bars_never_falls_as_fidelity_rises():
    shares = [share(f) for f in np.linspace(0, 1, 21)]
    assert all(b >= a - 1e-9 for a, b in zip(shares, shares[1:])) and shares[0] == 0.0 and shares[-1] == 1.0


def test_a_level_the_original_never_reaches_is_reported_at_fidelity_one():
    p = S.plan([0.15] * 8, BAR, [0.7] * 10, 1.0)
    assert p['unreachable'] == [0] and p['sections'][0]['source'] == 'original'
    assert S.plan([0.15] * 8, BAR, [0.7] * 10, 0.5)['sections'][0]['source'] == 'generate'


def test_a_pinned_section_ignores_the_slider():
    pins = {8: 'original', 0: 'generate'}
    for f in (0.0, 0.5, 1.0):
        p = S.plan(LEVELS, BAR, ENERGY, f, pins=pins); by = {s['first']: s for s in p['sections']}
        assert by[8]['source'] == 'original' and by[0]['source'] == 'generate' and by[8]['pinned']


def test_moving_the_slider_changes_only_the_keys_of_sections_that_changed():
    a = {s['first']: s['key'] for s in S.plan(LEVELS, BAR, ENERGY, 0.75)['sections']}
    same = {s['first']: s['key'] for s in S.plan(LEVELS, BAR, ENERGY, 0.76)['sections']}
    far = {s['first']: s['key'] for s in S.plan(LEVELS, BAR, ENERGY, 0.2)['sections']}
    src = {s['first']: s['source'] for s in S.plan(LEVELS, BAR, ENERGY, 0.75)['sections']}; src2 = {s['first']: s['source'] for s in S.plan(LEVELS, BAR, ENERGY, 0.76)['sections']}
    assert all(a[k] == same[k] for k in a if src[k] == src2[k] == 'original')      # an original section is the same take
    assert a != far


def test_generated_sections_repaint_from_the_neighbours_only_at_high_fidelity():
    hi = S.plan([0.15] * 8, BAR, [0.95] * 10, 0.8)['sections'][0]; lo = S.plan([0.15] * 8, BAR, [0.95] * 10, 0.4)['sections'][0]
    assert hi['source'] == lo['source'] == 'generate' and hi['repaint'] and not lo['repaint'] and hi['strength'] > lo['strength'] > 0


def test_sung_moments_use_the_original_below_half_only_as_a_stem():
    w = [dict(first=2, end=6, phrase_bar=3, offset=0.0, id='P1')]
    assert S.plan(LEVELS, BAR, ENERGY, 0.75, sung=w)['sung'][0]['form'] == 'a' and S.plan(LEVELS, BAR, ENERGY, 0.25, sung=w)['sung'][0]['form'] == 'b'
    assert S.plan(LEVELS, BAR, ENERGY, 0.75, sung=w)['sections'][0]['sung']
