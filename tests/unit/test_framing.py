"""Framing of plan windows and the preview projection. Run: .venv/bin/python tests/test_framing.py"""
import os, sys
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'src'))
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


def test_the_candidates_own_view_decides_the_subject():
    lib = TQ.load(); both = data(person=samples(100, 0), you=samples(200, 0, who='you'))
    assert FR.resolve_segment(dict(seg('hold_wide'), kind='you'), lib, both)['subject'] == 'you' and FR.resolve_segment(dict(seg('hold_wide'), kind='person'), lib, both)['subject'] == 'person'
    assert FR.resolve_segment(dict(seg('hold_wide'), kind='person'), lib, data())['subject'] == 'heading'                      # nobody in view: straight ahead


def test_projection_centre_and_planet():
    v = PV.EquirectView(64, 36); ez = np.array([0.0, 0.0, 1.0]); v.set_fov(90.0)
    mx, my = v.maps(np.array([1.0, 0.0, 0.0]), ez, 0.0, 400, 200)                                          # looking along +X (yaw 90): the centre pixel is lon +90 at the horizon
    assert abs(mx[18, 32] - (0.75 * 400 - 0.5)) < 4 and abs(my[18, 32] - 99.5) < 2
    v.set_fov(260.0, 1.0); mx, my = v.maps(np.array([0.0, 0.0, -1.0]), ez, 0.0, 400, 200); assert my[18, 32] > 190 and np.isfinite(mx).all() and np.isfinite(my).all()     # straight down: the nadir row
    v.set_fov(90.0, 0.0, 0.46); eq = (np.random.default_rng(1).random((200, 400, 3)) * 255).astype(np.uint8); v.set_background([0.1, 0.2, 0.3])
    out = v.render(eq, np.array([0.0, 0.0, -1.0]), ez, 0.0); assert out.shape == (36, 64, 3) and out.dtype == np.uint8 and tuple(out[0, 0]) == (25, 51, 76)      # the globe: a disc, the colour outside it


if __name__ == '__main__':
    fns = [v for k, v in sorted(globals().items()) if k.startswith('test_')]; bad = 0
    for fn in fns:
        try: fn(); print('ok  ', fn.__name__)
        except Exception as e: bad += 1; print('FAIL', fn.__name__, repr(e)[:300])
    print(f'{len(fns) - bad}/{len(fns)} passed'); sys.exit(bad)


def test_straight_ahead_turns_toward_a_clearly_more_interesting_view_and_otherwise_stays():
    from test_view_quality import maps
    lib = TQ.load(); q = maps(22)                                                                       # heading is 30 deg: column 19; the detail sits at column 22 (about 40 deg to the right of the heading)
    d = data(); d['quality'] = q; p = FR.resolve_segment(seg('hold_wide', t0=0.0), lib, d)
    assert p['subject'] == 'heading' and p['keyframes'][0]['yaw'] > 30 + 15 and 'turned' in p['why']
    d['quality'] = maps(19); p = FR.resolve_segment(seg('hold_wide', t0=0.0), lib, d); assert abs(p['keyframes'][0]['yaw'] - 30) < 1e-6      # already in view: no turn
