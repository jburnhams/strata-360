"""Candidate builder on a synthetic clip folder. Run: .venv/bin/python tests/test_candidates.py"""
import json, os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'src'))
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


def test_chatter_is_not_dialogue_and_never_splits_good_footage():
    d = make(lambda x: 5.0, speech=[(5, 11), (20, 27)], labels=['other', 'wearer']); r = C.build(d); cs = r['candidates']
    sp = [c for c in cs if c['kind'] == 'speech']; assert len(sp) == 1 and 19 <= sp[0]['start_s'] <= 21 and sp[0]['features']['speech'] == 1.0
    assert len(r['spans']) == 1 and r['unusable'] == [] and [c for c in cs if c['kind'] == 'span'][0]['end_s'] - [c for c in cs if c['kind'] == 'span'][0]['start_s'] >= 39      # one span, the voices do not cut it


def test_flickering_voices_make_no_slivers_and_only_real_problems_are_unusable():
    flick = [(a, a + 1) for a in range(10, 30, 2)]                                     # other voices on for 1 s, off for 1 s, for 20 s: used to cut the clip into 1 s pieces
    d = make(lambda x: 100.0 if 35 <= x < 37 else 5.0, speech=flick, labels=['other'] * len(flick)); r = C.build(d)
    assert [(s['start_s'], s['end_s']) for s in r['spans']] == [(0.0, 35.0), (37.0, 40.0)], r['spans']                # only the shaky 35-37 s cuts the footage
    assert [(m['start_s'], m['end_s']) for m in r['unusable']] == [(35.0, 37.0)] and 'too shaky' in r['unusable'][0]['reasons'] and r['unusable'][0]['starts_because']
    assert not any('too short' in x for m in r['unusable'] for x in m['reasons'])


def test_candidates_overlap_as_alternative_views_of_the_same_footage():
    d = make(lambda x: 5.0 if x < 20 else 35.0, speech=[(24, 34)], labels=['wearer']); r = C.build(d); cs = r['candidates']; kinds = {c['kind'] for c in cs}
    assert 'span' in kinds and 'speech' in kinds and len(cs) >= 3 and sorted(c['priority'] for c in cs) == list(range(1, len(cs) + 1))
    sp = next(c for c in cs if c['kind'] == 'speech'); span = next(c for c in cs if c['kind'] == 'span' and c['start_s'] <= sp['start_s'] < c['end_s']); assert span['start_s'] <= sp['start_s'] and sp['end_s'] <= span['end_s']     # inside it, overlapping


if __name__ == '__main__':
    fns = [v for k, v in sorted(globals().items()) if k.startswith('test_')]; bad = 0
    for f in fns:
        try: f(); print('ok  ', f.__name__)
        except AssertionError as e: bad += 1; print('FAIL', f.__name__, e)
    print(f'{len(fns) - bad}/{len(fns)} passed'); sys.exit(bad)


def test_clear_dialogue_overrides_unusable():
    d = make(lambda x: 100.0 if 15 <= x < 25 else 5.0, speech=[(17, 23)], labels=['wearer']); r = C.build(d)                  # violent shake for 10 s, and you talk through the middle 6 s
    un = [(m['start_s'], m['end_s']) for m in r['unusable']]
    assert all(not (a < 23 and b > 17) for a, b in un), un                                                                       # the talking part is not reported unusable
    assert any(a < 17 for a, b in un) or any(b > 23 for a, b in un)                                                              # the shaky parts around it still are
