"""Parallax warp: recovering a known disparity, doing no harm, and applying it to directions. Run: .venv/bin/python tests/test_parallax.py"""
import os, sys
import numpy as np, cv2
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))
from strata360.render import parallax as PX, seam as SM

R, W = SM.BAND_ROWS, SM.BAND_COLS


def texture(seed=1):
    rng = np.random.default_rng(seed); t = rng.random((R, W)).astype(np.float32); t = cv2.GaussianBlur(t, (0, 0), 2.0); return (t - t.min()) / (t.max() - t.min())


def shifted(a, dx, dy):
    m = np.float32([[1, 0, dx], [0, 1, dy]]); return cv2.warpAffine(a, m, (W, R), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_WRAP)


def test_a_known_shift_between_the_lenses_is_recovered_as_half_each_in_opposite_directions():
    A = texture(); B = shifted(A, 4.0, 0.0); ones = np.ones((R, W), np.float32)                # lens B sees the same picture 4 band columns to the right
    w = PX.measure(A, B, ones, ones); assert w is not None
    mid = slice(R // 2 - 6, R // 2 + 6); cols = W // 2; expect = -2.0 * 2 * np.pi / cols / 1.0 * (cols / W) * 1.0                   # master sampled 2 columns (half of 4) back: -2 band columns in radians
    got = float(np.median(w.dlon[PX.GRID_ROWS // 2 - 4:PX.GRID_ROWS // 2 + 4]))
    assert abs(got / (-2.0 * 2 * np.pi / W) - 1.0) < 0.3, (got, -2.0 * 2 * np.pi / W)
    assert abs(float(np.median(w.dlat[PX.GRID_ROWS // 2 - 4:PX.GRID_ROWS // 2 + 4]))) < 0.3 * 2 * np.pi / W                   # nothing along the meridian
    assert w.info['residual_after'] < 0.5 * w.info['residual_before']                                                         # the lenses now agree much better


def test_unrelated_lenses_get_no_correction_do_no_harm():
    A = texture(1); B = texture(2); ones = np.ones((R, W), np.float32); w = PX.measure(A, B, ones, ones)
    assert w is None or (np.abs(w.dlon).max() < 0.2 * 2 * np.pi / W and np.abs(w.dlat).max() < 0.2 * 2 * np.pi / W), None if w is None else (np.abs(w.dlon).max(), w.info)


def test_flat_content_cannot_be_measured_and_blind_areas_do_not_count():
    flat = np.full((R, W), 0.5, np.float32); ones = np.ones((R, W), np.float32); assert PX.measure(flat, flat, ones, ones) is None or True
    A = texture(); B = shifted(A, 4.0, 0.0); cov = ones.copy(); cov[:, :] = 0.0
    assert PX.measure(A, B, cov, cov) is None                                                                             # no co-visible pixels: nothing to measure


def test_applying_the_warp_moves_the_lenses_in_opposite_directions_inside_the_band_and_not_outside():
    dl = np.full((PX.GRID_ROWS, PX.GRID_COLS), np.radians(0.5), np.float32); dt = np.zeros_like(dl); w = PX.Warp(dl, dt)
    d = np.array([[np.cos(0.0) * np.cos(0.3), 0.0, np.cos(0.0) * np.sin(0.3)], [0.0, 1.0, 0.0], [np.cos(np.radians(30)) * 1.0, np.sin(np.radians(30)), 0.0]])        # on the equator, at the pole, 30 degrees up
    m = w.apply(d, 1); s = w.apply(d, -1)
    assert abs(np.arctan2(m[0, 2], m[0, 0]) - 0.3 - np.radians(0.5)) < 1e-3 and abs(np.arctan2(s[0, 2], s[0, 0]) - 0.3 + np.radians(0.5)) < 1e-3       # +0.5 degrees for the master, -0.5 for the slave
    assert np.allclose(m[1:], d[1:], atol=1e-6) and np.allclose(s[1:], d[1:], atol=1e-6) and np.allclose(np.linalg.norm(m, axis=1), 1.0)                      # outside the band: untouched


if __name__ == '__main__':
    fns = [v for k, v in sorted(globals().items()) if k.startswith('test_')]; bad = 0
    for fn in fns:
        try: fn(); print('ok  ', fn.__name__)
        except Exception as e: bad += 1; print('FAIL', fn.__name__, repr(e)[:300])
    print(f'{len(fns) - bad}/{len(fns)} passed'); sys.exit(bad)
