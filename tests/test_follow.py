"""Choosing which other person to frame: stay with one, jump rarely. Run: .venv/bin/python tests/test_follow.py"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))
from strata360.analysis import follow as F

P = lambda yaw, h, face=True: dict(yaw=yaw, pitch=-20, height_deg=h, face=face)


def test_stays_with_one_person_even_when_another_is_briefly_bigger():
    frames = [dict(t=float(k), cands=[P(100 + k, 30), P(250, 34 if k == 4 else 20)]) for k in range(10)]        # person A drifts slowly; B is bigger only at t=4
    ch = F.choose(frames); assert {j for j, _ in ch} == {0} and F.switches(ch) == 1


def test_switches_when_the_person_leaves_or_the_other_is_clearly_better():
    frames = [dict(t=float(k), cands=[P(100, 30)] + ([P(250, 55)] if k >= 3 else [])) for k in range(10)]        # from t=3 a much closer person: worth one jump, and then it stays
    ch = F.choose(frames); assert F.switches(ch) == 2 and ch[0][0] == 0 and ch[9][0] == 1
    frames = [dict(t=float(k), cands=[P(100, 30)] if k < 4 else [P(200, 30)]) for k in range(8)]                 # the only person is gone: must switch
    assert F.switches(F.choose(frames)) == 2


def test_gaps_keep_the_same_person_and_nobody_gives_none():
    frames = [dict(t=0.0, cands=[P(100, 30)]), dict(t=1.0, cands=[]), dict(t=2.0, cands=[P(104, 30)]), dict(t=3.0, cands=[])]
    ch = F.choose(frames); assert ch[0][1] == ch[2][1] == 0 and ch[1] == (None, None) and ch[3] == (None, None)


if __name__ == '__main__':
    fns = [v for k, v in sorted(globals().items()) if k.startswith('test_')]; bad = 0
    for fn in fns:
        try: fn(); print('ok  ', fn.__name__)
        except Exception as e: bad += 1; print('FAIL', fn.__name__, repr(e)[:300])
    print(f'{len(fns) - bad}/{len(fns)} passed'); sys.exit(bad)
