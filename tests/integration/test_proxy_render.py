"""The upright (equirect) renderer used for the proxies must work with the carved seam and the parallax warp on. It once did not: its `maps` override never set the ray directions the seam reads
(or applied the warp), so a proxy render with the seam on crashed. Uses the synthetic OSV's calibration; the lens frames are synthetic noise."""
import numpy as np
from strata360.render import proxy as P, flat as r4


def test_equirect_renderer_renders_with_seam_and_parallax(synthetic_osv):
    rng = np.random.default_rng(1); R = P.EquirectRenderer(synthetic_osv, 128, 64)
    base = rng.integers(8000, 50000, (r4.LS // 8, r4.LS // 8, 3), dtype=np.uint16)
    cm = np.ascontiguousarray(np.kron(base, np.ones((8, 8, 1), np.uint16))); cs = np.ascontiguousarray(np.roll(cm, 5, axis=1))            # two lens frames that nearly agree
    R.carve_seam = True; R.parallax = True; R.update_seam(cm, cs, reset=True)
    img = R.render(cm, cs, np.eye(3), None)
    assert img.shape[:2] == (64, 128) and img.dtype == np.uint16 and R.seam is not None and R._dirs.shape[1] == 3
    assert (img > 0).mean() > 0.2                                                                                                          # the lenses cover part of the sphere (the synthetic calibration is not a real lens)
