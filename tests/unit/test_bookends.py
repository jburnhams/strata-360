"""Openings and endings (edit/bookends.py): the pure parts. The window search, the spacing of candidates, the globe wrapped round a face shot, the plan segment of a candidate and the vision model's answer."""
import numpy as np
from strata360.edit import bookends as B


def test_windows_need_a_good_mean_and_no_bad_second():
    t = np.arange(0, 20.0); score = np.ones(20); score[8] = 0.2
    got = dict(B.pick_windows(t, score, 4.0, 0.8, 0.5))
    assert 0.0 in got and 3.0 in got and 4.0 not in got and 8.0 not in got and 9.0 in got               # windows 4 to 8 all contain the bad second
    assert B.pick_windows(t, score, 4.0, 0.8, 0.5, extra=lambda a, b: None) == []                        # a veto removes every window
    assert dict(B.pick_windows(t, np.full(20, 0.9), 4.0, 0.8, 0.5, extra=lambda a, b: 0.5))[0.0] == 0.45


def test_candidates_are_kept_apart_in_time():
    items = [(0.9, dict(clip='a', clip_start_s=10.0)), (0.8, dict(clip='a', clip_start_s=12.0)), (0.7, dict(clip='b', clip_start_s=12.0)), (0.6, dict(clip='a', clip_start_s=30.0))]
    got = [it['clip_start_s'] for _, it in B.spread(items, 12.0)]
    assert got == [10.0, 12.0, 30.0] and [it['clip'] for _, it in B.spread(items, 12.0)] == ['a', 'b', 'a']


FACE = dict(ref='world', subject='you', keyframes=[dict(t=0.0, yaw=40.0, pitch=2.0, fov=58.0), dict(t=1.5, yaw=42.0, pitch=2.0, fov=58.0), dict(t=3.2, yaw=41.0, pitch=1.0, fov=58.0)])


def test_an_opening_starts_as_the_planet_and_lands_on_the_face():
    p = B.globe_path(FACE, G=2.2); k = p['keyframes']
    assert k[0]['t'] == 0.0 and k[0]['pitch'] == -90.0 and k[0]['fov'] == 260.0 and k[0]['dist'] == 1.0 and k[0]['ease'] == 'smooth'
    assert k[1]['t'] == 2.2 and k[1]['fov'] == 58.0 and k[1]['dist'] == 0.0 and k[-1]['t'] == 5.4                  # the face keyframes moved 2.2 s in
    assert k[0]['yaw'] == 40.0 - B.SPIN_DEG and FACE['keyframes'][0]['t'] == 0.0                                   # (the input is not changed)


def test_an_ending_is_the_face_then_the_planet_closing():
    k = B.globe_path(FACE, G=2.2, outro=True)['keyframes']
    assert k[0]['t'] == 0.0 and k[0]['fov'] == 58.0 and k[-1]['t'] == 5.4 and k[-1]['pitch'] == -90.0 and k[-1]['fov'] == 260.0 and k[-1]['dist'] == 1.0 and k[-2]['ease'] == 'smooth'


def test_a_candidate_becomes_a_plan_segment():
    c = dict(id='intro-crowd-0', kind='crowd', where='intro', clip='CAM_1', clip_start_s=12.0, dur_s=5.0, technique='push_in', variant_seed=1000)
    g = B.segment_of(c); assert g['clip'] == 'CAM_1' and g['clip_start_s'] == 12.0 and g['dur_s'] == 5.0 and g['technique'] == 'push_in' and g['kind'] == 'best' and g['id'].endswith('intro-crowd-0')
    assert B.segment_of(dict(c, kind='globe_face', technique='selfie_close'))['kind'] == 'you'


def test_the_models_answer_is_read_even_with_a_trailing_comma():
    cs = [dict(id='a', dur_s=5.0), dict(id='b', dur_s=5.0)]

    class Server:
        def ask(self, prompt, images, max_tokens): return 'Here: {"scores": [{"i": 0, "score": 6, "why": "ok"}, {"i": 1, "score": 9, "why": "great"},], "best": 1}'
    scores, best = B.rank(cs, ['x.jpg', 'y.jpg'], 'intro', 'crowd', Server())
    assert best == 'b' and scores['b'] == dict(vlm_score=9.0, vlm_why='great') and scores['a']['vlm_score'] == 6.0
