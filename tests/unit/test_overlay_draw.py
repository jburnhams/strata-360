"""overlay/draw.py: text, icons, marker, map frames and route lines as RGBA patches, and laying patches onto uint8 and uint16 frames."""
import numpy as np
import pytest
from strata360.overlay import draw as D


def solid(h, w, rgba): return np.broadcast_to(np.array(rgba, np.uint8), (h, w, 4)).copy()


class TestText:
    def test_digits_have_equal_width(self):
        assert D.text('1111', 40)[2] == pytest.approx(D.text('8888', 40)[2]) and D.text('1:11', 40)[2] == pytest.approx(D.text('8:88', 40)[2])

    def test_labels_are_set_proportionally(self):
        assert D.text('iiii', 40, D.LABEL_FONT, tabular=False)[2] < D.text('WWWW', 40, D.LABEL_FONT, tabular=False)[2]

    def test_patch_is_white_text_with_a_dark_shadow(self):
        rgba, pad, w = D.text('88', 48); a = rgba[..., 3]; opaque = a == 255
        assert pad >= 2 and rgba.shape[1] >= w + 2 * pad and opaque.any() and (rgba[opaque][:, :3] >= 250).all()
        assert ((a > 0) & (a < 255) & (rgba[..., 0] < 128)).any()                    # shadow pixels: partly see-through and dark

    def test_scales_with_size(self):
        assert D.text('12', 80)[0].shape[0] > 1.8 * D.text('12', 40)[0].shape[0] * 0.9

    def test_empty_string(self):
        rgba, pad, w = D.text('', 20); assert w == 0 and rgba.shape[2] == 4


class TestShapes:
    @pytest.mark.parametrize('name', sorted(D.ICONS))
    def test_icons_draw_something(self, name):
        rgba, pad = D.icon(name, 64); assert rgba.shape[:2] == (64 + 2 * pad, 64 + 2 * pad) and (rgba[..., 3] == 255).sum() > 300

    def test_slope_down_mirrors_slope(self):
        up, _ = D.icon('slope', 64); down, _ = D.icon('slope_down', 64); assert (np.abs(up[..., 3].astype(int) - down[:, ::-1, 3]) > 40).mean() < 0.02

    def test_heart_is_red(self):
        rgba, _ = D.icon('heart', 64); assert tuple(rgba[rgba[..., 3] == 255][0][:3]) == (255, 84, 96)

    def test_marker_fill_edge_and_transparent_corners(self):
        m = D.marker(10, fill=(0, 0, 255)); c = m.shape[0] // 2
        assert tuple(m[c, c]) == (0, 0, 255, 255) and m[0, 0, 3] == 0 and m[c, 1][:3].max() < 40

    def test_rounded_mask_corners_and_ring(self):
        m = D.rounded(100, 30); ring = D.rounded(100, 30, 3)
        assert m[0, 0] == 0 and m[50, 50] == 1 and m[50, 0] > 0.9 and ring[50, 50] == 0 and ring[50, 1] > 0.9


class TestFramed:
    def test_opacity_outline_and_corners(self):
        p = D.framed(np.full((100, 100, 3), 200, np.uint8), 20, 0.6, outline=(255, 0, 0), outline_w=3)
        assert p[0, 0, 3] == 0 and p[50, 50, 3] == pytest.approx(153, abs=1) and tuple(p[50, 50, :3]) == (200, 200, 200) and tuple(p[50, 1]) == (255, 0, 0, 255)

    def test_without_outline(self):
        p = D.framed(np.full((40, 40, 3), 90, np.uint8), 0, 1.0, outline=None); assert (p[..., 3] == 255).all() and (p[..., :3] == 90).all()


class TestRouteLine:
    def test_draws_along_the_points(self):
        img = np.zeros((50, 50, 3), np.uint8); D.route_line(img, np.array([5.0, 45.0]), np.array([25.0, 25.0]), colour=(255, 0, 0), width=3)
        assert tuple(img[25, 25]) == (255, 0, 0) and img[5].max() == 0

    def test_nan_breaks_the_line(self):
        img = np.zeros((50, 50, 3), np.uint8); D.route_line(img, np.array([5.0, 20.0, np.nan, 30.0, 45.0]), np.full(5, 25.0), colour=(255, 0, 0), width=1)
        assert img[25, 25].max() == 0 and img[25, 10, 0] > 0 and img[25, 40, 0] > 0

    def test_points_far_away_are_ignored(self):
        img = np.zeros((20, 20, 3), np.uint8); D.route_line(img, np.array([1e9, 2e9]), np.array([1e9, 2e9])); assert img.max() == 0


class TestComposite:
    def test_opaque_transparent_and_half(self):
        f = np.full((4, 6, 3), 100, np.uint8); p = solid(2, 2, (200, 200, 200, 255)); q = solid(2, 2, (0, 0, 0, 0)); r = solid(2, 2, (200, 0, 0, 128))
        D.composite(f, [(0, 0, p), (2, 0, q), (4, 0, r)])
        assert tuple(f[0, 0]) == (200, 200, 200) and tuple(f[0, 2]) == (100, 100, 100) and tuple(f[0, 4]) == (150, 50, 50) and tuple(f[3, 0]) == (100, 100, 100)

    def test_sixteen_bit_frame(self):
        f = np.zeros((2, 2, 3), np.uint16); D.composite(f, [(0, 0, solid(2, 2, (255, 0, 255, 255)))]); assert tuple(f[0, 0]) == (65535, 0, 65535)

    def test_patches_are_cut_at_the_edges(self):
        f = np.zeros((4, 4, 3), np.uint8); D.composite(f, [(-1, -1, solid(2, 2, (9, 9, 9, 255))), (3, 3, solid(3, 3, (7, 7, 7, 255))), (10, 10, solid(2, 2, (1, 1, 1, 255)))])
        assert f[0, 0, 0] == 9 and f[1, 1, 0] == 0 and f[3, 3, 0] == 7 and f.sum() == 9 * 3 + 7 * 3
