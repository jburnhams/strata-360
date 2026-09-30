"""Candidate builder on a synthetic clip folder. Run: .venv/bin/python tests/test_candidates.py"""
import json, os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))
import numpy as np
from strata360.analysis import candidates as C


def make(shake, speech=(), dur=40, labels=None):
    d = tempfile.mkdtemp(); j = lambda n, o: json.dump(o, open(os.path.join(d, n), 'w'))
    j('clip.json', dict(clip_id='CAM_x_0001_D', video=dict(source_frames=dur * 50, nominal_fps=50.0), time=dict(start_utc='2026-02-19T17:00:00Z')))
    t = np.arange(0, dur, 0.2); j('motion.json', dict(series=dict(t=t.tolist(), shake_dps=[float(shake(x)) for x in t], ang_speed_dps=[20.0] * len(t), acc_energy=[0.3] * len(t))))
    j('transcript.json', dict(segments=[dict(t0=a, t1=b, text='hello there', lang='en', no_speech=0.0, flags=[], suspect=False) for a, b in speech]))
    if labels: j('speakers.json', dict(segments=[dict(t0=a, t1=b, label=lab) for (a, b), lab in zip(speech, labels)]))
    return d


def test_shaky_parts_are_dropped_and_speech_is_its_own_candidate():
    d = make(lambda x: 100.0 if 15 <= x < 20 else 5.0, speech=[(24, 30)]); r = C.build(d); cs = r['candidates']
    spans = [(c['start_s'], c['end_s']) for c in cs]
    assert not any(a < 20 and b > 15 for a, b in spans), spans                            # nothing overlaps the shaky 15-20 s
    sp = [c for c in cs if c['features']['speech']]; assert len(sp) == 1 and 23 <= sp[0]['start_s'] <= 25 and sp[0]['min_dur'] >= 3.0 and sp[0]['transcript']
    assert all(c['end_s'] - c['start_s'] >= C.MIN_LEN for c in cs) and all(0 <= c['quality'] <= 1 for c in cs)
    un = [m for m in r['unusable'] if 14 <= m['start_s'] <= 21]; assert un and any('too shaky' in x for m in un for x in m['reasons']) and all(m['starts_because'] for m in un), r['unusable']      # the shaky stretch is reported with its reason
    assert all(c['why']['starts_because'] and c['why'].get('ends_because') for c in cs)
    assert 'scenes' in r['missing'] and cs[0]['start_utc'].startswith('2026-02-19T17:00:0')


def test_chatter_is_not_dialogue():
    d = make(lambda x: 5.0, speech=[(5, 11), (20, 27)], labels=['other', 'wearer']); cs = C.build(d)['candidates']
    sp = [c for c in cs if c['features']['speech']]; ch = [c for c in cs if c['features']['chatter'] > 0.5]
    assert len(sp) == 1 and 19 <= sp[0]['start_s'] <= 21 and len(ch) == 1 and 4 <= ch[0]['start_s'] <= 6 and ch[0]['features']['speech'] == 0.0


if __name__ == '__main__':
    fns = [v for k, v in sorted(globals().items()) if k.startswith('test_')]; bad = 0
    for f in fns:
        try: f(); print('ok  ', f.__name__)
        except AssertionError as e: bad += 1; print('FAIL', f.__name__, e)
    print(f'{len(fns) - bad}/{len(fns)} passed'); sys.exit(bad)
