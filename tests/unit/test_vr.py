"""The 360 film (render/vr.py): the sphere turned to face the flat shot, the panel the overlay is pinned on, flat-camera transitions as cuts, generated clips on a screen, the settings and the key."""
import math

import numpy as np
import pytest

from strata360.render import camera as cam, final as FN, progress as PG, vr as VR


def sphere(W=360, H=180):
    """An equirect test picture whose red channel is the longitude and green the latitude (uint16)."""
    lon = (np.arange(W) + 0.5) / W; lat = (np.arange(H) + 0.5) / H; im = np.zeros((H, W, 3), np.uint16)
    im[..., 0] = (lon[None, :] * 60000).astype(np.uint16); im[..., 1] = (lat[:, None] * 60000).astype(np.uint16); return im


class TestDirections:
    def test_the_sphere_centre_looks_at_the_given_world_yaw(self):
        for psi in (0.0, 0.5, -2.0, math.pi):
            assert VR.rot_z(psi) @ np.array([0.0, 1.0, 0.0]) == pytest.approx(cam.direction(psi, 0.0))

    def test_a_turn_about_the_vertical_keeps_the_horizon_level(self):
        assert VR.rot_z(1.2) @ np.array([0.0, 0.0, 1.0]) == pytest.approx([0.0, 0.0, 1.0])

    def test_world_and_heading_paths_already_give_world_yaw(self):
        P = dict(ref='heading', yaw=np.array([0.1, 0.2]), pitch=np.zeros(2))
        assert VR.view_yaw(P, None) == pytest.approx([0.1, 0.2])

    def test_a_body_fixed_view_is_turned_into_the_world_by_the_stabilisation(self):
        turn = VR.rot_z(0.5).T                                                                   # d_body = M d_world with the body turned 0.5 rad to the right of the world
        P = dict(ref='body', yaw=np.array([0.3]), pitch=np.array([0.2]))
        assert VR.view_yaw(P, [turn])[0] == pytest.approx(0.8)

    @pytest.mark.parametrize('a, mean', [([0.1, 0.3], 0.2), ([math.pi - 0.1, -math.pi + 0.1], math.pi), ([], 0.0)])
    def test_circular_mean_goes_the_short_way_round(self, a, mean):
        assert abs(math.remainder(VR.circular_mean(a) - mean, 2 * math.pi)) < 1e-9


class TestPanel:
    def test_it_holds_as_many_pixels_across_its_centre_as_the_sphere(self):
        p = VR.Panel(3840, 1920, 80.0); w, h = p.size
        assert w == pytest.approx(math.tan(math.radians(40)) * 3840 / math.pi, abs=2) and w % 2 == 0 and h % 2 == 0 and w / h == pytest.approx(16 / 9, abs=0.02)

    def test_its_view_is_the_part_of_the_sphere_straight_ahead(self):
        eq = sphere(); p = VR.Panel(360, 180, 60.0); v = p.view(eq); w, h = p.size
        assert int(v[h // 2, w // 2, 0]) == pytest.approx(30000, abs=400) and int(v[h // 2, w // 2, 1]) == pytest.approx(30000, abs=400)
        assert int(v[h // 2, 0, 0]) == pytest.approx(60000 * (0.5 - 30 / 360), abs=400)                 # its left edge is 30 degrees to the left

    def test_a_raised_panel_looks_above_the_horizon(self):
        eq = sphere(); p = VR.Panel(360, 180, 60.0, pitch=20.0); v = p.view(eq); w, h = p.size
        assert int(v[h // 2, w // 2, 1]) == pytest.approx(60000 * (0.5 - 20 / 180), abs=400)

    def test_pinning_replaces_only_what_the_drawing_changed_at_the_right_place(self):
        eq = sphere(); p = VR.Panel(360, 180, 60.0); w, h = p.size

        def draw(v):
            v[h // 2 - 3:h // 2 + 3, w // 2 - 3:w // 2 + 3] = 65535; return v
        out = p.pin(eq, draw)
        assert (out[90, 180] == 65535).all()                                                       # the panel's centre is the sphere's
        changed = np.any(out != eq, axis=-1); ys, xs = np.nonzero(changed)
        assert 170 <= xs.min() and xs.max() <= 190 and 80 <= ys.min() and ys.max() <= 100           # nothing else moved
        assert (out[0, 0] == eq[0, 0]).all() and out.dtype == eq.dtype

    def test_a_drawing_that_changes_nothing_leaves_the_sphere_as_it_was(self):
        eq = sphere(); p = VR.Panel(360, 180, 60.0)
        assert p.pin(eq, lambda v: v) is eq and p.pin(eq, lambda v: None) is eq

    def test_a_flat_picture_fills_the_panel_on_a_dark_sphere(self):
        p = VR.Panel(360, 180, 60.0); img = np.full((10, 18, 3), 40000, np.uint16); out = p.screen(img)
        assert out.shape == (180, 360, 3) and (out[90, 180] == 40000).all() and (out[90, 0] == int(VR.BACKDROP * 65535)).all()


class TestSettings:
    def test_options_are_checked(self):
        assert VR.options() == dict(fov=80.0, pitch=0.0, orient='shot', source='osv')
        with pytest.raises(ValueError, match='orient'): VR.options(orient='spin')
        with pytest.raises(ValueError, match='degrees'): VR.options(fov=200)

    @pytest.mark.parametrize('size', [(3840, 2160), (100, 49), (98, 49)])
    def test_a_360_film_is_two_to_one_with_even_sides(self, size):
        with pytest.raises(ValueError, match='2:1'): VR.check_size(*size)

    def test_the_source_is_not_part_of_the_key(self):
        assert VR.signature(VR.options(source='proxy')) == VR.signature(VR.options()) != VR.signature(VR.options(fov=90))

    def test_whips_and_glides_are_cuts_and_the_rest_is_kept(self):
        segs = [dict(id='a', transition=dict(type='cut', dur_s=0.0)), dict(id='b', transition=dict(type='whip', dur_s=0.3)), dict(id='c', transition=dict(type='pan', dur_s=0.6, a_kf=[])), dict(id='d', transition=dict(type='dissolve', dur_s=0.5))]
        out = VR.as_cuts(segs)
        assert [g['transition']['type'] for g in out] == ['cut', 'cut', 'cut', 'dissolve'] and out[2]['transition']['dur_s'] == 0.0 and segs[1]['transition']['type'] == 'whip'

    def test_the_360_film_has_its_own_key(self, monkeypatch, tmp_path):
        from strata360.pipeline import config
        monkeypatch.setattr(config, 'race_dir', lambda f: str(tmp_path)); monkeypatch.setattr(FN, '_overlay_sig', lambda f: ''); monkeypatch.setattr(FN, '_text_sig', lambda f: ''); monkeypatch.setattr(FN.GR, 'on', lambda f: False)
        plan = dict(segments=[dict(id='a')]); flat = FN.final_key(plan, [3840, 1920], 50.0, '100M', 'f')
        assert flat == FN.final_key(plan, [3840, 1920], 50.0, '100M', 'f', vr=None) != FN.final_key(plan, [3840, 1920], 50.0, '100M', 'f', vr=VR.options()) != FN.final_key(plan, [3840, 1920], 50.0, '100M', 'f', vr=VR.options(orient='follow'))


class Overlay:
    def __init__(self): self.times = []

    def apply(self, img, t):
        self.times.append(t); img[:2, :2] = 65535; return img


class TestSource:
    def source(self, segs, framing=None, **kw): return VR.VRSource('/f', segs, framing or {}, 360, 180, 10.0, VR.Panel(360, 180, 60.0), progress=PG.Null(), **kw)

    def test_a_generated_clip_is_shown_on_the_panel_with_the_overlay_at_its_race_time(self, monkeypatch):
        seen = {}
        def frames(path, start, a0, a1, fps, W, H, order, dtype):
            seen.update(path=path, size=(W, H)); return (np.full((H, W, 3), 30000, np.uint16) for _ in range(a1 - a0))
        monkeypatch.setattr(VR.SYN, 'frames', frames); ov = Overlay()
        sg = dict(id='g', clip='gap1', synthetic='/f/gap1.mp4', clip_start_s=0.0, dur_s=1.0, utc_start='2026-02-21T12:00:00Z', utc_end='2026-02-21T12:00:10Z')
        src = self.source([sg], overlay=ov); src.film_synthetic = False; out = list(src.frames(0, 0, 3))
        assert len(out) == 3 and out[0].shape == (180, 360, 3) and (out[0][90, 180] == 30000).all() and seen == dict(path='/f/gap1.mp4', size=src.panel.size)
        assert ov.times[1] - ov.times[0] == pytest.approx(1.0)                                     # 10 s of race in 1 s of film, at 10 frames a second

    def test_a_shot_keeps_one_direction_whichever_part_of_it_is_asked_for(self, monkeypatch):
        sg = dict(id='s', clip='C', clip_start_s=0.0, dur_s=1.0); src = self.source([sg])
        monkeypatch.setattr(src, '_clip', lambda c: None); monkeypatch.setattr(src, '_stab', lambda ci, t: (None, [np.eye(3)] * len(t)))
        path = cam.CameraPath([dict(t=0.0, yaw=0.0), dict(t=1.0, yaw=40.0, ease='linear')], 'world')
        a = src.directions(sg, path, np.arange(0, 3) / 10.0, None); b = src.directions(sg, path, np.arange(7, 10) / 10.0, None)
        assert a == pytest.approx([math.radians(18)] * 3, abs=1e-3) and b == pytest.approx(a)

    def test_follow_turns_with_the_camera(self):
        sg = dict(id='s', clip='C', clip_start_s=0.0, dur_s=1.0); src = self.source([sg], orient='follow')
        path = cam.CameraPath([dict(t=0.0, yaw=0.0), dict(t=1.0, yaw=40.0, ease='linear')], 'world')
        assert src.directions(sg, path, np.array([0.0, 0.5, 1.0]), None) == pytest.approx(np.radians([0.0, 20.0, 40.0]))

    def test_a_generated_clip_is_taken_at_the_flat_films_size(self, monkeypatch):
        sizes = []
        monkeypatch.setattr(FN.FinalSource, 'synthetic_path', lambda self, sg: sizes.append((self.W, self.H)) or 'p'); monkeypatch.setattr(VR, 'flat_size', lambda f, sg, fps: (1920, 1080))
        src = self.source([]); assert src.synthetic_path(dict(clip='g')) == 'p' and sizes == [(1920, 1080)] and (src.W, src.H) == (360, 180)

    def test_the_flat_size_is_4k_only_when_that_clip_was_made_at_4k(self, monkeypatch, tmp_path):
        from strata360.edit import synth_render as SR, synthetic as SY
        made = tmp_path / 'g4k.mp4'; monkeypatch.setattr(SY, 'load', lambda f: dict(clips=[dict(id='g')])); monkeypatch.setattr(SR, 'film_path', lambda f, doc, fps, size: str(made))
        assert VR.flat_size('f', dict(clip='g'), 50.0) == (1920, 1080)
        made.write_bytes(b''); assert VR.flat_size('f', dict(clip='g'), 50.0) == (3840, 2160) and VR.flat_size('f', dict(clip='other'), 50.0) == (1920, 1080)


def test_subtitles_are_pinned_on_the_panel():
    class Caps:
        cues = [dict(t0=0.0, t1=1.0)]
        def apply(self, img, frame): img = img.copy(); img[:4, :4] = 65535; return img
    p = VR.Panel(360, 180, 60.0); pin = VR.Pinned(p, Caps()); eq = sphere(); out = pin.apply(eq, 0)
    assert pin.cues == Caps.cues and np.any(out != eq) and (out[0, 0] == eq[0, 0]).all()


class FakeRenderer:
    """Stands in for EquirectRenderer: records the rotation it is given and returns a sphere of the frame's number."""
    def __init__(self): self.Ms = []; self.seams = 0

    def stab_matrix(self, q): return np.eye(3)

    def update_seam(self, a, b, people=None): self.seams += 1

    def render(self, a, b, M, _): self.Ms.append(M); return np.full((180, 360, 3), int(a[0, 0, 0]), np.uint16)


class FakeDecoder:
    def __init__(self, n): self.frames = [np.full((4, 4, 3), k, np.uint16) for k in range(n)]

    def kill(self): pass

    def wait(self): pass


class TestFootage:
    def make(self, monkeypatch, n=5, **kw):
        R = FakeRenderer(); ci = dict(R=R, T=dict(quat=[[1, 0, 0, 0]] * n), pts=np.arange(n) / 10.0, n=n, osv='/x.osv', boxes=None)
        monkeypatch.setattr(VR.flat, 'decoder', lambda osv, stream, ss=0.0, native=False: FakeDecoder(n)); monkeypatch.setattr(VR.flat, 'read_frame', lambda p, nat=False: p.frames.pop(0) if p.frames else None); monkeypatch.setattr(FN.GPU, 'native_decode', lambda: False)
        sg = dict(id='s', clip='C', clip_start_s=0.0, dur_s=0.5, utc_start='2026-02-21T12:00:00Z')
        src = VR.VRSource('/f', [sg], {'s': dict(ref='world', keyframes=[dict(t=0.0, yaw=90.0)])}, 360, 180, 10.0, VR.Panel(360, 180, 60.0), progress=PG.Null(), **kw); monkeypatch.setattr(src, '_clip', lambda c: ci); return src, R

    def test_every_frame_is_a_sphere_turned_to_the_shot_with_the_overlay_pinned(self, monkeypatch):
        ov = Overlay(); src, R = self.make(monkeypatch, overlay=ov); out = list(src.frames(0, 0, 5))
        assert [int(o[90, 0, 0]) for o in out] == [0, 1, 2, 3, 4] and R.seams == 5                 # one seam per source frame
        assert all(M == pytest.approx(VR.rot_z(math.pi / 2)) for M in R.Ms)                         # the shot looks 90 degrees right: that is straight ahead now
        assert ov.times[1] - ov.times[0] == pytest.approx(0.1) and np.any(out[0] != out[0][90, 0])

    def test_past_the_end_of_the_clip_the_last_frame_is_held(self, monkeypatch):
        src, R = self.make(monkeypatch, n=3); out = list(src.frames(0, 0, 5))
        assert [int(o[90, 0, 0]) for o in out] == [0, 1, 2, 2, 2]

    def test_the_proxy_is_turned_by_shifting_it(self, monkeypatch, tmp_path):
        src, R = self.make(monkeypatch, source='proxy'); eq = sphere()

        class Dec:
            def __init__(self): self.stdout = self; self.left = 2
            def read(self, n):
                if not self.left: return b''
                self.left -= 1; return eq.tobytes()
            def close(self): pass
            def terminate(self): pass
            def wait(self): pass
        monkeypatch.setattr(FN, 'proxy_of', lambda f, c: str(tmp_path / 'proxy.mp4')); monkeypatch.setattr(VR.guard, 'popen', lambda *a, **k: Dec())
        out = list(src.frames(0, 0, 3))
        assert len(out) == 3 and (out[0][:, 180] == eq[:, 270]).all() and (out[2] == out[1]).all()     # what was 90 degrees right is the centre; past the end the last frame is held

    def test_a_clip_without_a_proxy_shows_a_card(self, monkeypatch):
        src, R = self.make(monkeypatch, source='proxy'); monkeypatch.setattr(FN, 'proxy_of', lambda f, c: None)
        out = list(src.frames(0, 0, 2)); assert len(out) == 2 and out[0].shape == (180, 360, 3)

    def test_nothing_is_asked_for_nothing(self, monkeypatch):
        src, R = self.make(monkeypatch); assert list(src.frames(0, 3, 3)) == []
