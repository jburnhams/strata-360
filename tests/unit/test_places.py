"""Which positions of a clip are looked up. Run: .venv/bin/python tests/test_places.py"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'src'))
from strata360.analysis.places import select_points

M = 50.0, 5.0                                    # the middle; 0.001 degrees of latitude is 111 m
at = lambda m: (M[0] + m / 111000.0, M[1])       # a point `m` metres north of the middle


def test_all_close_uses_the_middle_only():
    assert select_points(dict(start=at(-50), middle=M, end=at(60))) == ['middle']


def test_only_the_far_ends_are_added():
    assert select_points(dict(start=at(-500), middle=M, end=at(60))) == ['start', 'middle']
    assert select_points(dict(start=at(-50), middle=M, end=at(700))) == ['middle', 'end']
    assert select_points(dict(start=at(-500), middle=M, end=at(700))) == ['start', 'middle', 'end']


def test_start_and_end_when_each_is_near_the_middle_but_not_each_other():
    assert select_points(dict(start=at(-190), middle=M, end=at(190))) == ['start', 'end']       # 380 m apart, each within 200 m of the middle
    assert select_points(dict(start=at(-150), middle=M, end=at(-160))) == ['middle']            # near each other too


if __name__ == '__main__':
    fns = [v for k, v in sorted(globals().items()) if k.startswith('test_')]; bad = 0
    for f in fns:
        try: f(); print('ok  ', f.__name__)
        except AssertionError as e: bad += 1; print('FAIL', f.__name__, e)
    print(f'{len(fns) - bad}/{len(fns)} passed'); sys.exit(bad)
