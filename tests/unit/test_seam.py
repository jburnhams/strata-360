"""The carved seam: DP, orientation, routing around disagreement and blind areas, steadiness. Run: .venv/bin/python tests/test_seam.py"""
import os, sys
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))
from strata360.render import seam as SM


def test_the_dp_follows_the_cheap_valley_with_a_bounded_step_on_a_closed_ring():
    R, C = 40, 64; cost = np.ones((R, C), np.float32); true = (20 + 6 * np.sin(np.arange(C) / C * 2 * np.pi)).astype(int)
    for c in range(C): cost[true[c], c] = 0.0
    p = SM.solve_dp(cost); assert np.abs(p - true).max() <= 1 and np.abs(np.diff(np.append(p, p[0]))).max() <= SM.MAX_STEP        # the valley, steps within the bound, and it closes on itself
    cost2 = np.ones((R, C), np.float32); cost2[:, 10:14] = SM.FORBIDDEN; cost2[5:9, 10:14] = 0.1; p2 = SM.solve_dp(cost2)
    assert all(5 <= p2[c] < 9 for c in range(10, 14))                                                                              # it goes through the only gap in a forbidden zone


def test_master_share_is_one_on_the_master_side_and_zero_on_the_other_with_a_ramp_between():
    s = SM.Seam(np.radians(np.full(SM.COLS, 1.0)), np.radians(np.full(SM.COLS, 0.5)))                                                # seam at +1 degree, feather +-0.5
    def d(lat_deg, lon_deg): la, lo = np.radians(lat_deg), np.radians(lon_deg); return np.array([[np.cos(la) * np.cos(lo), np.sin(la), np.cos(la) * np.sin(lo)]])
    assert s.master_share(d(3.0, 20))[0] == 1.0 and s.master_share(d(-3.0, 20))[0] == 0.0 and abs(s.master_share(d(1.0, 20))[0] - 0.5) < 0.02
    assert 0.0 < s.master_share(d(1.2, -150))[0] < 1.0                                                                               # inside the feather, wherever the longitude


class FakeLens:
    def project(self, d): n = len(d); return np.zeros(n), np.zeros(n), np.full(n, np.radians(90.0))


class Synthetic(SM.SeamCarver):
    """Bands made up instead of read from lens frames: lens A and B agree except in a block of columns, where they disagree for rows near the equator; coverage is full except a blind patch."""
    def __init__(self, blind=False, disagree=True, full=False):
        super().__init__(FakeLens(), FakeLens(), None, None); self.blind, self.disagree, self.full = blind, disagree, full
    def band(self, img_m, img_s, warp=None):
        r = np.arange(SM.BAND_ROWS)[:, None]; c = np.arange(SM.BAND_COLS)[None, :]; A = np.full((SM.BAND_ROWS, SM.BAND_COLS), 0.4, np.float32) + 0.0 * c; B = A.copy()
        if self.disagree: B[40:56, 600:760] += 0.5                                                                                   # rows 40-56 are the equator (rows 48): a near object seen differently
        if self.full: B[:, 600:760] = 0.4 + 0.3 * np.sign(np.sin(c[:, 600:760] * 0.9 + r * 0.7))                                  # a different TEXTURE in every row: the lenses disagree structurally wherever the seam goes
        cov = np.ones_like(A); cB = cov.copy()
        if self.blind: cov[30:60, 1400:1500] = 0.0                                                                                   # the stick: lens A blind there
        return [(A, cov), (B, cB)]


def test_the_seam_routes_around_what_the_lenses_disagree_about_and_what_a_lens_cannot_see():
    s = Synthetic(blind=False).carve(None, None); lat = np.degrees(s.lat); cols = slice(600 // 2, 760 // 2)
    assert np.abs(lat[cols]).max() > 1.5                                                                                             # it leaves the equator, away from the disagreement
    far = np.concatenate([lat[:250], lat[420:]]); assert np.abs(far).max() < 1.0 and abs(s.hw[:200].mean() - np.radians(SM.WIDE_DEG)) < np.radians(0.3)    # elsewhere it stays near the equator with the wide feather
    f = Synthetic(disagree=False, full=True).carve(None, None); assert f.info['narrow_columns'] > 20 and np.degrees(f.hw[320:380]).max() < SM.WIDE_DEG - 0.3         # nowhere to hide: the lenses are never mixed there (narrow feather)
    b = Synthetic(blind=True, disagree=False).carve(None, None); bl = np.degrees(b.lat)[1400 // 2:1500 // 2]; assert b.info['forced_columns'] == 0 and np.abs(bl).max() > 3.0      # it routes around a blind patch rather than through it


def test_a_prior_seam_steadies_the_next_one_and_limits_how_far_it_may_move():
    c = Synthetic(disagree=True); first = c.carve(None, None); again = c.carve(None, None, prior=first)
    assert again.info['used_prior'] and np.abs(np.degrees(again.lat - first.lat)).max() <= SM.TEMPORAL_CLAMP_DEG + 1e-6 and np.abs(np.degrees(again.lat - first.lat)).mean() < 0.05


if __name__ == '__main__':
    fns = [v for k, v in sorted(globals().items()) if k.startswith('test_')]; bad = 0
    for fn in fns:
        try: fn(); print('ok  ', fn.__name__)
        except Exception as e: bad += 1; print('FAIL', fn.__name__, repr(e)[:300])
    print(f'{len(fns) - bad}/{len(fns)} passed'); sys.exit(bad)
