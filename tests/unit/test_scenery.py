"""edit/scenery.py (K3): the scenery camera avoids every person, takes the best scenery, holds or pans slowly, and cuts within its budget."""
import numpy as np
import pytest
from strata360.edit import scenery as SC, view_quality as VQ


def grid(n=80, tex=8.0, hz=2.0):
    f = lambda v: np.full((n, 12, 24), v, np.float16); return dict(hz=hz, tex=f(tex), clip_hi=f(0.0), clip_lo=f(0.0))


HEAD = lambda t: 0.0
PRIOR = lambda t, rel: 0.5
NOBODY = lambda t: []
ST = SC.Settings(noise=0.0)


def run(g, t0=0.0, t1=8.0, prior=PRIOR, boxes=NOBODY, st=ST, seed=0, start=None): return SC.track(g, t0, t1, HEAD, prior, boxes, st, np.random.default_rng(seed), start)


def test_it_holds_still_when_nothing_is_better_and_the_cost_of_moving_keeps_it_there():
    p = run(grid()); assert len(set(p['yaw'])) == 1 and p['jumps'] == [] and len(p['yaw']) == 9 and p['budget'] == 0


def test_it_never_looks_at_a_person_even_when_that_is_where_the_best_scenery_is():
    g = grid(); g['tex'][:, :, 12:16] = 14.0                                                                       # the best detail is straight ahead (columns 12 to 15 are yaw 0 to 60)
    me = lambda t: [(30.0, 0.0, 50.0)]                                                                              # a person right there
    p = run(g, boxes=me)
    for t, y in zip(p['times'], p['yaw']): assert SC.person_share(y, 0.0, ST.hfov, ST.aspect, me(t), ST) <= ST.person_share + 1e-9
    free = run(g); assert abs(SC.wrap(free['yaw'][0] - 30)) < 40                                                     # without the person it does look there


def test_it_pans_towards_better_scenery_slowly_one_bin_a_step_at_most_and_without_cuts_in_a_short_window():
    g = grid(); g['tex'][:, :, 18:] = 14.0                                                                         # much better detail to the right (yaw 90 to 180)
    p = run(g, t1=8.0, st=SC.Settings(noise=0.0, pan_cost=0.002), start=0.0); y = np.unwrap(np.radians(p['yaw'])) * 180 / np.pi
    assert p['jumps'] == [] and np.abs(np.diff(y)).max() <= SC.BIN_DEG + 1e-6 and y[-1] > y[0] + 14                       # it moves, never faster than 15 degrees a second, and never cuts: a window under half a minute has no budget


def test_a_long_window_may_cut_to_a_far_better_direction_but_never_more_than_its_budget():
    g = grid(n=140); g['tex'][:40, :, :12] = 14.0; g['tex'][40:, :, 12:] = 14.0                                      # the good side changes halfway through a minute
    p = run(g, t0=0.0, t1=60.0, st=SC.Settings(noise=0.0, budget_per_min=2.0)); assert p['budget'] == 2 and 1 <= len(p['jumps']) <= 2
    none = run(g, t0=0.0, t1=60.0, st=SC.Settings(noise=0.0, budget_per_min=0.0)); assert none['jumps'] == [] and none['budget'] == 0
    cheap = run(g, t0=0.0, t1=60.0, st=SC.Settings(noise=0.0, budget_per_min=6.0, jump_cost=0.0)); assert len(cheap['jumps']) <= 6


def test_a_better_rated_direction_is_preferred_and_the_same_seed_gives_the_same_camera():
    prior = lambda t, rel: 0.9 if abs(rel) > 120 else 0.1                                                           # the scenes stage likes what is behind
    p = run(grid(), prior=prior); assert abs(SC.wrap(p['yaw'][0])) > 100
    a, b, c = run(grid(), seed=3, st=SC.Settings(noise=0.05)), run(grid(), seed=3, st=SC.Settings(noise=0.05)), run(grid(), seed=4, st=SC.Settings(noise=0.05)); assert a['yaw'].tolist() == b['yaw'].tolist() and a['yaw'].tolist() != c['yaw'].tolist()


def test_availability_is_zero_where_every_direction_has_a_person_or_is_dark_and_high_where_there_is_somewhere_to_look():
    ring = lambda t: [(float(y), 0.0, 70.0) for y in range(-180, 180, 30)]                                           # people all round
    assert SC.availability(grid(n=20), [1.0, 2.0], HEAD, PRIOR, ring, ST).max() == 0.0
    assert SC.availability(grid(n=20), [1.0], HEAD, PRIOR, NOBODY, ST)[0] > 0.5 and SC.availability(grid(n=20, tex=0.2), [1.0], HEAD, PRIOR, NOBODY, ST)[0] < 0.1


def test_the_camera_path_is_continuous_across_pans_and_a_jump_is_a_cut_of_one_frame():
    path = dict(times=np.array([0.0, 1.0, 2.0, 3.0, 4.0]), yaw=np.array([165.0, 175.0, -175.0, -165.0, 20.0]), jumps=[4]); kf = SC.keyframes(path, 4.0, pitch=-3.0, fov=100.0)
    assert [k['yaw'] for k in kf[:4]] == [165.0, 175.0, 185.0, 195.0]                                                # through the wrap-around without a spin
    cut = [k for k in kf if k['t'] >= 3.9]; assert cut[0]['t'] == pytest.approx(3.96) and cut[0]['yaw'] == 195.0 and cut[1]['t'] == 4.0 and cut[1]['yaw'] == 20.0 and all(k['fov'] == 100.0 and k['pitch'] == -3.0 for k in kf)


def test_a_person_box_covers_a_share_of_the_view_in_proportion_to_its_size():
    assert SC.person_share(0.0, 0.0, 100, 16 / 9, [], ST) == 0.0 and SC.person_share(0.0, 0.0, 100, 16 / 9, [(0.0, 0.0, 40.0)], ST) > 0.03
    near, far = SC.person_share(0.0, 0.0, 100, 16 / 9, [(0.0, 0.0, 60.0)], ST), SC.person_share(0.0, 0.0, 100, 16 / 9, [(0.0, 0.0, 20.0)], ST); assert near > far > 0 and SC.person_share(0.0, 0.0, 100, 16 / 9, [(180.0, 0.0, 60.0)], ST) == 0.0


# ---- in the framing and the candidates

def test_the_scenery_and_free_view_techniques_are_in_the_library_and_need_their_availability_features():
    from strata360.edit import techniques as TQ
    lib = TQ.load(); s, f = lib['scenery'], lib['free_view']
    assert not s.dialogue_ok and not f.dialogue_ok and not s.hero and 'scenery_ok' in s.needs and 'free_ok' in f.needs and s.scale == 'wide' and f.max_consecutive == 1
    assert TQ.instantiate(s, 5.0, np.random.default_rng(0), look_yaw=20.0)['keyframes'][0]['yaw'] == 20.0


def views_data(g=None, boxes=NOBODY, prior=PRIOR):
    return dict(person=[], you=[], heading=HEAD, speakers=[], views=dict(grid=g, heading=HEAD, boxes=boxes, prior=prior))


def test_the_framing_uses_the_scenery_engine_and_a_fixed_free_view_and_falls_back_to_straight_ahead_without_a_grid():
    from strata360.edit import framing as FR, techniques as TQ
    lib = TQ.load(); g = grid(); g['tex'][:, :, 18:] = 14.0; seg = lambda tech: dict(id='c@10.00', clip='c', clip_start_s=10.0, dur_s=6.0, technique=tech, variant_seed=5)
    p = FR.resolve_segment(seg('scenery'), lib, views_data(g)); yaws = [k['yaw'] for k in p['keyframes']]; assert p['subject'] == 'scenery' and p['ref'] == 'world' and 'nobody in view' in p['why'] and abs(SC.wrap(yaws[0] - 127.5)) < 60 and p['keyframes'][-1]['t'] == 6.0
    q = FR.resolve_segment(seg('free_view'), lib, views_data(g)); k = q['keyframes']; assert q['subject'] == 'free' and k[0]['yaw'] == k[1]['yaw'] and k[0]['fov'] in FR.FREE_HFOVS and abs(SC.wrap(k[0]['yaw'] - 135)) < 60 and 'score' in q['why']
    for tech in ('scenery', 'free_view'):
        none = FR.resolve_segment(seg(tech), lib, views_data(None)); assert none['subject'] == 'heading' and 'no quality grid' in none['why']
    assert FR.resolve_segment(seg('scenery'), lib, dict(views_data(g), views=None))['subject'] == 'heading'                                            # a clip whose views could not be loaded
    again = FR.resolve_segment(seg('scenery'), lib, views_data(g)); assert [k['yaw'] for k in again['keyframes']] == yaws                              # the same seed: the same camera


def test_the_scenery_camera_in_the_framing_keeps_off_people():
    from strata360.edit import framing as FR, techniques as TQ
    me = lambda t: [(0.0, 0.0, 60.0), (90.0, 0.0, 50.0), (-90.0, 0.0, 50.0)]; g = grid(); g['tex'][:, :, 12:14] = 14.0                                      # the best detail is where someone stands
    p = FR.resolve_segment(dict(id='c@1', clip='c', clip_start_s=1.0, dur_s=6.0, technique='scenery', variant_seed=1), TQ.load(), views_data(g, boxes=me))
    for k in p['keyframes']: assert SC.person_share(k['yaw'], k['pitch'], k['fov'], 16 / 9, me(0), SC.Settings()) <= 0.02 + 1e-9


def test_the_people_boxes_come_from_the_identity_samples_and_every_detection_of_the_people_stage():
    from strata360.edit import clip_views as CV
    ident = dict(samples=[dict(t_s=5.0, me=dict(yaw=170.0, pitch=-10.0, height_deg=50.0), others=[dict(yaw=-80.0, pitch=0.0, height_deg=40.0)])])
    people = dict(people=[dict(t_s=5.0, yaw=30.0, pitch=2.0, height_deg=None), dict(t_s=5.5, yaw=-30.0, pitch=0.0, height_deg=33.0), dict(t_s=20.0, yaw=0.0, pitch=0.0, height_deg=50.0), dict(t_s=None, yaw=1.0, pitch=1.0)])
    at = CV.boxes_fn(ident, lambda t: 100.0, people); out = at(5.2)
    assert (170.0 + 100.0 - 360.0, -10.0, 50.0) in [tuple(round(x, 1) for x in b) for b in out] and (130.0, 2.0, 40.0) in out and (70.0, 0.0, 33.0) in out and len(out) == 4 and at(40.0) == [] and CV.boxes_fn(None, lambda t: 0.0)(1.0) == []        # a face with no body counts as 40 degrees
