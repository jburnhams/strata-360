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
