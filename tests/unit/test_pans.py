"""edit/pans.py and the pan piece of render/film.py: a glide instead of a hard cut between consecutive shots of one clip, only when it is gentle and keeps the subject in shot."""
import numpy as np
import pytest
from strata360.edit import pans as PN, framing as FR, techniques as TQ
from strata360.render import film as FI


def kf(yaw0, yaw1=None, T=4.0, pitch=0.0, fov=90.0): return [dict(t=0.0, yaw=yaw0, pitch=pitch, fov=fov), dict(t=T, yaw=yaw0 if yaw1 is None else yaw1, pitch=pitch, fov=fov)]


def path(yaw0, yaw1=None, T=4.0, subject=None, track=None, ref='world', **kw): return dict(ref=ref, keyframes=kf(yaw0, yaw1, T, **kw), subject=subject or 'heading', **({'track': track} if track is not None else {}))


def seg(i, start, dur=4.0, clip='c', **kw): return dict(id=f'w{i}', clip=clip, clip_start_s=start, dur_s=dur, **kw)


def track(yaw, T=8.0, pitch=0.0): return [dict(t=float(t), yaw=yaw, pitch=pitch) for t in np.arange(0, T + 1)]


def test_a_gentle_glide_between_consecutive_shots_of_one_clip_is_allowed_and_described():
    tr, why = PN.plan(seg(0, 10.0), seg(1, 14.0), path(0.0), path(30.0)); assert why is None and tr['type'] == 'pan' and 0.6 <= tr['dur_s'] <= 1.2 and tr['dur_s'] <= 0.4 * 4.0 and '30 degrees' in tr['why'] and tr['a_dur'] == 4.0 and len(tr['a_kf']) == 2
    assert 1.5 * 30 / tr['dur_s'] <= PN.MAX_SPEED and PN.plan(seg(0, 10.0), seg(1, 13.75), path(0.0), path(-30.0))[0] is not None and PN.plan(seg(0, 10.0), seg(1, 14.4), path(0.0), path(-30.0))[0] is not None       # either way round; a quarter second of overlap or gap is what whole-beat windows leave


def test_it_is_refused_when_the_shots_are_not_consecutive_or_not_both_world_frame_cameras_or_the_move_is_dramatic_or_pointless_or_too_short():
    reason = lambda a, b, pa, pb: PN.plan(a, b, pa, pb)[1]
    assert 'not consecutive' in reason(seg(0, 10.0), seg(1, 20.0), path(0.0), path(20.0)) and 'not consecutive' in reason(seg(0, 10.0), seg(1, 14.8), path(0.0), path(20.0)) and 'not consecutive' in reason(seg(0, 10.0), seg(1, 13.3), path(0.0), path(20.0)) and 'not consecutive' in reason(seg(0, 10.0), seg(1, 14.0, clip='d'), path(0.0), path(20.0))
    assert 'world-frame' in reason(seg(0, 10.0), seg(1, 14.0), path(0.0, ref='body'), path(20.0)) and 'world-frame' in reason(seg(0, 10.0), seg(1, 14.0), path(0.0), path(20.0, ref='heading'))
    assert 'too big a move' in reason(seg(0, 10.0), seg(1, 14.0), path(0.0), path(120.0)) and 'too big a move' in reason(seg(0, 10.0), seg(1, 14.0), path(0.0), path(10.0, pitch=40.0)) and 'too big a move' in reason(seg(0, 10.0), seg(1, 14.0), path(0.0), path(10.0, fov=170.0))
    assert 'look the same way' in reason(seg(0, 10.0), seg(1, 14.0), path(0.0), path(2.0)) and 'too short' in reason(seg(0, 10.0, 1.2), seg(1, 11.2, 1.2), path(0.0, T=1.2), path(30.0, T=1.2))


def test_the_subject_of_the_first_shot_must_stay_in_view_through_the_whole_glide_and_the_second_from_the_middle_on():
    a, b = seg(0, 10.0), seg(1, 14.0); you0 = track(0.0)
    ok, _ = PN.plan(a, b, path(0.0, subject='you', track=you0), path(30.0)); assert ok is not None                                                              # you stay straight ahead, the camera turns 30 degrees: still within 0.42 of half the field of view
    gone, why = PN.plan(a, b, path(0.0, subject='you', track=track(-40.0)), path(40.0)); assert gone is None and "first shot's you would leave the frame" in why        # the camera turns away from you
    second, why2 = PN.plan(a, b, path(0.0), path(30.0, subject='person', track=track(-30.0))); assert second is None and "second shot's person would leave the frame" in why2   # the next subject is nowhere near where the glide ends
    late, _ = PN.plan(a, b, path(0.0), path(30.0, subject='person', track=track(30.0))); assert late is not None                                               # the second subject only has to be there from the middle on
    assert 'no track' in PN.plan(a, b, path(0.0, subject='you'), path(30.0))[1] and PN.plan(a, b, path(0.0, subject='scenery'), path(30.0, subject='free'))[0] is not None


def test_only_plain_same_clip_cuts_become_glides_and_the_plan_itself_is_not_changed():
    segs = [dict(seg(0, 10.0), transition=dict(type='cut', why='the first shot')), dict(seg(1, 14.0), transition=dict(type='cut', why='the same clip: a new view, not an effect')),
            dict(seg(2, 18.0), transition=dict(type='cut', why='your choice')), dict(seg(3, 22.0), transition=dict(type='dissolve', why='x')), dict(seg(4, 40.0), transition=dict(type='cut', why='the same clip: a new view, not an effect')),
            dict(seg(5, 44.0, synthetic='x.mp4'), transition=dict(type='cut', why='the same clip: a new view, not an effect'))]
    fr = {s['id']: path(20.0 * i) for i, s in enumerate(segs)}; fr['w2'] = path(30.0); fr['w3'] = path(45.0); fr['w4'] = path(70.0); fr['w5'] = path(80.0); fr['w1'] = path(20.0); fr['w0'] = path(0.0)
    out, report = PN.apply_pans(segs, fr); assert [g['transition']['type'] for g in out] == ['cut', 'pan', 'cut', 'dissolve', 'cut', 'cut'] and segs[1]['transition']['type'] == 'cut'
    assert [r[0] for r in report] == ['w1', 'w4'] and 'glide' in report[0][1] and 'consecutive' in report[1][1]                                                      # w4 follows a gap in the clip; the user's choice, the dissolve and the generated clip are not examined
    off, rep = PN.apply_pans(segs, fr, enabled=False); assert [g['transition']['type'] for g in off] == ['cut', 'cut', 'cut', 'dissolve', 'cut', 'cut'] and rep == []


class FakeSource:
    def __init__(self): self.calls = []
    def frames(self, k, a0, a1, yaw_extra=None, pose_extra=None):
        self.calls.append((k, a0, a1, None if pose_extra is None else np.array(pose_extra)))
        for i in range(a1 - a0): yield np.full((2, 2, 3), 10 * k + 1, np.uint8)


def test_the_film_renders_a_pan_as_the_end_of_the_first_shot_then_the_start_of_the_second_with_offsets_that_glide_between_their_poses():
    fps = 10.0; a, b = seg(0, 10.0, 4.0), seg(1, 14.0, 4.0); tr, _ = PN.plan(a, b, path(0.0), path(30.0, pitch=5.0, fov=100.0))
    segs = [dict(a, film_start_s=0.0, transition=dict(type='cut', beats=0, dur_s=0.0)), dict(b, film_start_s=4.0, transition=tr)]; ps = FI.pieces(segs, fps)
    kinds = [p['kind'] for p in ps]; assert kinds == ['plain', 'pan', 'plain'] and sum(p['frames'] for p in ps) == 80 and ps[1]['frames'] == 2 * round(tr['dur_s'] * fps / 2)
    src = FakeSource(); out = []; total = FI.compose(segs, src, fps, out.append); assert total == 80 and len(out) == 80; hout = ps[1]['hout']
    first, second = [c for c in src.calls if c[3] is not None]; assert (first[0], first[1], first[2]) == (0, 40 - hout, 40) and (second[0], second[1], second[2]) == (1, 0, hout) and first[3].shape == (hout, 4) and second[3].shape == (hout, 4)
    assert abs(first[3][0][0]) < 2.0 and np.all(np.diff(first[3][:, 0]) >= -1e-9) and first[3][-1][0] < 30.0 and second[3][0][0] > -30.0 and abs(second[3][-1][0]) < 2.0 and np.all(np.diff(second[3][:, 0]) >= -1e-9)      # the first half moves towards the second's pose, the second half arrives
    mid = first[3][-1][0] + 0.0; assert 8.0 < mid < 24.0 and second[3][0][0] < 0 and mid - second[3][0][0] == pytest.approx(30.0, abs=6.0)                                                          # the two halves meet where the camera has done about half the glide (yaw offsets of opposite signs)
    assert second[3][-1][1] == pytest.approx(0.0, abs=1.0) and first[3][-1][2] > 3.0                                                                                                            # pitch and field of view glide too


def test_the_framing_records_where_the_subject_is_for_the_glides():
    lib = TQ.load(); you = [dict(t=8.0 + k, yaw=200.0, pitch=-5.0, height=50.0, head=8.0, who='you', speaking=False) for k in range(10)]
    p = FR.resolve_segment(dict(id='c@10', clip='c', clip_start_s=10.0, dur_s=4.0, technique='selfie_close', variant_seed=1), lib, dict(person=[], you=you, heading=lambda t: 30.0, speakers=[]))
    assert p['subject'] == 'you' and p['track'][0]['t'] == 0.0 and p['track'][-1]['t'] == 4.0 and abs(p['track'][0]['yaw'] - 200.0) < 1.0 and p['track'][0]['pitch'] == pytest.approx(-5.0, abs=0.1)


def test_a_change_between_the_mid_and_far_view_of_you_is_a_gentle_glide_that_takes_longer_for_the_bigger_zoom():
    mid_far, _ = PN.plan(seg(0, 10.0), seg(1, 14.0), path(0.0, fov=85.0), path(0.0, fov=130.0, pitch=2.0)); small, _ = PN.plan(seg(0, 10.0), seg(1, 14.0), path(0.0, fov=85.0), path(0.0, fov=100.0, pitch=2.0))
    assert mid_far is not None and small is not None and mid_far['dur_s'] > small['dur_s'] and mid_far['dur_s'] <= PN.MAX_S and 1.5 * 45 / mid_far['dur_s'] <= PN.MAX_ZOOM_RATE
    assert 'too big a move' in PN.plan(seg(0, 10.0), seg(1, 14.0), path(0.0, fov=50.0), path(0.0, fov=130.0))[1]                                                                        # 80 degrees of zoom is too much


class Recorder:
    def __init__(self): self.fov = []; self.dirs = []
    def set_background(self, *a, **k): pass
    def set_fov(self, fov, dist=0.0, disc=None): self.fov.append(fov)
    def render(self, fr, vdir, up, roll): self.dirs.append(np.array(vdir)); return np.zeros((4, 4, 3), np.uint8)


class Dec:
    def __init__(self): import io; self.stdout = io.BytesIO(bytes(64 * 32 * 3 * 40))
    def terminate(self): pass
    def wait(self): pass


def test_the_previews_pose_offsets_are_degrees_added_to_the_cameras_radians(monkeypatch):
    from strata360.render import preview as PV, camera as cam
    sg = dict(id='w0', clip='c', clip_start_s=1.0, dur_s=2.0); src = PV.PreviewSource('x', [sg], {'w0': path(0.0, fov=90.0)}, 64, 32, 64); src.V = Recorder()
    src.info['c'] = dict(proxy='p.mp4', side=dict(frames=[dict(t_s=0.04 * i, source_frame=i) for i in range(100)], size=[64, 32]), ts=None, stab=None); monkeypatch.setattr(PV.guard, 'popen', lambda *a, **k: Dec())
    list(src.frames(0, 0, 3)); base = list(src.V.dirs); src.V.dirs.clear(); src.V.fov.clear()
    list(src.frames(0, 0, 3, pose_extra=np.array([[10.0, 5.0, 20.0, 0.0]] * 3))); assert np.allclose(src.V.fov, 110.0) and np.allclose(src.V.dirs[0], cam.direction(np.radians(10.0), np.radians(5.0))) and np.allclose(base[0], cam.direction(0.0, 0.0))


def globe_path(): return dict(ref='world', bg='blur', subject='heading', keyframes=[dict(t=0, yaw=0.0, pitch=-90, disc=3.2), dict(t=4.0, yaw=90.0, pitch=-90, disc=0.46)])


def test_a_globe_shot_glides_to_and_from_a_flat_one_as_a_globe_all_the_way():
    tr, why = PN.plan(seg(0, 0.0), seg(1, 4.0), globe_path(), path(0.0, pitch=-10.0)); assert tr and tr['globe'] and tr['dur_s'] <= 1.4
    first, second = FI.pan_extras(tr, 120, 15, 30.0)
    assert first.shape == (15, 4) and (first[:, 3] > 0).all() and (second[:, 3] > 0).all()
    assert first[0, 3] < 1.0 and abs(second[-1, 3] - 4.0) < 0.7                                              # a small planet at first, the flat 90 degree view's equivalent radius (4) at the end
    assert PN.plan(seg(0, 0.0), seg(1, 4.0), path(0.0, pitch=-10.0), globe_path())[0]['globe']
    assert PN.plan(seg(0, 0.0), seg(1, 4.0), dict(globe_path(), keyframes=[dict(t=0, yaw=0.0, pitch=-90, disc=3.2), dict(t=4.0, yaw=250.0, pitch=-90, disc=0.46)]), path(0.0, pitch=60.0))[0] is None
    flat = FI.pan_extras(PN.plan(seg(0, 0.0), seg(1, 4.0), path(0.0), path(20.0))[0], 120, 15, 30.0); assert (flat[0][:, 3] == 0).all()


def test_a_glide_whose_middle_shows_mostly_sky_is_refused_and_a_good_one_keeps_its_score():
    good = lambda y, p, f, t: 0.6
    sky = lambda y, p, f, t: 0.6 if abs(y) < 1 or abs(y - 20) < 1 else 0.05                     # the ends look fine, everything between is sky
    a, b = path(0.0, pitch=0.0), path(20.0, pitch=0.0)
    tr, why = PN.plan(seg(0, 0.0), seg(1, 4.0), a, b, good); assert tr and tr['look'] == 0.6
    assert PN.plan(seg(0, 0.0), seg(1, 4.0), a, b, sky)[0] is None and 'poor views' in PN.plan(seg(0, 0.0), seg(1, 4.0), a, b, sky)[1]
    assert PN.plan(seg(0, 0.0), seg(1, 4.0), globe_path(), path(0.0, pitch=-10.0), lambda y, p, f, t: 0.02 if abs(p + 50) < 30 else 0.5)[0] is None            # a globe glide is judged the same way
    assert PN.plan(seg(0, 0.0), seg(1, 4.0), a, b, lambda *x: None)[0]                                                                                      # no grid for the clip: not judged
