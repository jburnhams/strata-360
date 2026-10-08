"""`lens` stage (implementation plan C1): is something over either lens (a hand or finger, fog, water, a wet smear, glare)? Once a second, per lens, from the lens picture itself (480 x 480, the fisheye circle fills the square), plain measurements on a 12 x 12 grid of cells inside the circle.

A cell is FLAT when it has almost no fine detail (a hand a few centimetres from the lens is out of focus; fog and a wet lens are smooth). Blue sky is flat too, so a flat cell that looks like sky (bright and bluer than red) does not count. Per lens and second: `cover` (the largest connected patch of flat non-sky cells as a share of the circle: a thumb is 0.1 to 0.3, a whole-lens blockage near 1), `flat` (all flat non-sky cells), `dark` (share of the circle under luma 20), `glare` (share over 250) and `soft` (share of textured cells that are blurred: fine detail small against mid detail, the look of water drops). `blocked(doc)` turns them into the 0 to 1 per-second signal the candidates stage uses: 1 where one lens is mostly covered, rising from 0 at a cover of 0.12.

Output `lens_check.json`: `hz`, `lenses` (['front', 'rear']), and per lens a list of rows [cover, flat, dark, glare, soft]."""
import subprocess

import numpy as np, cv2
from scipy import ndimage

from strata360 import hw
from strata360.pipeline import guard

SIZE, GRID = 480, 12
RADIUS = 0.42 * SIZE                      # inside the black rim of the circle
FLAT_FINE = 1.6                           # mean |g - blur(g, 1)| in 8-bit units below which a cell has no detail
COVER_FROM, COVER_FULL = 0.12, 0.5        # a patch this big starts to count, and counts fully at this size
FILE = 'lens_check.json'
LENSES = ('front', 'rear')                # osv streams 1 and 0 (master is the front lens)


def _mask():
    ys, xs = np.mgrid[:SIZE, :SIZE]
    return (xs - SIZE / 2 + 0.5) ** 2 + (ys - SIZE / 2 + 0.5) ** 2 <= RADIUS ** 2


_MASK = _mask()
_CELL = SIZE // GRID
_INSIDE = _MASK.reshape(GRID, _CELL, GRID, _CELL).mean((1, 3)) > 0.9      # cells wholly inside the circle


def _cells(a): return a.reshape(GRID, _CELL, GRID, _CELL).mean((1, 3))


def measure(img):
    """[cover, flat, dark, glare, soft] (each 0..1) for one BGR 480 x 480 lens picture."""
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32); b1 = cv2.GaussianBlur(g, (0, 0), 1.0); b4 = cv2.GaussianBlur(g, (0, 0), 4.0)
    fine, mid = _cells(np.abs(g - b1)), _cells(np.abs(b1 - b4)); luma = _cells(g)
    bgr = [_cells(img[..., c].astype(np.float32)) for c in range(3)]
    sky = (luma > 110) & (bgr[0] > bgr[2] + 8)
    flat = (fine < FLAT_FINE) & ~sky & _INSIDE
    lab, n = ndimage.label(flat)
    biggest = max((int((lab == i).sum()) for i in range(1, n + 1)), default=0)
    total = max(int(_INSIDE.sum()), 1)
    textured = _INSIDE & ~flat & (fine >= FLAT_FINE)
    soft = float(((fine / (mid + 1.0) < 0.2) & textured).sum() / max(int(textured.sum()), 1)) if textured.any() else 0.0
    px = _MASK.sum()
    return [biggest / total, float(flat.sum()) / total, float(((g < 20) & _MASK).sum() / px), float(((g > 250) & _MASK).sum() / px), soft]


def blocked(doc, t):
    """Per-time array (seconds `t`, cell centres) of 0..1: how much one of the lenses is covered."""
    t = np.asarray(t, float)
    if not doc or not doc.get('lenses'): return np.zeros(len(t))
    hz = float(doc.get('hz', 1.0)); best = np.zeros(len(t))
    for rows in doc['lenses'].values():
        if not rows: continue
        cover = np.array([r[0] for r in rows], float); ts = (np.arange(len(cover)) + 0.5) / hz
        s = np.clip((cover - COVER_FROM) / (COVER_FULL - COVER_FROM), 0, 1)
        best = np.maximum(best, np.interp(t, ts, s))
    return best


def frames(osv, stream, hz=1.0):
    """BGR 480 x 480 pictures of one lens stream at `hz` a second, one at a time."""
    cmd = ['ffmpeg', '-v', 'error', *hw.hwaccel_args(), '-i', osv, '-map', f'0:v:{stream}', '-an', '-vf', f'fps={hz:g},scale={SIZE}:{SIZE}:flags=area', '-pix_fmt', 'bgr24', '-f', 'rawvideo', '-']
    p = guard.popen(cmd, stdout=subprocess.PIPE, bufsize=SIZE * SIZE * 3 * 4); n = SIZE * SIZE * 3
    try:
        while True:
            b = p.stdout.read(n)
            if len(b) < n: break
            yield np.frombuffer(b, np.uint8).reshape(SIZE, SIZE, 3)
    finally:
        p.stdout.close(); p.wait()


def analyse(osv, hz=1.0):
    """The `lens_check.json` document for a clip's .OSV. Raises RuntimeError when a lens gave no frames."""
    out = {}
    for name, stream in (('front', 1), ('rear', 0)):
        rows = [measure(img) for img in frames(osv, stream, hz)]
        if not rows: raise RuntimeError(f'no frames could be read from lens stream {stream} of {osv}')
        out[name] = [[round(v, 3) for v in r] for r in rows]
    return dict(hz=float(hz), lenses=out, columns=['cover', 'flat', 'dark', 'glare', 'soft'])
