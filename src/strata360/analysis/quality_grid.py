"""`quality` stage (implementation plan K2): how good each direction of a clip looks, on a 15 degree grid (12 rows x 24 columns of the clip's equirect proxy) twice a second, from plain image measurements. The numbers are
guardrails and tie-breaks for choosing a view (edit/view_quality.py), never a ranking of beauty: they punish open, bright landscapes, so the scenes stage's scenery rating decides where the picture is good and this says where it is
featureless, blurred, hazy or blown out.

Channels, per frame and cell (`CHANNELS`): fine (mean fine detail), mid (mid-scale detail), blur (fine over mid: low = blurry whatever the texture), tex (mid detail: low = featureless: sky, fog, a hand, a smear), dark (the dark channel: haze and
fog raise it), contrast (luma standard deviation), sat (saturation), clip_hi and clip_lo (the share of near-white and near-black pixels), luma. Output `quality_grid.npz`: `hz` and one (n, 12, 24) float16 array per channel."""
import os, subprocess

import numpy as np, cv2

from strata360.pipeline import guard

W, H, GR, GC = 1920, 960, 12, 24
CHANNELS = ('fine', 'mid', 'blur', 'tex', 'dark', 'contrast', 'sat', 'clip_hi', 'clip_lo', 'luma')
HZ = 2.0
FILE = 'quality_grid.npz'


def _cells(a): return a.reshape(GR, H // GR, GC, W // GC).mean((1, 3))


def measure(img):
    """The channels of one BGR frame (H x W x 3 uint8): {name: (12, 24) float array}."""
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32); b1 = cv2.GaussianBlur(g, (0, 0), 1.0); b4 = cv2.GaussianBlur(g, (0, 0), 4.0)
    fc, mc = _cells(np.abs(g - b1)), _cells(np.abs(b1 - b4)); mean = _cells(g); dark = _cells(img.min(2).astype(np.float32)); contrast = np.sqrt(np.maximum(_cells(g * g) - mean ** 2, 0))
    sat = _cells(cv2.cvtColor(img, cv2.COLOR_BGR2HSV)[..., 1].astype(np.float32))
    return dict(fine=fc, mid=mc, blur=fc / (mc + 1.0), tex=mc, dark=dark, contrast=contrast, sat=sat, clip_hi=_cells((g > 250).astype(np.float32)), clip_lo=_cells((g < 8).astype(np.float32)), luma=mean)


def frames(path, hz=HZ):
    """BGR frames of the proxy at `hz` a second, scaled to 1920 x 960 (area average), one at a time."""
    cmd = ['ffmpeg', '-v', 'error', '-threads', '2', '-i', path, '-an', '-vf', f'fps={hz:g},scale={W}:{H}:flags=area', '-pix_fmt', 'bgr24', '-f', 'rawvideo', '-']
    p = guard.popen(cmd, stdout=subprocess.PIPE, bufsize=W * H * 3 * 2); n = W * H * 3
    try:
        while True:
            b = p.stdout.read(n)
            if len(b) < n: break
            yield np.frombuffer(b, np.uint8).reshape(H, W, 3)
    finally:
        p.stdout.close(); p.wait()


def analyse(proxy_path, hz=HZ, progress=None):
    """{channel: (n, 12, 24) float16, 'hz': hz} for the proxy video. Raises RuntimeError when no frame could be read."""
    out = {k: [] for k in CHANNELS}
    for i, img in enumerate(frames(proxy_path, hz)):
        for k, v in measure(img).items(): out[k].append(v)
        if progress: progress(i + 1)
    if not out['luma']: raise RuntimeError(f'no frames could be read from {proxy_path}')
    return dict(hz=float(hz), **{k: np.array(v, np.float16) for k, v in out.items()})


def save(path, grid):
    tmp = path + '.tmp.npz'; np.savez_compressed(tmp, **grid); os.replace(tmp, path)


def load(clip_dir):
    """The clip's quality grid (`analyse`'s dict, `hz` a float), or None when the quality stage has not made it."""
    try:
        with np.load(os.path.join(clip_dir, FILE)) as z: d = {k: z[k] for k in z.files}
    except (OSError, ValueError): return None
    d['hz'] = float(d['hz']); return d
