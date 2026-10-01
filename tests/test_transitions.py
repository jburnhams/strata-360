"""Transition choice. Run: .venv/bin/python tests/test_transitions.py"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))
from strata360.edit import transitions as TR


def seg(i, clip, t0, dur=4.0, start_beat=0, hi=False):
    import datetime as dt
    a = dt.datetime(2026, 2, 19, 10) + dt.timedelta(seconds=t0); b = a + dt.timedelta(seconds=dur)
    f = lambda x: x.strftime('%Y-%m-%dT%H:%M:%S.000Z'); return dict(id=f'{clip}@{t0:.2f}', clip=clip, utc_start=f(a), utc_end=f(b), dur_s=dur, start_beat=start_beat, energy_hi=hi)


def test_rules_by_gap_and_clip():
    s = TR.choose([seg(0, 'A', 0), seg(1, 'A', 10), seg(2, 'B', 4000), seg(3, 'B', 4010), seg(4, 'C', 4000 + 7 * 3600)], 0.5)
    assert [g['transition']['type'] for g in s] == ['cut', 'cut', 'dissolve', 'cut', 'dip'] and s[4]['transition']['dur_s'] == 1.0 and s[2]['transition']['dur_s'] == 0.5


def test_no_two_effects_in_a_row_and_fit_and_overrides():
    s = TR.choose([seg(0, 'A', 0), seg(1, 'B', 4000), seg(2, 'C', 9000)], 0.5); assert [g['transition']['type'] for g in s] == ['cut', 'dissolve', 'cut']        # the second would also be a dissolve: not directly after one
    s = TR.choose([seg(0, 'A', 0, dur=2.0), seg(1, 'B', 4000, dur=2.0)], 0.5, forced={'B@4000.00': 'dip'}); assert s[1]['transition']['type'] == 'dip' and s[1]['transition']['dur_s'] <= 1.0   # at most half of the shorter window
    s = TR.choose([seg(0, 'A', 0, hi=True), seg(1, 'B', 100, start_beat=8, hi=True), seg(2, 'C', 200, start_beat=16, hi=True)], 0.5); assert sum(g['transition']['type'] == 'whip' for g in s) <= 1   # whips are rare


if __name__ == '__main__':
    fns = [v for k, v in sorted(globals().items()) if k.startswith('test_')]; bad = 0
    for fn in fns:
        try: fn(); print('ok  ', fn.__name__)
        except Exception as e: bad += 1; print('FAIL', fn.__name__, repr(e)[:300])
    print(f'{len(fns) - bad}/{len(fns)} passed'); sys.exit(bad)
