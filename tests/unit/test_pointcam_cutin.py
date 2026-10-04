"""A point camera as an option for the planner: a technique `cam:C1` for the windows inside its stretch, b-roll taken over the place, no duplicate of a camera that is a shot of its own, the framing, and glides to and from the neighbouring shots."""
import datetime as dt

import numpy as np
import pytest

import test_script_plan as TSP
from overlay_fakes import race_track, T0
from strata360.edit import chrono as CH, framing as FR, pans as PN, pointcam as PC, pointcam_clip as PCL, script_plan as SPL, techniques as TQ

C1ID = TSP.C1['id']


def cam_doc(clip=C1ID, t0=30.0, t1=45.0, **kw):
    t = np.arange(t0, t1 + 1e-9, 0.5); n = len(t)
    d = dict(id='C1', clip=clip, name='the old mill', t0=t0, t1=t1, t_pass=(t0 + t1) / 2, t=[float(x) for x in t], yaw=[float(x) for x in np.linspace(-40, 60, n)], pitch=[-3.0] * n, fov=[float(x) for x in np.linspace(90, 60, n)], min_dist_m=22.0); d.update(kw); return d


@pytest.fixture
def lib(monkeypatch):
    monkeypatch.setattr(PCL, 'cutins', lambda folder, tr=None: [cam_doc()]); return TQ.with_cams(TSP.LIB, 'x')


def run(lib, draft=TSP.DRAFT, pack=TSP.PACK):
    return SPL.build(draft, pack, [TSP.C1, TSP.C2], lib, TSP.MUSIC, TSP.VOICE, st=CH.Settings(seed=1))


class TestTechnique:
    def test_each_possible_clip_camera_is_a_technique_of_its_own(self, lib):
        t = lib['cam:C1']; assert t.family == 'pointcam' and t.cam['clip'] == C1ID and t.dur == (2.0, 5.0, 15.0) and not t.hero and not t.dialogue_ok and t.needs == {} and 'cam:C1' not in TSP.LIB
        assert set(TSP.LIB) < set(lib) and TQ.validate(lib)

    def test_a_stretch_under_two_seconds_or_a_failing_project_adds_nothing(self, monkeypatch):
        monkeypatch.setattr(PCL, 'cutins', lambda folder, tr=None: [cam_doc(t0=30.0, t1=31.0)]); assert TQ.with_cams(TSP.LIB, 'x') == TSP.LIB
        def boom(folder, tr=None): raise OSError('no such project')
        monkeypatch.setattr(PCL, 'cutins', boom); assert TQ.with_cams(TSP.LIB, 'x') is TSP.LIB

    def test_the_planners_cameras_are_the_possible_ones_on_clips_with_their_path_in_clip_seconds(self, project, monkeypatch):
        t = race_track(n=600, speed=3.0, lat0=50.13, lon0=5.79); monkeypatch.setattr(PCL, '_track', lambda folder: t)
        project.add_clip('c1', start_utc=dt.datetime.fromtimestamp(T0 + 100, dt.timezone.utc).isoformat(), source_frames=3000, fps=30.0); rd = project.race_dir
        lat, lon = 50.13 + 450.0 / 111_195.0, 5.79 + 25.0 / (111_195.0 * np.cos(np.radians(50.13)))
        a = PC.create(rd, dict(kind='clip', clip='c1'), lat, lon, T0 + 150.0, use='possible', name='mill'); PC.create(rd, dict(kind='clip', clip='c1'), lat, lon, T0 + 150.0, use='must'); PC.create(rd, dict(kind='clip', clip='c1'), lat, lon, T0 + 150.0)
        PC.create(rd, dict(kind='streetview', key='k'), lat, lon, T0 + 150.0, use='possible')
        (c,) = PCL.cutins(project.folder); assert c['id'] == a['id'] and c['clip'] == 'c1' and c['name'] == 'mill'                  # (a must one is its own shot; a street view one can only be a generated clip)
        assert c['t0'] == pytest.approx(50.0 - 40 / 3.0, abs=1.5) and c['t_pass'] == pytest.approx(50.0, abs=1.0) and c['t1'] == pytest.approx(50.0 + 40 / 3.0, abs=1.5)          # 40 m each side at 3 m/s and len(c['t']) == len(c['yaw']) == len(c['pitch']) == len(c['fov']) and np.all(np.abs(np.diff(c['yaw'])) < 90)
        assert c['min_dist_m'] == pytest.approx(25.0, abs=2.0)


class TestWindows:
    def test_a_window_must_lie_inside_the_stretch_give_or_take_a_beat(self, lib):
        t = lib['cam:C1']; fits = lambda clip, a, d: CH.cam_fits(t, clip, a, d)
        assert fits(C1ID, 32.0, 4.0) and fits(C1ID, 30.0, 15.0) and fits(C1ID, 41.0, 4.4) and not fits(C1ID, 25.0, 4.0) and not fits(C1ID, 44.0, 4.0) and not fits(TSP.C2['id'], 32.0, 4.0)

    def test_broll_of_a_clip_with_a_camera_is_taken_over_the_place_and_the_planner_cuts_to_the_camera(self, lib):
        draft = dict(wpm=150, items=[TSP.item('broll', 1, seconds=4.0), TSP.item('broll', 2, seconds=4.0)]); res = run(lib, draft); segs = [s for s in res['segs'] if s.cand.clip == C1ID]
        assert len(segs) == 1 and segs[0].tech.id == 'cam:C1' and 30.0 - 0.5 <= segs[0].clip_start_s and segs[0].clip_start_s + segs[0].beats * TSP.BEAT <= 45.0 + 0.5           # the window is inside the stretch, round the closest approach (37.5 s)
        assert abs(segs[0].clip_start_s + segs[0].beats * TSP.BEAT / 2 - 37.5) < 1.0
        assert {o['tech'] for s in res['segs'] for o in s.parts['options'] if s.cand.clip == TSP.C2['id']}.isdisjoint({'cam:C1'})                                             # (a window of another clip never offers it)
        plain = run(TSP.LIB, draft); assert all(s.tech.id != 'cam:C1' for s in plain['segs'])

    def test_a_camera_with_no_room_in_the_footage_is_just_not_used(self, monkeypatch):
        monkeypatch.setattr(PCL, 'cutins', lambda folder, tr=None: [cam_doc(t0=200.0, t1=215.0)]); lib = TQ.with_cams(TSP.LIB, 'x'); res = run(lib, dict(wpm=150, items=[TSP.item('broll', 1, seconds=4.0)]))
        assert all(s.tech.id != 'cam:C1' for s in res['segs'])

    def test_a_camera_that_is_a_shot_of_its_own_is_not_cut_in_as_well(self, lib):
        syn = dict(label='C1', clip='C1', duration_s=6.0, usable_s=10.0, usable=[(2.0, 10.0)], scene={}, note='', lines=[], synthetic=True, camera=True, start_utc='2026-02-22T10:01:30Z', cam_facts=dict(min_s=2.0, max_s=10.0), settings={})
        pack = dict(TSP.PACK, clips=TSP.PACK['clips'] + [syn]); draft = dict(wpm=150, items=[TSP.item('broll', 1, seconds=4.0), dict(type='camera', clip='C1', seconds=6.0), TSP.item('broll', 2, seconds=4.0)])
        res = run(lib, draft, pack); assert [p['label'] for p in res['pieces'] if p['kind'] == 'synthetic'] == ['C1'] and all(s.tech.id != 'cam:C1' for s in res['segs'])

    def test_the_old_planner_does_not_offer_a_camera_to_footage_it_does_not_cover(self, lib):
        from strata360.edit import optimise as O
        c = O.Candidate(id='a', clip='c', quality=0.5, energy=0.5, min_dur=1.0, max_dur=10.0, features=TSP.feats()); A = O.option_table([c], lib, O.Music(bpm=120, beats=64, bar_beats=4, sections=[(0, 64, 0.5)]), O.Settings())
        assert 'cam:C1' in A['tech_ids'] and 'cam:C1' not in {A['tech_ids'][i] for i in A['t']}


class TestFraming:
    def g(self, a, T, tech='cam:C1'): return dict(technique=tech, clip=C1ID, clip_start_s=a, dur_s=T, variant_seed=0)

    def test_the_window_gets_the_cameras_path_for_its_seconds(self, lib):
        p = FR.resolve_segment(self.g(33.0, 4.0), lib, {}); kf = p['keyframes']
        assert p['ref'] == 'world' and p['subject'] == 'camera' and 'point camera C1 (the old mill)' in p['why'] and kf[0]['t'] == 0.0 and kf[-1]['t'] == 4.0 and all(k['ease'] == 'linear' for k in kf)
        assert kf[0]['yaw'] == pytest.approx(-40 + 100 * 3.0 / 15.0, abs=0.1) and kf[-1]['yaw'] == pytest.approx(-40 + 100 * 7.0 / 15.0, abs=0.1) and kf[0]['fov'] == pytest.approx(90 - 30 * 3.0 / 15.0, abs=0.1)
        held = FR.resolve_segment(self.g(44.0, 2.0), lib, {})['keyframes']; assert held[-1]['yaw'] == pytest.approx(60.0, abs=0.1)         # (a window running past the end holds the last pose)

    def test_a_camera_taken_away_since_the_plan_was_made_is_a_plain_wide_shot(self, lib):
        gone = dict(self.g(33.0, 4.0, 'cam:C9')); p = FR.resolve_segment(gone, TSP.LIB, dict(heading=lambda t: 10.0, quality=None, person=[], you=[], speakers=[], views=None, stab=None, proxy=None, head=None))
        assert p['subject'] == 'heading' and all(k['fov'] == 100 for k in p['keyframes'])


class TestGlides:
    def test_the_planner_hopes_for_a_glide_to_or_from_a_camera_and_the_real_path_decides(self, lib):
        assert PN.glide_pair('cam:C1', 'scenery') and PN.glide_pair('free_view', 'cam:C1') and not PN.glide_pair('cam:C1', 'cam:C1') and not PN.glide_pair('cam:C1', 'spin_roll')
        a = dict(clip=C1ID, clip_start_s=33.0, dur_s=4.0); pa = FR.resolve_segment(dict(a, technique='cam:C1', variant_seed=0), lib, {}); end = pa['keyframes'][-1]
        near = dict(ref='world', keyframes=[dict(t=0.0, yaw=end['yaw'] + 30.0, pitch=0.0, fov=100.0, ease='linear'), dict(t=3.0, yaw=end['yaw'] + 30.0, pitch=0.0, fov=100.0, ease='linear')], subject='free'); b = dict(clip=C1ID, clip_start_s=37.0, dur_s=3.0)
        res, why = PN.plan(a, b, pa, near); assert why is None and res['type'] == 'pan' and 0.6 <= res['dur_s'] <= 1.7                                     # a camera shot glides into the next shot of the clip like any other
        far = dict(near, keyframes=[dict(k, yaw=end['yaw'] + 120.0) for k in near['keyframes']]); res, why = PN.plan(a, b, pa, far); assert res is None and 'too big a move' in why
        res, why = PN.plan(b | dict(clip='other'), a, near, pa); assert res is None and 'not consecutive' in why
