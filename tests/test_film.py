"""Composer: length, blends, handles. Run: .venv/bin/python tests/test_film.py"""
import os, sys
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))
from strata360.render import film as F


class Fake:
    """Window k is a flat grey of level 60*(k+1); records what was asked for."""
    def __init__(self): self.asked = []
    def frames(self, k, a0, a1, yaw_extra=None):
        self.asked.append((k, a0, a1, None if yaw_extra is None else len(yaw_extra)))
        for _ in range(a1 - a0): yield np.full((8, 16, 3), 60 * (k + 1), np.uint8)


def segs(kinds, dur=2.0):
    out = []
    for i, k in enumerate(kinds):
        d = dict(id=f'c@{i}', film_start_s=i * dur, dur_s=dur, transition=dict(type=k, dur_s=0.0 if k == 'cut' else 0.5))
        out.append(d)
    return out


def run(kinds):
    src = Fake(); got = []; F.compose(segs(kinds), src, 10, got.append); return src, got


def test_film_length_is_exact_whatever_the_transitions():
    for kinds in (['cut', 'cut', 'cut'], ['cut', 'dissolve', 'dip'], ['cut', 'whip', 'dissolve']):
        src, got = run(kinds); assert len(got) == 3 * 2 * 10, (kinds, len(got))


def test_dissolve_dip_and_whip_shapes():
    src, got = run(['cut', 'dissolve', 'cut']); mid = got[20 - 2: 20 + 2]; levels = [int(g[0, 0, 0]) for g in mid]
    assert levels == sorted(levels) and levels[0] >= 60 and levels[-1] <= 120 and len(set(levels)) >= 3, levels          # a smooth climb from shot 1 (60) to shot 2 (120)
    assert (1, -2, 2, None) in src.asked and (0, 18, 22, None) in src.asked          # handles: the incoming shot starts 2 frames early, the outgoing one runs 2 frames on
    src, got = run(['cut', 'dip', 'cut']); assert min(int(g[0, 0, 0]) for g in got[15:25]) <= 10                        # black in the middle
    src, got = run(['cut', 'whip', 'cut']); assert any(y is not None for k, a, b, y in src.asked) and len(got) == 60


if __name__ == '__main__':
    fns = [v for k, v in sorted(globals().items()) if k.startswith('test_')]; bad = 0
    for fn in fns:
        try: fn(); print('ok  ', fn.__name__)
        except Exception as e: bad += 1; print('FAIL', fn.__name__, repr(e)[:300])
    print(f'{len(fns) - bad}/{len(fns)} passed'); sys.exit(bad)
