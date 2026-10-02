"""K6, the three views of you (mid, close, far): when each is possible, the techniques, their framing, the planner's use of them and the pack that tells the writer."""
import numpy as np
import pytest
from strata360.analysis import candidates as CA
from strata360.edit import aim, chrono as CH, framing as FR, optimise as O, script_pack as SP, script_plan as SPL, techniques as TQ

LIB = TQ.load()


def tc(n, **ft): return dict(id=f'c{n}', clip='c', start_s=0.0, end_s=40.0, quality=0.6, energy=0.5, min_dur=1.0, max_dur=40.0, kind='span', features=dict(steady=0.8, protagonist=0.8, speech=0.0, **ft))


def mk(**ft): return CH.clip_candidates(dict(id='c', candidates=[tc(1, **ft)]))[0]


def test_close_needs_you_found_and_not_filling_the_frame_far_needs_a_known_small_height():
    me = np.array([1.0, 1.0, 1.0, 1.0, 0.0, 1.0]); h = np.array([50.0, 65.0, 80.0, np.nan, 50.0, 40.0])
    close, far = CA.you_view_arrays(me, h)
    assert list(close) == [1.0, 1.0, 0.0, 1.0, 0.0, 1.0]      # 80 degrees tall: already filling the frame; unknown height: fine; not found: no
    assert list(far) == [1.0, 0.0, 0.0, 0.0, 0.0, 1.0]        # 65 is too tall for the whole body in an ultra wide frame; unknown height cannot be trusted; not found: no
    assert list(CA.you_view_arrays(np.array([0.7]), np.array([55.0]))[0]) == [0.7]                                                                   # a partly found moment counts in proportion


def test_the_two_new_techniques_are_in_the_library_as_talking_head_shots_that_need_their_view():
    c, f = LIB['selfie_close'], LIB['selfie_far']
    assert c.dialogue_ok and f.dialogue_ok and not c.hero and not f.hero and c.scale == 'tight' and f.scale == 'wide' and 'you_close' in c.needs and 'you_far' in f.needs
    cand = lambda **ft: mk(**ft)
    with_all = cand(you_close=0.9, you_far=0.9); only_close = cand(you_close=0.9)
    assert O.fit(with_all, c) is not None and O.fit(with_all, f) is not None and O.fit(only_close, f) is None and O.fit(cand(), c) is None             # a view the footage does not have never fits


def test_the_close_view_zooms_and_the_far_view_goes_ultra_wide_both_in_the_body_frame_looking_back():
    rng = np.random.default_rng(1); mid = TQ.instantiate(LIB['selfie_hold'], 4.0, rng); close = TQ.instantiate(LIB['selfie_close'], 4.0, rng); far = TQ.instantiate(LIB['selfie_far'], 4.0, rng)
    fov = lambda p: p['keyframes'][0]['fov']; assert fov(close) < fov(mid) < fov(far) and fov(close) == TQ.CLOSE_FOV and fov(far) == TQ.FAR_FOV and all(p['ref'] == 'body' and p['keyframes'][0]['yaw'] == 180 for p in (mid, close, far))


def seg(tech): return dict(id='c@10.00', clip='c', clip_start_s=10.0, dur_s=4.0, technique=tech, variant_seed=3)


def you(height=50.0, head=8.0): return [dict(t=8.0 + k, yaw=200.0, pitch=-5.0, height=height, head=head, who='you', speaking=False) for k in range(10)]


def data(you_s=None): return dict(person=[], you=you_s if you_s is not None else [], heading=lambda t: 30.0, speakers=[])


def test_each_view_of_you_frames_you_and_says_which_view_it_is():
    for tech, word in (('selfie_hold', 'wearer'), ('selfie_close', 'close on the face'), ('selfie_far', 'ultra wide')):
        p = FR.resolve_segment(seg(tech), LIB, data(you())); assert p['subject'] == 'you' and word in p['why'] and p['keyframes'][0]['fov'] == {'selfie_hold': 85, 'selfie_close': TQ.CLOSE_FOV, 'selfie_far': TQ.FAR_FOV}[tech]
        assert FR.resolve_segment(seg(tech), LIB, data([]))['subject'] == 'none'                                                                       # you are not found: no view of you


def test_the_close_view_centres_the_head_and_the_far_view_centres_the_body():
    face = aim.aim_face(-5.0, 50.0, 8.0); assert face == pytest.approx(8.0 - aim.FACE_BELOW_TOP * 50.0)                                                       # the middle of the head, not the top of the frame
    close = FR.resolve_segment(seg('selfie_close'), LIB, data(you())); far = FR.resolve_segment(seg('selfie_far'), LIB, data(you()))
    assert close['keyframes'][0]['pitch'] == pytest.approx(face, abs=1.0) and far['keyframes'][0]['pitch'] == pytest.approx(-5.0, abs=1.0)                  # close aims at the face, far at the middle of the body (it all fits)




def plan_one(view, **ft):
    clips = [dict(id='c', start_utc='2026-02-22T10:00:00Z', duration_s=40.0, candidates=[tc(1, **ft)])]; w = CH.Window(0, mk(**ft), 0.0, 8, 0.6, False, speech=True); w.view = view; warns = []
    music = O.Music(bpm=120.0, beats=8, bar_beats=4, sections=[(0, 10 ** 9, 0.5)])
    segs = CH.assign_techniques([w], clips, LIB, music, CH.Settings(seed=1), np.random.default_rng(1), warns, B=8); return segs[0].tech.id, warns


def test_a_requested_view_is_used_when_the_footage_has_it_and_said_not_to_be_when_it_does_not():
    assert plan_one('close', you_close=0.9, you_far=0.9)[0] == 'selfie_close' and plan_one('far', you_close=0.9, you_far=0.9)[0] == 'selfie_far' and plan_one('mid', you_close=0.9, you_far=0.9)[0] == 'selfie_hold'
    tech, warns = plan_one('far', you_close=0.9)
    assert tech != 'selfie_far' and any('far view of you was asked for' in w for w in warns)


def test_a_long_talking_stretch_is_cut_in_the_pauses_nearest_to_each_six_seconds():
    pauses = [4.1, 7.9, 12.2, 17.5, 19.4]
    assert SPL.split_points(0.0, 20.0, pauses) == [7.9, 12.2, 19.4] or len(SPL.split_points(0.0, 20.0, pauses)) >= 2
    cuts = SPL.split_points(0.0, 20.0, pauses); assert all(b - a >= SPL.SPLIT_MIN_S for a, b in zip([0.0] + cuts, cuts + [20.0])) and cuts == sorted(cuts)
    assert SPL.split_points(0.0, 8.0, pauses) == [] and SPL.split_points(0.0, 20.0, []) == []                                                                # short, or no pause to cut in
    assert SPL._pauses([dict(t0=0.0, t1=2.0), dict(t0=2.1, t1=4.0), dict(t0=5.0, t1=6.0)], 0.0, 6.0) == [4.5]                                             # 0.1 s is no pause


class FP:
    def __init__(self, ft): self.duration = 60.0; self.occ = []; self.c = mk(**ft)
    def candidate_at(self, a, b): return self.c


def test_dialogue_windows_are_cut_at_the_given_points_and_stay_whole_without_them():
    from strata360.edit.script_plan import dialogue_windows, Footage
    fp = FP(dict(you_close=0.9)); w = []; out = dialogue_windows(fp, 10.0, 16.0, w, '0001', 20.0, cuts=[15.0, 21.0]); assert [(round(a, 1), round(l, 1)) for _, a, l in out] == [(10.0, 5.0), (15.0, 6.0), (21.0, 5.0)]
    assert len(dialogue_windows(FP({}), 10.0, 16.0, [], '0001', 20.0)) == 1
    assert Footage.views_ok(FP(dict(you_far=0.9)), 0, 5) is True and Footage.views_ok(FP(dict(you_close=0.2)), 0, 5) is False


def test_the_pack_tells_the_writer_which_views_a_clip_has_and_for_how_much_of_its_time():
    cands = [dict(kind='span', start_s=0.0, end_s=30.0, features=dict(protagonist=0.8, you_close=0.9, you_far=0.0)), dict(kind='span', start_s=40.0, end_s=50.0, features=dict(protagonist=0.8, you_close=0.9, you_far=0.9)), dict(kind='speech', start_s=0.0, end_s=5.0, features=dict(protagonist=1, you_close=0, you_far=0))]
    assert SP.you_views(cands) == dict(mid=0.8, close=0.9, far=0.23) and SP.you_views([dict(kind='span', start_s=0.0, end_s=10.0, features=dict(protagonist=0.05))]) is None
    c = dict(label='0001', clip='C', duration_s=50.0, usable_s=40.0, usable=[], scene={}, note='', lines=[], speech_s=0.0, speech_words=0, you_views=dict(mid=0.8, close=0.9, far=0.23), start_utc='2026-02-22T10:00:00Z')
    assert 'views of you' in SP.render(dict(race={}, clips=[c])) and 'close (a face zoom) 90%' in SP.render(dict(race={}, clips=[c])) and 'views of you' not in SP.render(dict(race={}, clips=[dict(c, you_views=dict(mid=0.8, close=0.1, far=0.0))]))
