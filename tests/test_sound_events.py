"""Sound categories and the suggested level of the clip's sound in the film. Run: .venv/bin/python tests/test_sound_events.py"""
import json, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))
from strata360.analysis import sound_events as SE


def doc(*wins): return dict(windows=[dict(t0=a, t1=b, cats=c, top=[]) for a, b, c in wins])


def test_every_listed_class_exists_in_the_model_except_known_gaps():
    cfg = os.path.join(SE.MODEL_DIR, 'config.json')
    if not os.path.exists(cfg): print('    (model not downloaded: skipped)'); return
    labels = set(json.load(open(cfg))['id2label'].values()); missing = [n for names in SE.CATEGORIES.values() for n in names if n not in labels]
    assert len(missing) <= 8, missing                                           # a few names may differ between model versions; most must match


def test_the_wearer_speaking_is_always_full_volume_and_other_sounds_follow_their_role():
    d = doc((0, 6, dict(cheering=0.8, wind=0.1)), (6, 12, dict(wind=0.7)), (12, 18, dict(water=0.6, wind=0.5)), (18, 24, dict(speech=0.7)), (24, 30, {}))
    assert SE.window_mix(d, 0, 6, wearer_speaks=True)['gain_db'] == 0.0
    cheer = SE.window_mix(d, 0, 6); assert -8 <= cheer['gain_db'] <= -5 and 'cheering' in cheer['why'][0]
    wind = SE.window_mix(d, 6, 12); assert wind['gain_db'] <= -24                                       # wind is pulled right down
    mixed = SE.window_mix(d, 12, 18); assert mixed['gain_db'] < -10 and mixed['gain_db'] > -20 and mixed['why'][0].startswith('water')           # a nice sound with wind on it: a little under the nice one
    assert SE.window_mix(d, 18, 24)['gain_db'] == -6.0 and SE.window_mix(d, 24, 30)['gain_db'] == SE.QUIET_DB and SE.window_mix(None, 0, 5)['gain_db'] == SE.QUIET_DB


def test_overlap_weighting_and_summary():
    d = doc((0, 6, dict(crowd=0.9)), (3, 9, dict(crowd=0.1, wind=0.8)))
    s = SE.scores_between(d, 3, 6); assert abs(s['crowd'] - 0.5) < 1e-9 and abs(s['wind'] - 0.4) < 1e-9
    assert SE.category_seconds(d)['crowd'] == 3.0


if __name__ == '__main__':
    fns = [v for k, v in sorted(globals().items()) if k.startswith('test_')]; bad = 0
    for fn in fns:
        try: fn(); print('ok  ', fn.__name__)
        except Exception as e: bad += 1; print('FAIL', fn.__name__, repr(e)[:300])
    print(f'{len(fns) - bad}/{len(fns)} passed'); sys.exit(bad)
