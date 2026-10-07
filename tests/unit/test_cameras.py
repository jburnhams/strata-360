"""edit/cameras.py: the camera list of a clip, best first, with trackings trimmed where the picture is bad and seeded free cameras."""
import numpy as np
from strata360.edit import cameras as CM


def grid(n=120, tex=8.0, hz=2.0):
    f = lambda v: np.full((n, 12, 24), v, np.float16); return dict(hz=hz, tex=f(tex), clip_hi=f(0.0), clip_lo=f(0.0))


def view(g=None, identity=None, boxes=lambda t: []):
    return dict(grid=g or grid(), heading=lambda t: 0.0, boxes=boxes, prior=lambda t, rel: 0.5, identity=identity or [])


def me_samples(a, b, yaw=170.0):
    return [dict(t_s=float(t), me=dict(yaw=yaw, pitch=0.0, height_deg=40.0), others=[]) for t in range(a, b)]


def kinds(cams): return [c['kind'] for c in cams]


def test_a_clip_without_a_grid_or_too_short_has_no_cameras():
    assert CM.build(dict(grid=None)) == [] and CM.build(view(grid(n=4))) == []


def test_every_clip_gets_heading_scenery_and_about_one_free_camera_per_fifteen_seconds():
    cams = CM.build(view())                                                                    # 60 s
    assert kinds(cams).count('heading') == 1 and kinds(cams).count('scenery') == 1 and kinds(cams).count('free') == 4
    assert 'you' not in kinds(cams) and 'person' not in kinds(cams)                            # nobody was found


def test_free_cameras_are_capped_and_cover_separate_stretches():
    cams = CM.build(view(grid(n=200)), max_free=3)                                             # 100 s would want 7
    free = sorted((c for c in cams if c['kind'] == 'free'), key=lambda c: c['start_s'])
    assert len(free) == 3 and all(a['end_s'] <= b['start_s'] + 1e-9 for a, b in zip(free, free[1:]))


def test_the_list_is_best_first_and_scores_are_between_zero_and_one():
    s = [c['score'] for c in CM.build(view())]; assert s == sorted(s, reverse=True) and all(0 <= x <= 1 for x in s)


def test_you_is_one_camera_per_stretch_where_the_wearer_is_seen_and_bridges_short_gaps():
    ident = me_samples(5, 15) + me_samples(17, 25) + me_samples(45, 55)                         # a 2 s gap bridges, a 20 s one does not
    you = [c for c in CM.build(view(identity=ident)) if c['kind'] == 'you']
    assert [(c['start_s'], c['end_s']) for c in sorted(you, key=lambda c: c['start_s'])] == [(5.0, 25.0), (45.0, 55.0)]


def test_a_tracking_is_shortened_where_the_picture_is_bad_at_its_ends():
    g = grid(); g['tex'][:20] = 0.2; g['tex'][-20:] = 0.2                                        # 10 s of mush at each end (tex under the flat limit)
    h = [c for c in CM.build(view(g)) if c['kind'] == 'heading'][0]
    assert h['start_s'] >= 9 and h['end_s'] <= 51


def test_free_cameras_avoid_a_foggy_direction_when_a_clear_one_exists():
    g = grid(); g['tex'][:, :, :12] = 0.2                                                       # the western half of the sphere is fog
    for c in CM.build(view(g)):
        if c['kind'] == 'free':
            y = c['aim']['keyframes'][0]['yaw']; assert y > -20, c


def test_the_scenery_camera_never_looks_at_a_person():
    me = lambda t: [(30.0, 0.0, 50.0)]
    c = [c for c in CM.build(view(boxes=me)) if c['kind'] == 'scenery'][0]
    from strata360.edit import scenery as SC
    for k in c['aim']['keyframes']: assert SC.person_share(k['yaw'], 0.0, c['aim']['fov'], 16 / 9, me(0), SC.Settings()) <= SC.Settings().person_share + 1e-9


def test_the_same_seed_gives_the_same_cameras_and_another_seed_other_poses():
    g = grid(); rng = np.random.default_rng(3); g['tex'] = (8 + rng.uniform(-3, 3, g['tex'].shape)).astype(np.float16)
    a, b, c = CM.build(view(g), seed=1), CM.build(view(g), seed=1), CM.build(view(g), seed=2)
    assert a == b and a != c


# the planner and the framing use the list

def aim_cam(kind, start, end, kfs, t0, score=0.8, cid='X'):
    return dict(id=cid, kind=kind, start_s=start, end_s=end, score=score, why='test', aim=dict(t0=t0, keyframes=kfs))


def kf(t, yaw, fov=100.0): return dict(t=t, yaw=yaw, pitch=0.0, fov=fov, ease='linear')


def test_a_window_takes_the_aim_of_the_camera_that_holds_it_cut_to_the_window_with_its_jump_kept():
    from strata360.edit import framing as FR
    cam = aim_cam('scenery', 0.0, 60.0, [kf(0, 0), kf(10, 40), kf(10.04, 120), kf(30, 150)], t0=0.0)        # a pan, a cut at 10 s, a slower pan
    p = FR.camera_path([cam], 'scenery', 8.0, 4.0)
    assert [k['t'] for k in p['keyframes']] == [0.0, 2.0, 2.04, 4.0] and p['keyframes'][0]['yaw'] == 32.0 and p['keyframes'][1]['yaw'] == 40.0 and p['keyframes'][2]['yaw'] == 120.0
    assert p['subject'] == 'scenery' and 'X' in p['why']


def test_a_free_cameras_times_are_from_its_own_start_and_a_window_outside_every_camera_gets_none():
    from strata360.edit import framing as FR
    cam = aim_cam('free', 20.0, 35.0, [kf(0, 10, 90), kf(15, 70, 90)], t0=20.0)
    p = FR.camera_path([cam], 'free', 27.5, 4.0); assert abs(p['keyframes'][0]['yaw'] - 40.0) < 1e-6 and abs(p['keyframes'][-1]['yaw'] - 56.0) < 1e-6
    assert FR.camera_path([cam], 'free', 40.0, 4.0) is None and FR.camera_path([cam], 'scenery', 27.5, 4.0) is None and FR.camera_path([], 'free', 27.5, 4.0) is None and FR.camera_path(None, 'free', 27.5, 4.0) is None


def test_the_best_scoring_camera_of_the_kind_is_the_one_used():
    from strata360.edit import framing as FR
    lo = aim_cam('free', 0.0, 30.0, [kf(0, 0), kf(30, 0)], 0.0, score=0.3, cid='LO'); hi = aim_cam('free', 0.0, 30.0, [kf(0, 90), kf(30, 90)], 0.0, score=0.9, cid='HI')
    assert 'HI' in FR.camera_path([lo, hi], 'free', 5.0, 4.0)['why']


def test_resolving_a_scenery_window_uses_the_cameras_aim_and_without_cameras_the_old_way():
    from strata360.edit import framing as FR, techniques as TQ
    lib = TQ.load(); g = dict(id='c@10.00', clip='c', clip_start_s=10.0, dur_s=4.0, technique='scenery', variant_seed=3)
    d = dict(person=[], you=[], heading=lambda t: 0.0, speakers=[], views=None, cameras=[aim_cam('scenery', 0.0, 60.0, [kf(0, 55), kf(60, 55)], 0.0)])
    p = FR.resolve_segment(g, lib, d); assert p['subject'] == 'scenery' and all(k['yaw'] == 55.0 for k in p['keyframes'])
    d['cameras'] = []; assert 'no quality grid' in FR.resolve_segment(g, lib, d)['why']


def test_person_hold_frames_another_person_and_is_offered_only_where_a_person_camera_is():
    from strata360.edit import framing as FR, techniques as TQ, chrono as CH, optimise as O
    lib = TQ.load(); assert lib['person_hold'].dialogue_ok is False
    g = dict(id='c@10.00', clip='c', clip_start_s=10.0, dur_s=4.0, technique='person_hold', variant_seed=3)
    other = [dict(t=8.0 + k, yaw=200.0, pitch=-5.0, height=40.0, head=8.0, who='other', speaking=False) for k in range(10)]
    p = FR.resolve_segment(g, lib, dict(person=other, you=[], heading=lambda t: 30.0, speakers=[])); assert p['subject'] == 'person'
    assert FR.resolve_segment(g, lib, dict(person=[], you=[], heading=lambda t: 30.0, speakers=[]))['subject'] == 'heading'
    cl = lambda cams: dict(id='c', start_utc='2026-02-19T10:00:00Z', duration_s=40.0, unusable=[], cameras=cams, candidates=[dict(id='c#0', clip='c', start_s=0.0, end_s=40.0, quality=0.6, energy=0.5, min_dur=1.0, max_dur=40.0, features=dict(steady=0.9, subject=1.0, protagonist=0.2, speech=0.0))])
    for cams, want in (([dict(kind='person', start_s=0.0, end_s=40.0, score=1.0)], True), ([], False)):
        clips = [cl(cams)]; m = O.Music(bpm=120, beats=40, bar_beats=4, sections=[(0, 40, 0.5)])
        plan = CH.plan(clips, lib, m, CH.Settings(seed=1, w_camlist=20.0)); assert ('person_hold' in [s.tech.id for s in plan]) is want
