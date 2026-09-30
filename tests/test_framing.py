"""Framing of plan windows and the preview projection. Run: .venv/bin/python tests/test_framing.py"""
import os, sys
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))
from strata360.edit import framing as FR, techniques as TQ
from strata360.render import preview as PV


def seg(tech, t0=10.0, dur=4.0): return dict(id='c@10.00', clip='c', clip_start_s=t0, dur_s=dur, technique=tech, variant_seed=3)


def data(person=None, you=None, speakers=None): return dict(person=person or [], you=you or [], heading=lambda t: 30.0, speakers=speakers or [])


def samples(yaw0, rate, t0=8.0, n=10, who='other'): return [dict(t=t0 + k, yaw=(yaw0 + rate * k) % 360, pitch=-10.0, who=who, speaking=False) for k in range(n)]


def test_a_followed_person_stays_in_the_middle_of_the_framing():
    lib = TQ.load(); p = FR.resolve_segment(seg('hold_wide'), lib, data(person=samples(100, 10)))
    assert p['subject'] == 'person' and abs(p['keyframes'][0]['yaw'] - 100 - 20) < 12 and p['keyframes'][-1]['yaw'] - p['keyframes'][0]['yaw'] > 25     # 4 s at 10 deg/s: the camera turns with them


def test_speaker_and_fallbacks():
    lib = TQ.load(); sp = lambda label: [dict(t0=9.0, t1=15.0, label=label)]
    assert FR.resolve_segment(seg('hold_wide'), lib, data(person=samples(100, 0), you=samples(200, 0, who='you'), speakers=sp('wearer')))['subject'] == 'you'
    assert FR.resolve_segment(seg('hold_wide'), lib, data(person=samples(100, 0), you=samples(200, 0, who='you'), speakers=sp('other')))['subject'] == 'person'
    p = FR.resolve_segment(seg('hold_wide'), lib, data()); assert p['subject'] == 'heading' and abs(p['keyframes'][0]['yaw'] - 30) < 1e-6
    assert FR.resolve_segment(seg('planet_fill'), lib, data(person=samples(100, 0)))['subject'] == 'none'


def test_projection_centre_and_planet():
    g = PV.Grid(64, 36); mx, my = PV.view_maps(g, 400, 200, np.radians(90), 0.0, 0.0, 90.0)
    assert abs(mx[18, 32] - (0.75 * 400 - 0.5)) < 4 and abs(my[18, 32] - 99.5) < 2                      # looking right (yaw 90): the centre pixel is lon +90 at the horizon
    mx, my = PV.view_maps(g, 400, 200, 0.0, -np.pi / 2, 0.0, 260.0); assert my[18, 32] > 190 and np.isfinite(mx).all() and np.isfinite(my).all()      # straight down: the nadir row; planet fov is valid everywhere


if __name__ == '__main__':
    fns = [v for k, v in sorted(globals().items()) if k.startswith('test_')]; bad = 0
    for fn in fns:
        try: fn(); print('ok  ', fn.__name__)
        except Exception as e: bad += 1; print('FAIL', fn.__name__, repr(e)[:300])
    print(f'{len(fns) - bad}/{len(fns)} passed'); sys.exit(bad)
