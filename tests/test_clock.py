"""Clock anchors and suggestion on synthetic data. Run: .venv/bin/python tests/test_clock.py"""
import json, os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))
import numpy as np
from strata360.gps import anchors as A

T0 = 1771520000.0            # arbitrary UTC epoch


def make_track(runs):
    t = np.arange(T0, T0 + 4000.0); sp = np.zeros_like(t)
    for a, b in runs: sp[(t >= T0 + a) & (t < T0 + b)] = 2.6
    return dict(t=t, speed=sp, cadence=np.where(sp > 0, 88.0, 0.0))


def make_race(offset, runs_clip, cam0, dur=200):
    d = tempfile.mkdtemp(); c = os.path.join(d, 'clips', 'CAM_x_0001_D'); os.makedirs(c)
    iso = lambda x: __import__('datetime').datetime.fromtimestamp(x, __import__('datetime').timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    json.dump(dict(clip_id='CAM_x_0001_D', time=dict(container_creation_time=iso(cam0), start_utc=iso(cam0 - offset))), open(c + '/clip.json', 'w'))
    t = np.arange(2, dur - 2, 1.0); on = np.zeros_like(t, bool)
    for a, b in runs_clip: on |= (t >= a) & (t < b)
    json.dump(dict(duration_s=dur, steps=dict(t=t.tolist(), hz=[3.0] * len(t), strength=np.where(on, 0.8, 0.05).tolist())), open(c + '/motion.json', 'w'))
    return d


def test_events_found():
    ev = A.gps_events(make_track([(300, 900), (1300, 2000)]))
    assert [k for _, k in ev] == ['start', 'stop', 'start', 'stop'], ev
    assert abs(ev[0][0] - (T0 + 300)) < 8 and abs(ev[1][0] - (T0 + 900)) < 8


def test_suggest_recovers_offset():
    tr = make_track([(300, 900), (1300, 1410), (2500, 3000)])             # true UTC of running starts: +300, +1300, +2500
    cam0 = T0 + 1300 + 370 - 40                                            # clip starts 40 s before the second start; camera is 370 s ahead
    race = make_race(370, [(40, 150)], cam0)
    res = A.suggest(race, tr); assert res and abs(res[0]['offset_s'] - 370) < 10, res


def test_near_offsets_are_preferred():
    tr = make_track([(300, 400), (1300, 1410), (2500, 2600)]); cam0 = T0 + 1300 + 370 - 40; race = make_race(370, [(40, 150)], cam0)
    res = A.suggest(race, tr, prior_s=0.0, sigma_s=900.0)
    assert res and abs(res[0]['offset_s'] - 370) < 10, res                                   # 370 s beats equally good matches hundreds of seconds further away
    far = A.suggest(race, tr, prior_s=-1000.0, sigma_s=300.0); assert far[0]['offset_s'] != res[0]['offset_s'] or far[0]['score'] < res[0]['score']


def test_anchor_snaps_and_fits():
    tr = make_track([(300, 900), (1300, 1410)]); cam0 = T0 + 1300 + 370 - 40; race = make_race(370, [(40, 150)], cam0)
    an = A.add_anchor(race, tr, '0001_D', 43.0, current_offset_s=0.0)      # a click 3 s after the event still snaps to it
    assert an['snapped'] and an['kind'] == 'start' and abs(an['offset_s'] - 370) < 8, an
    m = A.fit([an]); assert abs(m['offset_seconds'] - an['offset_s']) < 1e-6 and m['drift_s_per_day'] == 0
    an2 = dict(an); an2['camera_time'] = A._iso(A._ts(an['camera_time']) + 2 * 86400); an2['offset_s'] = an['offset_s'] + 20.0
    m2 = A.fit([an, an2]); assert abs(m2['drift_s_per_day'] - 10.0) < 0.1, m2
    cfg = {}; A.apply_to_config(cfg, [an]); assert cfg['camera_clock']['verified'] and 'drift_s_per_day' not in cfg['camera_clock']


if __name__ == '__main__':
    fns = [v for k, v in sorted(globals().items()) if k.startswith('test_')]; bad = 0
    for f in fns:
        try: f(); print('ok  ', f.__name__)
        except (AssertionError, ValueError) as e: bad += 1; print('FAIL', f.__name__, repr(e)[:300])
    print(f'{len(fns) - bad}/{len(fns)} passed'); sys.exit(bad)
