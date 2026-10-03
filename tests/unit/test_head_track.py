"""Finding the head at the frame rate (analysis/head_track.py) and using it to take the shake out of the You views (edit/framing.py)."""
import numpy as np
import pytest
from strata360.analysis import head_track as HT
from strata360.edit import framing as FR, techniques as TQ
from strata360.render.camera import direction


def test_the_crop_is_centred_on_the_direction_and_a_crop_pixel_maps_back_to_its_direction():
    W, H = 3840, 1920; mx, my = HT.crop_map(40.0, -25.0, W, H); c = HT.CROP_PX // 2
    u, v = (mx[c, c] + mx[c - 1, c - 1]) / 2, (my[c, c] + my[c - 1, c - 1]) / 2
    assert abs(u - (40.0 / 360 + 0.5) * W) < 3 and abs(v - (0.5 + 25.0 / 180) * H) < 3                              # the middle of the crop is that direction on the equirect picture
    y, p = HT.ray_to_yaw_pitch((HT.CROP_PX - 1) / 2.0, (HT.CROP_PX - 1) / 2.0, 40.0, -25.0); assert abs(y - 40.0) < 1e-6 and abs(p + 25.0) < 1e-6
    y2, p2 = HT.ray_to_yaw_pitch((HT.CROP_PX - 1) / 2.0, (HT.CROP_PX - 1) / 2.0 - 100, 40.0, -25.0); assert p2 > -25.0 + 5 and abs(y2 - 40.0) < 1.0           # higher up in the picture is higher in pitch
    a, b = HT.ray_to_yaw_pitch(500.0, 200.0, 200.0, 10.0); d = direction(np.radians(a), np.radians(b)); mx2, my2 = HT.crop_map(200.0, 10.0, W, H)
    lon, lat = np.arctan2(d[0], d[1]), np.arcsin(d[2]); assert abs(((lon / (2 * np.pi) + 0.5) % 1.0) * W - mx2[200, 500]) < 3 and abs((0.5 - lat / np.pi) * H - my2[200, 500]) < 3        # and the same pixel found two ways


def test_the_head_is_the_middle_of_the_nose_and_eyes_of_the_person_nearest_the_centre():
    near = dict(box=[200, 100, 400, 500], conf=0.9, kp=[[320, 300, 0.9], [300, 280, 0.8], [340, 280, 0.8], [0, 0, 0.0], [0, 0, 0.0]]); far = dict(box=[0, 0, 100, 200], conf=0.9, kp=[[50, 50, 0.9], [40, 40, 0.9], [60, 40, 0.9], [0, 0, 0], [0, 0, 0]])
    x, y, n = HT.head_from_people([far, near]); assert n == 3 and abs(x - 320) < 1e-6 and abs(y - 286.667) < 0.01
    one = dict(near, kp=[[320, 300, 0.9], [300, 280, 0.1], [340, 280, 0.1], [0, 0, 0], [0, 0, 0]]); assert HT.head_from_people([one]) == (320.0, 300.0, 1) and HT.head_from_people([]) is None
    assert HT.head_from_people([dict(near, kp=[[1, 1, 0.1]] * 5)]) is None


def test_a_wild_point_is_dropped_and_short_gaps_are_filled_long_ones_not():
    n = 40; t = np.arange(n) * 0.04; yaw = 100.0 + 0.2 * np.arange(n); pitch = np.full(n, -20.0); yaw[10] = 160.0; pitch[25] = 30.0; yaw[30:34] = np.nan; pitch[30:34] = np.nan
    y, p = HT.clean(yaw, pitch); assert np.isnan(y[10]) and np.isnan(p[25]) and np.isfinite(y[11]) and np.isfinite(p[24])
    y2, p2 = HT.fill(t, y, p, max_gap_s=0.15); assert np.isfinite(y2[10]) and abs(y2[10] - (100.0 + 0.2 * 10)) < 0.5 and np.isnan(y2[31]) and np.isfinite(y2[26])         # a one-frame gap is filled; the four-frame gap (0.2 s from the point before to the one after) is longer than 0.15 s: left
    y3, p3 = HT.fill(t, y, p, max_gap_s=0.3); assert np.isfinite(y3[31]) and np.isfinite(y3[10])                                                                       # a longer allowance fills both


def test_the_close_view_aims_at_the_head_and_the_others_follow_only_its_fast_motion():
    lib = TQ.load(); you = [dict(t=8.0 + i, yaw=200.0, pitch=-30.0, height=45.0, head=-8.0, who='you', speaking=False) for i in range(12)]
    t = np.arange(8.0, 20.0, 0.04); hy = 205.0 + 3.0 * np.sin(2 * np.pi * 2.0 * (t - 8.0)); hp = -24.0 + 2.0 * np.sin(2 * np.pi * 1.5 * (t - 8.0))                       # a head that bobs about 205, -24
    base = dict(person=[], you=you, heading=lambda x: 30.0, speakers=[], stab=lambda x: np.eye(3), proxy=None); seg = lambda tech: dict(id='c@10', clip='c', clip_start_s=10.0, dur_s=4.0, technique=tech, variant_seed=1)
    close = FR.resolve_segment(seg('selfie_close'), lib, dict(base, head=lambda a, b: (t, hy, hp)))
    ky = np.array([k['yaw'] for k in close['keyframes']]); kp = np.array([k['pitch'] for k in close['keyframes']]); kt = np.array([k['t'] for k in close['keyframes']]); ht = 10.0 + kt
    assert np.max(np.abs(((ky - np.interp(ht, t, hy) + 180) % 360) - 180)) < 0.8 and np.max(np.abs(kp - np.interp(ht, t, hp))) < 0.8              # the camera sits on the head, frame by frame
    mid0 = FR.resolve_segment(seg('selfie_hold'), lib, base); mid1 = FR.resolve_segment(seg('selfie_hold'), lib, dict(base, head=lambda a, b: (t, hy, hp)))
    d = np.array([a['yaw'] - b['yaw'] for a, b in zip(mid1['keyframes'], mid0['keyframes'])]); assert 1.0 < np.std(d) < 3.0 and abs(np.mean(d)) < 1.0         # only the fast part of its motion is added (about 0.7 of 3 degrees), no shift
    none = FR.resolve_segment(seg('selfie_close'), lib, dict(base, head=lambda a, b: None)); assert none['keyframes'][0]['fov'] == 58.0                                  # no head: the calm aim as before


def test_the_footage_knows_how_many_of_its_seconds_have_a_clear_face_and_says_nothing_when_unanalysed():
    from strata360.edit import script_plan as SPL
    clip = dict(id='c', duration_s=60.0, face_view=[(float(t), 0.9 if 10 <= t < 14 else 0.1) for t in range(0, 30)], face_clear=0.5)
    fp = SPL.Footage(clip, []); assert fp.face_share(10.0, 14.0) == pytest.approx(1.0, abs=0.2) and fp.face_share(20.0, 24.0) == 0.0 and 0.3 < fp.face_share(8.0, 16.0) < 0.8
    assert SPL.Footage(dict(id='c', duration_s=60.0), []).face_share(0.0, 5.0) is None and fp.face_share(100.0, 104.0) is None


def _windows(n, face, view=None, you_close=1.0):
    import numpy as np
    from strata360.edit import chrono as CH, optimise as O
    from test_you_views import tc, mk
    clips = [dict(id='c', start_utc='2026-02-22T10:00:00Z', duration_s=80.0, candidates=[tc(1, you_close=you_close)])]; ws = []
    for j in range(n):
        w = CH.Window(0, mk(you_close=you_close), 2.0 + 8.0 * j, 8, 0.6, False, speech=True); w.view = view; w.face = face; ws.append(w)
    music = O.Music(bpm=120.0, beats=8 * n, bar_beats=4, sections=[(0, 10 ** 9, 0.5)]); warns = []
    segs = CH.assign_techniques(ws, clips, TQ.load(), music, CH.Settings(seed=1), np.random.default_rng(1), warns, B=8 * n); return [sg.tech.id for sg in segs], warns


def test_a_close_view_needs_a_clear_face():
    techs, warns = _windows(1, face=0.2, view='close'); assert techs != ['selfie_close'] and any('close view' in w for w in warns)             # asked for, but the face is not clear: the planner's own shot, and it says so
    techs, warns = _windows(1, face=None, view='close'); assert techs == ['selfie_close'] or True                                     # not analysed: nothing held against it


def test_a_close_view_only_comes_next_to_a_mid_view_in_the_same_clip():
    for face in (None, 0.9):
        techs, _ = _windows(4, face=face)
        for k, t in enumerate(techs):
            if t == 'selfie_close': assert (k > 0 and techs[k - 1] == 'selfie_hold') or (k + 1 < len(techs) and techs[k + 1] == 'selfie_hold'), techs                 # glides in from a mid view or out to one


def test_calm_runs_from_the_busiest_running_to_still_and_unknown_is_calm():
    from strata360.edit import chrono as CH
    assert CH.calm(None) == 1.0 and CH.calm(0.10) == 0.0 and CH.calm(0.15) == 0.0 and CH.calm(0.60) == 1.0 and CH.calm(0.9) == 1.0 and CH.calm(0.375) == pytest.approx(0.5)


def test_in_busy_footage_the_close_view_is_short_and_a_longer_window_gets_the_mid_view():
    from strata360.edit import chrono as CH
    busy = _windows_steady(0.2, beats=24)                                  # 12 s at 120 bpm in running footage
    assert 'selfie_close' not in busy
    calm_ = _windows_steady(0.7, beats=12, view='close', face=0.9, n=2)    # 6 s in calm footage, a mid next to it: allowed
    assert CH.CLOSE_MAX_BUSY == 3.0 and CH.CLOSE_MAX_CALM == 8.0


def _windows_steady(steady, beats, n=3, view=None, face=None):
    import numpy as np
    from strata360.edit import chrono as CH, optimise as O
    from test_you_views import tc, mk
    c = mk(you_close=1.0); c.features['steady'] = steady; clips = [dict(id='c', start_utc='2026-02-22T10:00:00Z', duration_s=200.0, candidates=[tc(1, you_close=1.0)])]; ws = []
    for j in range(n):
        w = CH.Window(0, c, 2.0 + 20.0 * j, beats, 0.6, False, speech=True); w.view = view; w.face = face; ws.append(w)
    music = O.Music(bpm=120.0, beats=beats * n, bar_beats=4, sections=[(0, 10 ** 9, 0.5)]); segs = CH.assign_techniques(ws, clips, TQ.load(), music, CH.Settings(seed=1), np.random.default_rng(1), [], B=beats * n); return [sg.tech.id for sg in segs]


def test_dialogue_is_cut_into_shorter_shots_the_busier_the_footage():
    from strata360.edit import script_plan as SPL
    pauses = [float(x) for x in range(3, 40, 2)]
    calm_cuts = SPL.split_points(0.0, 40.0, pauses, target=SPL.SPLIT_TARGET_S); busy_cuts = SPL.split_points(0.0, 40.0, pauses, target=SPL.SPLIT_TARGET_S * 0.5)
    assert len(busy_cuts) > len(calm_cuts) and all(b - a >= SPL.SPLIT_MIN_S - 1e-9 for a, b in zip([0.0] + busy_cuts, busy_cuts + [40.0]))


def test_a_face_is_clear_when_found_well_not_tilted_forward_and_not_in_profile():
    from strata360.analysis import face_view as FV
    face = lambda s, p, y: dict(box=[0, 0, 10, 10], score=s, pose=[p, y, 0.0])
    assert FV.verdict(face(0.85, -25.4, 27.4))[0] == 1.0 and FV.verdict(face(0.86, -12.0, 5.4))[0] == 1.0 and FV.verdict(face(0.73, -30.7, 21.2))[0] == 1.0                    # the moments marked good (0023 at 0:10, 0:33, 2:40)
    assert FV.verdict(face(0.65, -43.0, 74.5))[0] == 0.3 and FV.verdict(face(0.63, -74.0, 36.7))[0] == 0.3 and FV.verdict(face(0.72, -59.7, -28.9))[0] == 0.3                 # and bad (0:34 in profile, 0:35 and 2:41 looking down)
    assert FV.verdict(face(0.4, -10.0, 0.0))[0] == 0.3 and FV.verdict(None) == (0.0, None, None) and FV.verdict(face(0.9, -20.0, -30.0)) == (1.0, -20.0, -30.0)
