"""The local upscaler's own logic (edit/upscale.py): when to enlarge, tiling, windows and the cache, and the night gate. A stand-in network (nearest-neighbour 4x) replaces the real model, so no weights or GPU are needed."""
import json

import cv2
import numpy as np
import pytest
try: import torch
except ImportError: torch = None                                    # (the CI unit environment has no torch: the tests that run a network are skipped there)

from strata360.edit import upscale as UP


needs_torch = pytest.mark.skipif(torch is None, reason='torch is not installed')
if torch is not None:
    class Nearest4(torch.nn.Module):
        def forward(self, x): return torch.nn.functional.interpolate(x, scale_factor=4, mode='nearest')

    class NoRed(torch.nn.Module):                                   # the model's own first (red) channel is zeroed, and the picture is enlarged 4x
        def forward(self, x): y = torch.nn.functional.interpolate(x, scale_factor=4, mode='nearest').clone(); y[:, 0] = 0; return y

    FAKE = (Nearest4(), 'cpu')


def picture(h=70, w=130):
    rng = np.random.default_rng(1); return rng.integers(0, 255, (h, w, 3), dtype=np.uint8)


class TestFactorFor:
    def test_enough_pixels_means_no_upscale(self):
        assert UP.factor_for(source_px_per_deg=22.0, out_px=1920, narrowest_fov=85.0) == 1

    def test_a_low_resolution_source_is_enlarged_by_the_ratio(self):
        assert UP.factor_for(10.7, 1920, 85.0) == 2                 # 22.6 px/deg wanted, 10.7 held
        assert UP.factor_for(7.0, 1920, 85.0) == 3

    def test_the_tightest_zoom_of_the_shot_decides(self):
        wide = UP.factor_for(10.7, 1920, 85.0); tight = UP.factor_for(10.7, 1920, 45.0)
        assert wide == 2 and tight == 4                            # one tight moment enlarges the whole shot more

    def test_it_never_exceeds_the_model_factor(self):
        assert UP.factor_for(1.0, 1920, 30.0) == UP.MAX_FACTOR

    def test_a_small_shortfall_is_left_to_the_plain_scaler(self):
        assert UP.factor_for(16.0, 1920, 85.0) == 1                 # ratio 1.41, under MIN_RATIO


@needs_torch
class TestUpscale:
    @pytest.mark.parametrize('factor', [2, 3, 4])
    def test_size_is_factor_times_the_input(self, factor):
        assert UP.upscale(picture(), factor, model=FAKE).shape == (70 * factor, 130 * factor, 3)

    def test_tiling_gives_the_same_picture_as_one_piece(self, monkeypatch):
        im = picture(); one = UP.upscale(im, 4, model=FAKE)
        monkeypatch.setitem(UP.MODELS, UP.MODEL, UP.MODELS[UP.MODEL][:3] + (32,)); tiled = UP.upscale(im, 4, model=FAKE)
        assert np.array_equal(one, tiled)

    def test_factor_two_is_the_four_times_result_brought_down(self):
        im = picture(); two = UP.upscale(im, 2, model=FAKE)
        assert np.array_equal(two, np.repeat(np.repeat(im, 2, 0), 2, 1))        # nearest 4x then area 2x of a nearest image is nearest 2x


@needs_torch
class TestPrecisionAndOrder:
    def test_sixteen_bit_pictures_stay_sixteen_bit_with_their_values(self):
        im = np.random.default_rng(2).integers(0, 65535, (12, 20, 3), dtype=np.uint16); out = UP.upscale(im, 2, model=FAKE, bgr=False)
        assert out.dtype == np.uint16 and np.abs(out.astype(int) - np.repeat(np.repeat(im, 2, 0), 2, 1)).max() <= 1       # (no rounding down to 8 bits: a sky would band)

    def test_bgr_pictures_are_shown_to_the_model_as_rgb(self):
        out = UP.upscale(np.full((8, 8, 3), 200, np.uint8), 2, model=(NoRed(), 'cpu'), bgr=True); assert out[..., 2].max() == 0 and out[..., 0].min() == 200      # red is the last channel of BGR

    def test_rgb_pictures_are_given_as_they_are(self):
        out = UP.upscale(np.full((8, 8, 3), 200, np.uint8), 2, model=(NoRed(), 'cpu'), bgr=False); assert out[..., 0].max() == 0 and out[..., 2].min() == 200


class TestCached:
    def test_made_once_and_named_after_the_model(self, tmp_path, monkeypatch):
        path = str(tmp_path / 'p.pano.jpg'); cv2.imwrite(path, picture(), [cv2.IMWRITE_JPEG_QUALITY, 100]); calls = []
        monkeypatch.setattr(UP, 'upscale', lambda im, f, wrap_x=False, model=None, name=None: calls.append(im.shape) or np.zeros((im.shape[0] * f, im.shape[1] * f, 3), np.uint8))
        a = UP.cached(path, 2, log=lambda m: None); b = UP.cached(path, 2, log=lambda m: None)
        assert len(calls) == 1 and a.shape == b.shape == (140, 260, 3) and (tmp_path / f'p.pano.{UP.MODEL}.x2.jpg').exists()

    def test_a_window_is_cropped_with_wrap_and_kept_apart(self, tmp_path, monkeypatch):
        path = str(tmp_path / 'p.jpg'); cv2.imwrite(path, picture(), [cv2.IMWRITE_JPEG_QUALITY, 100]); seen = []
        monkeypatch.setattr(UP, 'upscale', lambda im, f, wrap_x=False, model=None, name=None: seen.append(im) or np.zeros((im.shape[0] * f, im.shape[1] * f, 3), np.uint8))
        out = UP.cached(path, 2, box=(-10, 20, 5, 25), log=lambda m: None)         # x runs past the left edge: the right edge is used
        whole = cv2.imread(path)
        assert seen[0].shape == (20, 30, 3) and np.array_equal(seen[0][:, :10], whole[5:25, -10:]) and out.shape == (40, 60, 3)
        assert (tmp_path / f'p.w-10_20_5_25.{UP.MODEL}.x2.jpg').exists()


class TestLoad:
    def test_a_missing_package_says_what_to_install(self, monkeypatch):
        import sys; monkeypatch.setitem(sys.modules, 'spandrel', None); monkeypatch.setattr(UP, '_model', {})
        with pytest.raises(RuntimeError, match='torch and spandrel packages.*pip install -r requirements.txt'): UP.load()

    def test_missing_weights_say_where_to_get_them(self, tmp_path, monkeypatch):
        monkeypatch.setattr(UP, '_model', {}); monkeypatch.setattr(UP, 'weights_path', lambda name=None, root=None: str(tmp_path / 'none.pth'))
        pytest.importorskip('torch'); pytest.importorskip('spandrel')
        with pytest.raises(FileNotFoundError, match='github.com'): UP.load()


class TestSkipReason:
    def write(self, d, sun, exposure):
        (d / 'exposure.json').write_text(json.dumps(exposure))
        if sun is not None: (d / 'sun.json').write_text(json.dumps(sun))

    def frames(self, level): return dict(frames=[dict(sphere=dict(mean_lin=level)) for _ in range(5)])

    def test_a_dark_clip_under_a_low_sun_is_skipped(self, tmp_path):
        self.write(tmp_path, dict(covered=True, elevation_deg=-30.0), self.frames(0.002))
        assert 'night' in UP.skip_reason(str(tmp_path))

    def test_a_lit_indoor_clip_at_night_is_kept(self, tmp_path):
        self.write(tmp_path, dict(covered=True, elevation_deg=-30.0), self.frames(0.4)); assert UP.skip_reason(str(tmp_path)) is None

    def test_without_the_sun_stage_nothing_is_excluded(self, tmp_path):
        self.write(tmp_path, None, self.frames(0.002)); assert UP.skip_reason(str(tmp_path)) is None
