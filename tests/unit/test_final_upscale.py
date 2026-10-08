"""Enlarging shots in the final render (render/final.py `FinalSource`): one factor for a whole shot from its narrowest view, none for night footage or a generated clip, a renderer at 1/factor of the output size, and the enlarged picture fitted to the output."""
import numpy as np
import pytest

from strata360.edit import upscale as UP
from strata360.render import final as FN, flat, progress as PG


def path(*fovs): return dict(ref='world', keyframes=[dict(t=float(i), yaw=0.0, pitch=0.0, roll=0.0, fov=float(f)) for i, f in enumerate(fovs)])


def source(framing, W=3840, H=2160, upscale='full', **kw):
    segs = [dict(id=k, clip='C') for k in framing]; return FN.FinalSource('/f', segs, framing, W, H, 50.0, upscale=upscale, progress=PG.Null(), **kw)


@pytest.fixture(autouse=True)
def day(monkeypatch): monkeypatch.setattr(UP, 'skip_reason', lambda d: None)


class TestShotFactor:
    def test_off_means_one(self): assert source({'w1': path(40)}, upscale='off').shot_factor(dict(id='w1', clip='C')) == 1

    def test_a_tight_shot_is_enlarged(self): assert source({'w1': path(45)}).shot_factor(dict(id='w1', clip='C')) == 4

    def test_a_wide_shot_that_the_footage_already_fills_is_not(self): assert source({'w1': path(90)}, 1920, 1080).shot_factor(dict(id='w1', clip='C')) == 1

    def test_the_narrowest_view_anywhere_in_the_shot_decides_for_all_of_it(self):
        s = source({'w1': path(90, 90, 40, 90)}); assert s.shot_factor(dict(id='w1', clip='C')) == UP.factor_for(20.0, 3840, 40.0) == 4

    def test_the_same_shot_always_gets_the_same_answer(self):
        s = source({'w1': path(60)}); sg = dict(id='w1', clip='C'); assert len({s.shot_factor(sg) for _ in range(3)}) == 1

    def test_night_footage_is_left_alone_and_the_log_says_why(self, monkeypatch):
        monkeypatch.setattr(UP, 'skip_reason', lambda d: 'night: the sun is -30 degrees'); s = source({'w1': path(40)})
        assert s.shot_factor(dict(id='w1', clip='C')) == 1 and any('night' in m for _, m in s.pg.log)

    def test_the_clip_folder_is_what_the_night_test_reads(self, monkeypatch):
        seen = []; monkeypatch.setattr(UP, 'skip_reason', lambda d: seen.append(d)); source({'w1': path(40)}).shot_factor(dict(id='w1', clip='CAM_1'))
        assert seen[0].endswith('clips/CAM_1')

    def test_a_generated_clip_is_never_enlarged(self): assert source({'w1': path(40)}).shot_factor(dict(id='w1', clip='C', synthetic='x.mp4')) == 1

    def test_the_decision_is_logged_once(self):
        s = source({'w1': path(40)}); sg = dict(id='w1', clip='C'); s.shot_factor(sg); s.shot_factor(sg); assert sum('enlarged' in m for _, m in s.pg.log) == 1


class TestModes:
    def sg(self): return dict(id='w1', clip='C')

    def test_the_model_works_up_to_the_modes_width_not_the_outputs(self):
        f = lambda mode, fov: source({'w1': path(fov)}, upscale=mode).shot_factor(self.sg())
        assert f('full', 45) == 4 and f('1440p', 45) == 3 and f('1080p', 45) == 2          # 3840, 2560 and 1920 wide wanted from 20 px/degree at 45 degrees

    def test_a_wide_shot_the_lower_mode_already_satisfies_is_not_enlarged_at_all(self):
        assert source({'w1': path(90)}, upscale='1080p').shot_factor(self.sg()) == 1 and source({'w1': path(90)}, upscale='full').shot_factor(self.sg()) == 2

    def test_the_renderer_makes_the_picture_for_the_modes_width(self, monkeypatch):
        made = []
        class R:
            def __init__(self, osv, W, H, *a): made.append((W, H))
        monkeypatch.setattr(flat, 'Renderer', R); s = source({'w1': path(45)}, upscale='1080p'); s._renderer(dict(osv='x', R=None, Rs={}), 2); assert made == [(960, 540)]

    def test_a_lower_mode_is_resampled_to_the_output_with_lanczos_and_the_resample_is_timed(self, monkeypatch):
        import cv2
        monkeypatch.setattr(UP, 'upscale', lambda im, f, wrap_x=False, model=None, name=None, bgr=True: np.repeat(np.repeat(im, f, 0), f, 1)); seen = []
        real = cv2.resize; monkeypatch.setattr(cv2, 'resize', lambda im, size, interpolation=None, **k: seen.append(interpolation) or real(im, size, interpolation=interpolation))
        s = source({'w1': path(45)}, 3840, 2160, upscale='1080p'); out = s._enlarge(np.zeros((540, 960, 3), np.uint16), 2)
        assert out.shape == (2160, 3840, 3) and seen == [cv2.INTER_LANCZOS4] and s.pg.timings['resample']['calls'] == 1

    def test_the_full_mode_only_brings_a_small_overshoot_down(self, monkeypatch):
        import cv2
        monkeypatch.setattr(UP, 'upscale', lambda im, f, wrap_x=False, model=None, name=None, bgr=True: np.repeat(np.repeat(im, f, 0), f, 1)); seen = []
        real = cv2.resize; monkeypatch.setattr(cv2, 'resize', lambda im, size, interpolation=None, **k: seen.append(interpolation) or real(im, size, interpolation=interpolation))
        source({'w1': path(45)}, 100, 60)._enlarge(np.zeros((20, 34, 3), np.uint16), 3); assert seen == [cv2.INTER_AREA]

    def test_modes_are_normalised(self):
        assert [UP.normalize(v) for v in (None, False, '', 'off', True, 'full', '1080p', '1440p')] == ['off', 'off', 'off', 'off', 'full', 'full', '1080p', '1440p']
        with pytest.raises(ValueError): UP.normalize('8k')

    def test_the_width_is_never_more_than_the_outputs(self):
        assert [UP.target_width(m, 1920) for m in ('off', '1080p', '1440p', 'full')] == [0, 1920, 1920, 1920] and UP.target_width('1440p', 3840) == 2560


class TestRenderersAndPicture:
    def test_a_shot_is_rendered_at_a_fraction_of_the_output_and_the_renderers_are_kept(self, monkeypatch):
        made = []
        class R:
            def __init__(self, osv, W, H, *a): made.append((W, H))
        monkeypatch.setattr(flat, 'Renderer', R); s = source({'w1': path(40)}); ci = dict(osv='x.osv', R=object(), Rs={(3840, 2160): None}); ci['Rs'][(3840, 2160)] = ci['R']
        assert s._renderer(ci, 1) is ci['R'] and made == []
        a = s._renderer(ci, 4); b = s._renderer(ci, 4); assert a is b and made == [(960, 540)]

    def test_an_output_not_divisible_by_the_factor_rounds_up(self, monkeypatch):
        made = []
        class R:
            def __init__(self, osv, W, H, *a): made.append((W, H))
        monkeypatch.setattr(flat, 'Renderer', R); s = source({'w1': path(40)}, 1000, 563); s._renderer(dict(osv='x', R=None, Rs={}), 3); assert made == [(334, 188)]

    def test_the_enlarged_picture_is_fitted_to_the_output_size_and_the_work_is_timed(self, monkeypatch):
        monkeypatch.setattr(UP, 'upscale', lambda im, f, wrap_x=False, model=None, name=None, bgr=True: np.repeat(np.repeat(im, f, 0), f, 1))
        s = source({'w1': path(40)}, 100, 60); small = np.zeros((20, 34, 3), np.uint16); out = s._enlarge(small, 3)          # 34 x 3 = 102 wide: a little over, brought down to 100
        assert out.shape == (60, 100, 3) and out.dtype == np.uint16 and s.pg.timings['upscale']['calls'] == 1

    def test_the_model_is_given_the_renderers_rgb_order(self, monkeypatch):
        seen = []; monkeypatch.setattr(UP, 'upscale', lambda im, f, wrap_x=False, model=None, name=None, bgr=True: seen.append(bgr) or np.repeat(np.repeat(im, f, 0), f, 1))
        source({'w1': path(40)}, 8, 8)._enlarge(np.zeros((4, 4, 3), np.uint16), 2); assert seen == [False]


class TestKey:
    def test_the_key_changes_only_when_enlarging_is_on(self, project):
        p = dict(segments=[dict(id='w0', clip='C', film_start_s=0.0, dur_s=1.0)])
        a = FN.final_key(p, [1920, 1080], 50.0, '100M', project.folder); b = FN.final_key(p, [1920, 1080], 50.0, '100M', project.folder, 'full')
        assert a == FN.final_key(p, [1920, 1080], 50.0, '100M', project.folder, 'off') and a != b


class TestWarmUpFrames:
    """A still renders a few frames before the wanted one only to settle the seam: those must not cost an enlarge, a grade or an overlay."""
    def run(self, monkeypatch, last_only, m=4):
        import types
        calls = dict(enlarge=0, grade=0, overlay=0)
        class Overlay:
            def apply(self, img, t): calls['overlay'] += 1; return img
        class Renderer:
            carve_seam = parallax = False; seam = warp = None
            def set_background(self, *a, **k): pass
            def update_seam(self, *a, **k): pass
            def set_fov(self, *a, **k): pass
            def render(self, *a, **k): return np.zeros((6, 8, 3), np.uint16)
            def stab_matrix(self, q): return np.eye(3)
        class Path:
            ref = 'body'; bg = 'blur'; bg_opts = {}; use_disc = False
            def evaluate(self, times, Ms, fps): n = len(times); return dict(ref='body', fov=np.full(n, 40.0), dist=np.zeros(n), disc=np.zeros(n), use_disc=False, yaw=np.zeros(n), pitch=np.zeros(n), roll=np.zeros(n))
            def set_background(self, *a): pass
        monkeypatch.setattr(FN.cam.CameraPath, 'from_dict', classmethod(lambda cls, d: Path())); monkeypatch.setattr(FN.cam, 'direction', lambda y, p: np.array([0.0, 0.0, 1.0]))
        monkeypatch.setattr(FN.GR, 'apply', lambda img, g: calls.__setitem__('grade', calls['grade'] + 1) or img)
        s = source({'w1': path(40)}, 8, 6, overlay=Overlay(), gains={'w1': lambda t: 1.0}); s.last_only = last_only
        s._enlarge = lambda img, f: calls.__setitem__('enlarge', calls['enlarge'] + 1) or np.zeros((6, 8, 3), np.uint16); s.shot_factor = lambda sg: 2; s._renderer = lambda ci, f: ci['R']
        ci = dict(osv='x', R=Renderer(), Rs={}, boxes=None, n=100, pts=np.arange(100) / 50.0, T=dict(quat=np.zeros((100, 4))), src_fps=50.0); ci['Rs'][(8, 6)] = ci['R']; s.info['C'] = ci
        s.segs = [dict(id='w1', clip='C', clip_start_s=0.0, utc_start='2026-02-21T12:00:00Z')]
        monkeypatch.setattr(flat, 'decoder', lambda *a, **k: types.SimpleNamespace(kill=lambda: None, wait=lambda: None)); monkeypatch.setattr(flat, 'read_frame', lambda p: np.zeros((2, 2, 3), np.uint16)); monkeypatch.setattr(flat, 'frame_at', lambda pts, t: np.arange(len(t)))
        monkeypatch.setattr(FN.SM, 'people_in_layout', lambda *a, **k: None)
        frames = list(s.frames(0, 0, m)); return frames, calls

    def test_a_normal_render_enlarges_grades_and_overlays_every_frame(self, monkeypatch):
        frames, calls = self.run(monkeypatch, False); assert len(frames) == 4 and calls == dict(enlarge=4, grade=4, overlay=4)

    def test_for_a_still_only_the_last_frame_gets_them(self, monkeypatch):
        frames, calls = self.run(monkeypatch, True); assert len(frames) == 4 and calls == dict(enlarge=1, grade=1, overlay=1)
