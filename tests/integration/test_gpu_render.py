"""The GPU renderer pieces (render/gpu.py) against the CPU reference code they replace. Needs CUDA (skipped otherwise) and, for the video conversions, ffmpeg."""
import subprocess
import numpy as np
import pytest
from strata360.osv.calib import Lens
from strata360.render import gpu, parallax as PX, seam as SM

pytestmark = pytest.mark.skipif(not gpu.available(), reason='needs CUDA')


def _lens():
    slot = {1: 1000.0, 2: 1000.0, 3: 960.0, 4: 960.0, 5: 0.01, 6: -0.002, 7: 0.0, 8: 0.0, 15: 0.0, 'q': (1.0, 0.0, 0.0, 0.0)}
    return Lens(slot)


def _dirs(n=2000, seed=0):
    d = np.random.default_rng(seed).normal(size=(n, 3)); return d / np.linalg.norm(d, axis=1, keepdims=True)


def test_lens_projection_matches_the_cpu_one():
    import torch
    L = _lens(); d = _dirs(); u, v, th = L.project(d); gu, gv, gth = (x.cpu().numpy() for x in gpu.project(L, torch.from_numpy(d).cuda()))
    assert np.abs(u - gu).max() < 1e-6 and np.abs(v - gv).max() < 1e-6 and np.abs(th - gth).max() < 1e-9


def test_parallax_warp_applies_the_same_on_the_gpu():
    import torch
    rng = np.random.default_rng(1); w = PX.Warp(rng.normal(size=(32, 256)) * 0.01, rng.normal(size=(32, 256)) * 0.01)
    d = _dirs(4000, 2); d[:2000, 1] *= 0.1; d /= np.linalg.norm(d, axis=1, keepdims=True)                          # half of them inside the band
    for sign in (1, -1): assert np.abs(w.apply(d, sign) - gpu.warp_apply(w, torch.from_numpy(d).cuda(), sign).cpu().numpy()).max() < 1e-6


def test_resampling_matches_cv2_remap():
    import cv2, torch
    rng = np.random.default_rng(2); gy, gx = np.mgrid[0:200, 0:300]; img = np.stack([(0.5 + 0.5 * np.sin(gx / 17.0 + c) * np.cos(gy / 11.0 - c)) * 65535 for c in range(3)], -1).astype(np.uint16)             # smooth: cv2's fixed-point weights differ most on noise
    u = rng.uniform(-5, 305, (40, 50)).astype(np.float32); v = rng.uniform(-5, 205, (40, 50)).astype(np.float32); t = gpu.to_gpu(img)
    for mode, flag in (('bilinear', cv2.INTER_LINEAR), ('bicubic', cv2.INTER_CUBIC)):
        ref = cv2.remap(img, u, v, flag, borderMode=cv2.BORDER_CONSTANT).astype(np.float64); got = gpu.remap(t, torch.from_numpy(u).cuda(), torch.from_numpy(v).cuda(), mode)[0].permute(1, 2, 0).cpu().numpy()
        assert np.abs(ref - got).mean() < 30, mode                                                                      # fixed point against float: well under one 10-bit step on average


def test_rgb_to_p010_matches_ffmpegs_conversion():
    rng = np.random.default_rng(3); W, H = 320, 180; x = np.linspace(0, 1, W)[None, :, None]; y = np.linspace(0, 1, H)[:, None, None]
    img = np.clip(np.concatenate([x + 0 * y, y + 0 * x, 0.5 + 0.4 * np.sin(8 * x * y)], 2) + 0.01 * rng.standard_normal((H, W, 3)), 0, 1); rgb = (img * 65535).astype(np.uint16)
    r = subprocess.run(['ffmpeg', '-v', 'error', '-f', 'rawvideo', '-pix_fmt', 'rgb48le', '-s', f'{W}x{H}', '-i', '-', '-vf', 'scale=in_range=full:out_range=tv:out_color_matrix=bt709:flags=accurate_rnd+full_chroma_int',
                        '-pix_fmt', 'p010le', '-f', 'rawvideo', '-'], input=rgb.tobytes(), capture_output=True, check=True)
    ref = np.frombuffer(r.stdout, np.uint16).astype(np.float64) / 64; mine = np.frombuffer(gpu.rgb48_to_p010(rgb), np.uint16).astype(np.float64) / 64
    assert ref.shape == mine.shape and np.abs(ref[:W * H] - mine[:W * H]).mean() < 0.5 and np.abs(ref[W * H:] - mine[W * H:]).mean() < 2.0


def test_p010_to_rgb_matches_ffmpegs_conversion():
    side = 128; gx = np.linspace(0, 1, side)[None, :]; gy = np.linspace(0, 1, side)[:, None]; h = side // 2                                   # smooth planes: the chroma filters only differ at sharp colour edges
    yuv = np.concatenate([((150 + 700 * (0.5 * gx + 0.5 * gy)) * 64).astype(np.uint16).ravel(), np.stack([((350 + 300 * np.linspace(0, 1, h)[None, :]) * np.ones((h, 1))) * 64, ((650 - 300 * np.linspace(0, 1, h)[:, None]) * np.ones((1, h))) * 64], -1).astype(np.uint16).ravel()])
    r = subprocess.run(['ffmpeg', '-v', 'error', '-f', 'rawvideo', '-pix_fmt', 'p010le', '-colorspace', 'bt709', '-color_range', 'tv', '-s', f'{side}x{side}', '-i', '-', '-pix_fmt', 'rgb48le', '-f', 'rawvideo', '-'],
                       input=yuv.tobytes(), capture_output=True, check=True)
    ref = np.frombuffer(r.stdout, np.uint16).reshape(side, side, 3).astype(np.float64); mine = gpu.frame_from_p010(yuv.tobytes(), side).numpy().astype(np.float64)
    assert np.abs(ref[8:-8, 8:-8] - mine[8:-8, 8:-8]).mean() < 200


def test_band_matches_the_cpu_band():
    gy, gx = np.mgrid[0:1000, 0:1000]; a = np.stack([(0.5 + 0.5 * np.sin(gx / 37.0 + c)) * 65535 for c in range(3)], -1).astype(np.uint16); b = np.stack([(0.5 + 0.5 * np.cos(gy / 29.0 + c)) * 65535 for c in range(3)], -1).astype(np.uint16)
    L = _lens(); om = np.ones((500, 500), np.float32)

    class Carver(SM.SeamCarver):
        def __init__(self): self.master = self.slave = L; self.occl_m = self.occl_s = om; T = np.radians(90.0 - SM.BAND_DEG + (np.arange(SM.BAND_ROWS) + 0.5) * (2 * SM.BAND_DEG / SM.BAND_ROWS)); P = (np.arange(SM.BAND_COLS) + 0.5) / SM.BAND_COLS * 2 * np.pi - np.pi; TT, PP = np.meshgrid(T, P, indexing='ij'); self.dirs = np.stack([np.sin(TT) * np.cos(PP), np.cos(TT), np.sin(TT) * np.sin(PP)], -1).reshape(-1, 3); self._proj = [L.project(self.dirs)] * 2

    c = Carver(); got = gpu.band(c, a, b); gpu._state['ok'] = False
    try: ref = c.band(a, b)
    finally: gpu._state.pop('ok')
    for (gy, gc), (ry, rc) in zip(got, ref): assert np.abs(gy - ry).mean() < 2e-3 and np.abs(gc - rc).mean() < 2e-3
