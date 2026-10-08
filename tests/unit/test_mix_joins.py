"""audio/mix.py: where the windows sit on the film's clock and how each join crossfades (no ffmpeg)."""
import pytest
from strata360.audio import mix


def seg(clip, start, dur, cs=0.0, tr=None, **kw): return dict(clip=clip, clip_start_s=cs, dur_s=dur, film_start_s=start, transition=tr or dict(type='cut', dur_s=0.0), **kw)


def test_windows_are_read_end_to_end_when_the_plan_has_no_clock():
    assert mix.film_starts(dict(segments=[dict(dur_s=2.0), dict(dur_s=3.0)])) == [(0.0, 2.0), (2.0, 3.0)] and mix.film_starts(dict(segments=[seg('A', 1.0, 2.0)])) == [(1.0, 2.0)]


def test_a_cut_crossfades_over_thirty_milliseconds_a_transition_over_its_own_length_and_continuous_footage_is_marked():
    p = dict(segments=[seg('A', 0.0, 4.0, 0.0), seg('B', 4.0, 4.0, tr=dict(type='dissolve', dur_s=1.0)), seg('B', 8.0, 2.0, cs=0.0 + 0.0, tr=dict(type='cut', dur_s=0.0)), seg('B', 10.0, 3.0, cs=2.0)])
    j = mix.joins(p)
    assert j[0] == (0.0, False) and j[1] == (0.5, False)                                         # a dissolve: half its length each side of the cut
    assert j[2] == (mix.CUT_XFADE_S / 2, False)                                                   # a plain cut between different stretches
    assert j[3] == (mix.CUT_XFADE_S / 2, True)                                                    # window 3 starts where window 2 ended in the same clip: one continuous sound
    short = dict(segments=[seg('A', 0.0, 0.4), seg('B', 0.4, 0.4, tr=dict(type='dip', dur_s=2.0))]); assert mix.joins(short)[1][0] == pytest.approx(0.15)       # never more than the shorter window can give
