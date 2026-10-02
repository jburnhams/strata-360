"""EquirectRenderer.maps (the proxy renderer) must hand the carved seam its body-frame rays and apply the parallax warp, as flat.Renderer.maps does."""
import numpy as np
from strata360.render import proxy as P


class Lens:
    def __init__(self): self.seen = None
    def project(self, d): self.seen = d.copy(); n = len(d); return np.zeros(n), np.zeros(n), np.zeros(n)


class Warp:
    def apply(self, d, sign): return d + sign * 0.01


def renderer(warp=None):
    r = P.EquirectRenderer.__new__(P.EquirectRenderer); r.gw, r.gh = 2, 2; r.dE = np.eye(3)[[0, 1, 2, 0]]; r.master, r.slave = Lens(), Lens(); r.warp = warp
    return r


def test_maps_keeps_the_body_frame_rays_for_the_seam():
    r = renderer(); M = np.eye(3); r.maps(M, None)
    assert np.allclose(r._dirs, r.dE) and np.allclose(r.master.seen, r.dE) and np.allclose(r.slave.seen, r.dE)


def test_maps_moves_each_lens_by_the_parallax_warp_in_opposite_directions():
    r = renderer(Warp()); r.maps(np.eye(3), None)
    assert np.allclose(r._dirs, r.dE) and np.allclose(r.master.seen, r.dE + 0.01) and np.allclose(r.slave.seen, r.dE - 0.01)
