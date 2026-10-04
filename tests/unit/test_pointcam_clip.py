"""Point cameras as pictures and in the film: the path a camera looks from, the shot, the pack, the script item, the plan, the clip."""
import datetime as dt
import json
import os

import numpy as np
import pytest

import test_script_plan as TSP
from overlay_fakes import race_track, T0
from strata360 import streetview as SV
from strata360.edit import pointcam as PC, pointcam_clip as PCL, script_draft as SD, script_pack as SP, script_plan as SPL, synthetic as SY, streetview_cam as CAM

M = 1 / 111_195.0                                  # degrees of latitude in a metre
CLIP_START = T0 + 100.0                            # the clip starts 100 s into the run and lasts 100 s


def iso(t): return dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


@pytest.fixture
def tr(monkeypatch):
    t = race_track(n=600, speed=3.0, lat0=50.13, lon0=5.79); monkeypatch.setattr(PCL, '_track', lambda folder: t); return t


@pytest.fixture
def proj(project, tr):
    project.add_clip('c1', start_utc=iso(CLIP_START), source_frames=3000, fps=30.0); return project


def point_east_of(metres_along, east_m):
    lat0, lon0 = 50.13, 5.79; return lat0 + metres_along * M, lon0 + east_m * M / np.cos(np.radians(lat0))


def make_cam(rd, source=None, along=450.0, east=25.0, **kw):
    lat, lon = point_east_of(along, east); return PC.create(rd, source or dict(kind='clip', clip='c1'), lat, lon, T0 + along / 3.0, **kw)


def sv_section(proj):
    """A 360 street view section along the run (40 pictures 10 m apart from 300 m on); returns its key."""
    rd = proj.race_dir; items = [dict(id='m%d' % i, km=0.3 + i * 0.01, lat=50.13 + (300 + 10 * i) * M, lon=5.79, a=0, b=0, t=1_700_000_000 + i) for i in range(40)]
    sec = dict(id='M1', provider='mapillary', stretch='R1', kind='360', km0=0.3, km1=0.69, length_m=390, frames=40, spacing_m=10.0, years=[2024], camera='GoPro Max', size=[5760, 2880], seq='s1', angles=None, items=items)
    roads = dict(schema=1, id='r', stretches=[], run=[], total_km=3); SV._save(rd, 'roads', roads); SV._save(rd, 'mapillary', SV.provider_doc('mapillary', [sec], roads)); key = SV.section_key(sec)
    return key

class TestSource:
    def test_a_clip_is_the_part_of_the_race_track_it_was_filmed_on(self, proj):
        p, bounds, extra = PCL.source_poly(proj.folder, dict(kind='clip', clip='c1'))
        assert bounds == (CLIP_START, CLIP_START + 100.0) and extra[1] == 100.0 and p['t'][0] >= CLIP_START - 15 and p['t'][-1] <= CLIP_START + 115 and len(p['t']) == 131
        with pytest.raises(ValueError, match='no clip nope'): PCL.source_poly(proj.folder, dict(kind='clip', clip='nope'))
        with pytest.raises(ValueError, match='unknown source'): PCL.source_poly(proj.folder, dict(kind='map'))

    def test_a_click_must_be_near_the_path(self, proj):
        p, bounds, _ = PCL.source_poly(proj.folder, dict(kind='clip', clip='c1')); lat, lon = point_east_of(450.0, 25.0)
        t, d = PCL.approach(p, lat, lon, bounds); assert t == pytest.approx(T0 + 150.0, abs=0.5) and d == pytest.approx(25.0, abs=1.0)
        with pytest.raises(ValueError, match='from the path'): PCL.approach(p, *point_east_of(450.0, 900.0), bounds)
        with pytest.raises(ValueError, match='from the path'): PCL.approach(p, *point_east_of(-300.0, 25.0), bounds)          # (outside the clip's own stretch the nearest point is the clip's edge: 600 m away)

    def test_a_street_view_section_is_the_path_of_its_pictures_timed_by_where_the_runner_was(self, proj):
        key = sv_section(proj); p, bounds, got = PCL.source_poly(proj.folder, dict(kind='streetview', key=key))
        assert len(p['t']) == 40 and bounds == (p['t'][0], p['t'][-1]) and p['t'][0] == pytest.approx(T0 + 100.0, abs=1.0) and p['t'][1] - p['t'][0] == pytest.approx(10 / 3.0, abs=0.1) and got['provider'] == 'mapillary'
        with pytest.raises(ValueError, match='not there any more'): PCL.source_poly(proj.folder, dict(kind='streetview', key='mapillary:x:9.9'))


class TestPlan:
    def test_the_shot_is_the_metres_either_side_of_the_closest_approach_and_looks_at_the_point(self, proj):
        cam = make_cam(proj.race_dir, before_m=30.0, after_m=60.0); pl = PCL.plan(proj.folder, cam)
        assert pl['t0'] == pytest.approx(T0 + 140.0, abs=0.5) and pl['t1'] == pytest.approx(T0 + 170.0, abs=0.5) and pl['seconds'] == pl['source_seconds'] == pytest.approx(30.0, abs=1.0)
        sm = pl['samples']; assert sm['dist'].min() == pytest.approx(25.0, abs=1.5) and pl['facts']['seconds'] == pytest.approx(30.0, abs=1.0) and pl['facts']['warnings'] == []

    def test_a_shorter_length_trims_the_shot_round_the_closest_approach(self, proj):
        cam = make_cam(proj.race_dir, before_m=60.0, after_m=60.0); whole = PCL.plan(proj.folder, cam); short = PCL.plan(proj.folder, cam, 10.0)
        assert short['seconds'] == pytest.approx(10.0, abs=0.1) and whole['t0'] < short['t0'] < cam['t_pass'] < short['t1'] < whole['t1']

    def test_the_clip_is_calibrated_to_the_compass_from_its_heading(self, proj):
        cam = make_cam(proj.race_dir); proj.write_json('clips/c1/motion.json', dict(series=dict(t=[0.0, 100.0], heading_deg=[30.0, 30.0])))       # the run goes north (0 degrees): the clip's frame has north at -30
        cj = json.load(open(proj.path('clips', 'c1', 'clip.json'))); cj['source_files'] = dict(osv='x.osv'); json.dump(cj, open(proj.path('clips', 'c1', 'clip.json'), 'w'))
        pl = PCL.plan(proj.folder, cam); assert pl['north_offset'] == pytest.approx(-30.0, abs=1.0)
        kf = PCL.clip_path(pl['samples'], 0.0, pl['north_offset'])['keyframes']; assert kf[0]['yaw'] == pytest.approx(pl['samples']['bearing'][0] + 30.0, abs=0.1)
        assert PCL.plan(proj.folder, cam)['north_offset'] == pytest.approx(-30.0, abs=1.0)

    def test_a_street_view_shot_is_played_in_the_length_asked_for(self, proj):
        key = sv_section(proj)
        cam = make_cam(proj.race_dir, source=dict(kind='streetview', key=key), along=450.0, east=25.0, before_m=100.0, after_m=100.0); pl = PCL.plan(proj.folder, cam, 6.0)
        assert pl['seconds'] == 6.0 and pl['source_seconds'] == pytest.approx(PC.MAX_S, abs=0.5) and PCL.plan(proj.folder, cam)['seconds'] == 8.0          # (200 m of road is 66 s of running: held to a minute) and 200 m at 25 m/s without a length
        assert PCL.range_of(cam, pl)[0] == PC.MIN_S and PCL.range_of(cam, pl)[1] == min(float(pl['extra']['max_s']), PC.MAX_S)

    def test_the_summary_says_why_a_camera_cannot_give_its_shot(self, proj):
        cam = make_cam(proj.race_dir); s = PCL.summary(proj.folder, cam)
        assert s['ok'] and s['range'] == [PC.MIN_S, s['source_seconds']] and len(s['geometry']['sights']) == 7 and s['geometry']['line'][0][0] < s['geometry']['line'][-1][0] and s['window'][0] < cam['t_pass'] < s['window'][1]
        assert PCL.summary(proj.folder, dict(cam, source=dict(kind='clip', clip='gone')))['ok'] is False


class TestTheFilm:
    def pack_clip(self, proj, tr, **kw):
        cam = make_cam(proj.race_dir, **kw); out = SP.camera_clips(proj.folder, tr, 'UTC'); return cam, out

    def test_only_offered_cameras_are_pack_clips_with_their_facts(self, proj, tr):
        cam = make_cam(proj.race_dir); assert SP.camera_clips(proj.folder, tr, 'UTC') == [] and SP.camera_clips(proj.folder, None, 'UTC') == []
        PC.update(proj.race_dir, 'C1', use='must', name='the old mill', seconds=12); (c,) = SP.camera_clips(proj.folder, tr, 'UTC'); f = c['cam_facts']
        assert c['label'] == 'C1' and c['synthetic'] and c['camera'] and c['settings']['must'] is True and c['settings']['seconds'] == 12.0 and c['duration_s'] == 12.0 and c['usable'] == [(PC.MIN_S, c['usable_s'])]
        assert f['name'] == 'the old mill' and f['source'] == 'clip c1' and f['min_s'] == PC.MIN_S and f['max_s'] == c['usable_s'] and f['min_dist_m'] == pytest.approx(25.0, abs=1.5) and 'km' in c['track']
        PC.update(proj.race_dir, 'C1', use='possible'); assert SP.camera_clips(proj.folder, tr, 'UTC')[0]['settings']['must'] is False
        PC.update(proj.race_dir, 'C1', use='possible', before_m=5)                                                                              # (the pack never fails for a camera that cannot be worked out)
        os.remove(proj.path('clips', 'c1', 'clip.json')); assert SP.camera_clips(proj.folder, tr, 'UTC') == []

    def test_the_prompt_tells_the_writer_what_the_camera_is(self, proj, tr):
        make_cam(proj.race_dir, use='must', name='the old mill'); (c,) = SP.camera_clips(proj.folder, tr, 'UTC')
        text = SP.render(dict(race={}, clips=[c], music=None), with_usable=False); assert '=== POINT CAMERA C1:' in text and 'the old mill' in text and 'camera item of 2 to' in text and 'MUST INCLUDE' in text and 'the runner says nothing' not in text
        assert '"camera": a shot' in SD.SYSTEM and '"type": "camera"' in SD.SCHEMA

    def pack(self, c): return dict(TSP.PACK, clips=[dict(x, start_utc=f'2025-09-16T06:0{i}:00Z') for i, x in enumerate(TSP.PACK['clips'])] + [c])

    def test_a_camera_item_is_checked_for_what_it_names_and_how_long(self, proj, tr):
        make_cam(proj.race_dir, use='must'); (c,) = SP.camera_clips(proj.folder, tr, 'UTC'); first = TSP.PACK['clips'][0]['label']; hi = c['usable_s']
        def check(items, c=c): return SD.check(dict(items=items), self.pack(c), 20.0, 150.0)
        rep, probs = check([dict(type='broll', clip=first, seconds=6), dict(type='camera', clip='C1', seconds=5)]); assert not [p for p in probs if p.startswith('item')] and rep['camera_s'] == 5.0 and rep['per_clip']['C1'] == 5.0
        assert any(f'C1 plays for 2 to {hi:g} seconds, not 1' in p for p in check([dict(type='camera', clip='C1', seconds=1)])[1]) and any(f'{first} is not a point camera' in p for p in check([dict(type='camera', clip=first, seconds=5)])[1])
        assert any('C1 is a camera with no words: use a camera item' in p for p in check([dict(type='clip', clip='C1', **{'from': 'x', 'to': 'y'})])[1]) and any('C1 is not a gap' in p for p in check([dict(type='gap', clip='C1', seconds=5)])[1])
        assert any('point camera C1 is marked MUST INCLUDE but no item uses it' in p for p in check([dict(type='broll', clip=first, seconds=8)])[1]) and not any('MUST INCLUDE' in p for p in check([dict(type='camera', clip='C1', seconds=5)])[1])
        assert SD.resolve(dict(items=[dict(type='camera', clip='C1', seconds=5.04)]), self.pack(c), 150.0)['items'][0]['seconds'] == 5.0

    def test_the_plan_places_a_camera_like_a_photo_and_adds_a_must_one_the_script_left_out(self, proj, tr):
        make_cam(proj.race_dir, use='must'); (c,) = SP.camera_clips(proj.folder, tr, 'UTC'); pack = self.pack(c); first = TSP.PACK['clips'][0]['label']
        ps, warn = SPL.pieces(dict(items=[dict(type='camera', clip='C1', seconds=5), dict(type='camera', clip=first, seconds=5), dict(type='gap', clip='C1', seconds=5)]), pack, {}, 150.0)
        assert [p['label'] for p in ps] == ['C1'] and ps[0]['camera'] and ps[0]['role'] == 'broll' and ps[0]['seconds'] == 5.0 and ps[0]['cam_range'] == (PC.MIN_S, c['usable_s']) and not ps[0].get('streetview') and len(warn) == 2
        assert SPL.flex(ps[0]) == (PC.MIN_S, c['usable_s'])                                                                     # (any length in what the shot can play)
        added = SPL.force_gaps([], pack, []); assert added == ['C1']
        ps2 = []; SPL.force_gaps(ps2, pack, []); assert ps2[0]['camera'] and ps2[0]['seconds'] == c['duration_s']

    def test_the_clip_is_made_once_for_the_plans_length_and_again_when_the_camera_changes(self, proj, tr, monkeypatch):
        make_cam(proj.race_dir, use='must'); made = []
        def fake_render(folder, cam, seconds, out, log=print): made.append((cam['id'], seconds)); os.makedirs(os.path.dirname(out), exist_ok=True); open(out, 'wb').write(b'v')
        monkeypatch.setattr(PCL, 'render', fake_render); specs = [dict(clip='C1', seconds=6.0), dict(clip='G03', seconds=4.0), dict(clip='V1', seconds=4.0)]
        (c,) = PCL.sync(proj.folder, specs); assert made == [('C1', 6.0)] and c['id'] == 'C1' and c['kind'] == 'pointcam' and c['status'] == 'ready' and c['seconds'] == 6.0 and c['file'] == os.path.join('synthetic', 'C1.mp4') and c['size'] == SY.POINTCAM_SIZE
        assert c['t0'] < iso(CLIP_START + 100) and c['duration_s'] == pytest.approx(6.0, abs=0.2)                                 # (a trimmed window: the part of the shot nearest the point)
        PCL.sync(proj.folder, specs); assert len(made) == 1                                                                     # unchanged: kept
        PCL.sync(proj.folder, [dict(clip='C1', seconds=8.0)]); assert made[-1] == ('C1', 8.0)
        PC.update(proj.race_dir, 'C1', fov_far=70); PCL.sync(proj.folder, [dict(clip='C1', seconds=8.0)]); assert len(made) == 3                                       # a changed camera is made again
        logs = []; PC.delete(proj.race_dir, 'C1'); assert PCL.sync(proj.folder, [dict(clip='C1', seconds=8.0)], logs.append) == [] and 'not there any more' in logs[0]
        assert [x['id'] for x in SY.load(proj.folder)['clips']] == ['C1']

    def test_the_credits_name_a_street_view_provider_but_not_the_runners_own_clip(self, proj, monkeypatch):
        from strata360.edit import credits as CR, project as PJ
        a = SY.make_pointcam(dict(PC.DEFAULTS, id='C1', source=dict(kind='clip', clip='c1'), lat=50.0, lon=5.0, t_pass=1.0), 5.0, T0, T0 + 30); b = SY.make_pointcam(dict(PC.DEFAULTS, id='C2', source=dict(kind='streetview', key='k'), lat=50.0, lon=5.0, t_pass=1.0), 5.0, T0, T0 + 30, provider='google')
        assert a['key'] != b['key'] and b['style']['provider'] == 'google' and a['kind'] == 'pointcam' and a['duration_s'] == 30.0 and a['speedup'] == 6.0
        for c in (a, b): SY.upsert(proj.folder, dict(c, status='ready'))
        monkeypatch.setattr(PJ, 'load', lambda folder: dict(plan=dict(segments=[dict(synthetic='x', clip='C1'), dict(synthetic='y', clip='C2')]), settings={}))
        rows = CR.needed(proj.folder); assert [t for what, t in rows if 'C2' in what] == ['Street-level imagery: © Google'] and not any('C1' in what for what, t in rows)
        with pytest.raises(ValueError, match='shorter'): SY.make_pointcam(dict(PC.DEFAULTS, id='C1', source={}, lat=0, lon=0, t_pass=0), 1.0, 0, 5)


class FakeEncoder:
    """Stands in for the ffmpeg process a render pipes its frames to."""
    made = []
    def __init__(self, cmd, **kw): self.cmd, self.frames, self.returncode = cmd, [], 0; FakeEncoder.made.append(self); self.stdin = self
    def write(self, b): self.frames.append(len(b))
    def close(self): pass
    def wait(self): return 0


class TestStreetViewShot:
    def test_each_frame_looks_at_the_point_blending_the_two_pictures_it_falls_between(self, tmp_path, monkeypatch):
        calls = []; img = np.zeros((20, 40, 3), np.uint8)
        rig = CAM.Rig([dict(id=str(i)) for i in range(4)], np.arange(4) * 10.0, np.zeros(4), None, rot=lambda i, y, p: calls.append(('rot', i, y, p)) or np.eye(3), img=lambda i: img)
        monkeypatch.setattr(CAM, 'build', lambda *a, **k: rig); monkeypatch.setattr(CAM, 'reproject', lambda im, R, f, size: calls.append(('view', f)) or np.full((size[1], size[0], 3), 7, np.uint8)); monkeypatch.setattr(CAM, 'flow_blend', lambda A, B, a: A)
        monkeypatch.setattr(CAM.subprocess, 'Popen', FakeEncoder); FakeEncoder.made.clear(); out = str(tmp_path / 'o.mp4'); monkeypatch.setattr(CAM.os, 'replace', lambda a, b: open(b, 'wb').write(b'x')); logs = []
        r = CAM.render_point('rd', dict(id='M1'), np.array([0.0, 0.5, 1.5, 2.99]), [10.0, 20.0, 30.0, 400.0], [-3.0, 0.0, 0.0, 5.0], [50.0, 60.0, 70.0, 80.0], out, size=(32, 18), log=logs.append)
        assert r == dict(frames=4, fps=30) and len(FakeEncoder.made[0].frames) == 4 and set(FakeEncoder.made[0].frames) == {32 * 18 * 3}
        rots = [c for c in calls if c[0] == 'rot']; assert rots[0] == ('rot', 0, 10.0, -3.0) and ('rot', 1, 20.0, 0.0) in rots and any(c[2] == 400 % 360 for c in rots) and [c[1] for c in calls if c[0] == 'view'][:2] == [50.0, 60.0] and 'rendering 4 of 4 frames' in logs[-2]
        flat = CAM.Rig([dict(id='0')] * 8, np.arange(8.0), np.zeros(8), lambda i, y: img); monkeypatch.setattr(CAM, 'build', lambda *a, **k: flat)
        with pytest.raises(ValueError, match='only a 360 section'): CAM.render_point('rd', dict(id='M2'), [0.0], [0.0], [0.0], [60.0], out)


class TestAim:
    """Where the camera looks over time, for the page to draw over a playing video."""
    def test_a_clips_aim_is_its_path_in_the_clips_own_frame_and_seconds(self, proj):
        cam = make_cam(proj.race_dir, before_m=30, after_m=30); pl = PCL.plan(proj.folder, cam); a = PCL.aim_path(proj.folder, cam)
        assert a['kind'] == 'world' and len(a['t']) == len(a['yaw']) == len(a['pitch']) == len(a['fov']) == len(a['on']) and all(a['on']) and a['t'][0] == pytest.approx(pl['t0'] - (T0 + 100.0), abs=0.01) and a['t'][-1] - a['t'][0] == pytest.approx(pl['seconds'], abs=0.2)
        assert a['yaw'][0] == pytest.approx(pl['samples']['bearing'][0] - pl['north_offset'], abs=0.01) and np.all(np.abs(np.diff(a['yaw'])) < 90)
        with pytest.raises(ValueError, match='not a clip'): PCL.aim_path(proj.folder, cam, 'pano')

    def sv(self, proj, monkeypatch, hs=None):
        key = sv_section(proj); cam = make_cam(proj.race_dir, source=dict(kind='streetview', key=key), along=450.0, east=25.0, before_m=100.0, after_m=100.0)
        monkeypatch.setattr(CAM, 'headings', lambda rd, sec, road=None, pano=False: np.zeros(len(CAM.forward_items(sec))) if hs is None else hs); return key, cam

    def test_the_look_around_aim_is_relative_to_the_middle_of_each_picture_and_only_on_inside_the_stretch(self, proj, monkeypatch):
        key, cam = self.sv(proj, monkeypatch); a = PCL.aim_path(proj.folder, cam, 'pano'); n = 40
        assert a['kind'] == 'rel' and len(a['t']) == len(a['on']) == n and 'viewer' not in a
        on = [i for i, x in enumerate(a['on']) if x]; assert 0 < len(on) < n and on == list(range(on[0], on[-1] + 1))
        i = on[len(on) // 2]; assert a['yaw'][i] == pytest.approx(90.0, abs=8.0)                            # heading north along the road, the point is to the east near the closest approach: 90 degrees to the right
        assert all(-180 <= y <= 180 for y in a['yaw'])
        key2, cam2 = self.sv(proj, monkeypatch, hs=np.full(40, 90.0)); a2 = PCL.aim_path(proj.folder, cam2, 'pano'); j = [i for i, x in enumerate(a2['on']) if x][len(on) // 2]; assert abs(a2['yaw'][j]) < 8.0          # facing the point, it is dead ahead

    def test_the_flat_preview_aim_is_sampled_over_the_videos_time_with_its_fixed_view(self, proj, monkeypatch):
        key, cam = self.sv(proj, monkeypatch); a = PCL.aim_path(proj.folder, cam, 'flat'); sec = PCL.section_of(proj.race_dir, key)
        assert a['viewer'] == dict(yaw=0.0, pitch=CAM.PITCH, fov=CAM.FOV) and a['t'][0] == 0.0 and a['t'][-1] == pytest.approx(SV.default_seconds(sec), abs=0.2) and a['t'][1] == 0.2 and any(a['on']) and not all(a['on'])
        sec['provider'] = 'google'
        monkeypatch.setattr(PCL, 'section_of', lambda rd, key: sec)
        with pytest.raises(ValueError, match='cannot be aimed over'): PCL.aim_path(proj.folder, cam, 'flat')
