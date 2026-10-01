"""The selfie-stick mask: the stored 14-point arc must be closed outward to the rim (as OpenOSV does), not filled as it is. Run: .venv/bin/python tests/test_occlusion.py"""
import os, sys
import numpy as np, cv2
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))
from strata360.render import photo as ph

CX, CY, RIM = 1909.0, 1912.0, 1890.0
ARC = [(90, 1823), (150, 1845), (140, 1827), (130, 1815), (120, 1817), (110, 1819), (100, 1821), (90, 1823), (80, 1825), (70, 1827), (60, 1828), (50, 1828), (40, 1844), (30, 1864)]        # the real master lens (angle deg, radius px)
PX = np.array([CX + r * np.cos(np.radians(a)) for a, r in ARC]); PY = np.array([CY + r * np.sin(np.radians(a)) for a, r in ARC])


def crossings(poly):
    n = len(poly); k = 0
    def ccw(a, b, c): return (c[1] - a[1]) * (b[0] - a[0]) > (b[1] - a[1]) * (c[0] - a[0])
    for i in range(n):
        for j in range(i + 2, n):
            if i == 0 and j == n - 1: continue
            a, b, c, d = poly[i], poly[(i + 1) % n], poly[j], poly[(j + 1) % n]
            if ccw(a, c, d) != ccw(b, c, d) and ccw(a, b, c) != ccw(a, b, d): k += 1
    return k


def test_the_closed_outward_polygon_is_simple_and_has_the_arc_and_the_rim_points():
    poly = ph.occlusion_polygon(PX, PY, CX, CY, RIM)
    assert crossings(poly) == 0 and len(poly) == 2 * 13                                    # the apex is stored twice: 13 distinct points on the arc, 13 more along the rim
    assert np.allclose(np.hypot(poly[13:, 0] - CX, poly[13:, 1] - CY), max(RIM, 1.02 * max(r for _, r in ARC)), atol=1.0) and np.all(np.diff(np.arctan2(poly[:13, 1] - CY, poly[:13, 0] - CX)) > 0)       # the rim points are on the rim; the arc is in angular order


def test_the_mask_covers_the_sliver_between_the_arc_and_the_rim_and_nothing_else():
    m = ph.occlusion_map(PX, PY, centre=(CX, CY), rim=RIM); at = lambda a, r: float(m[int((CY + r * np.sin(np.radians(a))) * 0.5), int((CX + r * np.cos(np.radians(a))) * 0.5)])
    assert at(90, 1850) == 0.0 and at(60, 1855) == 0.0 and at(120, 1850) == 0.0                # the stick, between the arc (about 1820) and the rim (1890)
    assert at(90, 1700) == 1.0 and at(0, 1850) == 1.0 and at(270, 1850) == 1.0 and m[int(CY * 0.5), int(CX * 0.5)] == 1.0          # picture above the arc, other sides, the centre: untouched
    share = float((m == 0).mean()); raw = np.zeros((1920, 1920), np.uint8); cv2.fillPoly(raw, [(np.stack([PX, PY], 1) * 0.5).astype(np.int32).reshape(-1, 1, 2)], 255)
    assert 0.012 < share < 0.03 and share < 0.8 * float((raw > 0).mean())                      # about 2% of the frame; the raw fill took 3.7% (the wrong 3.7%)


if __name__ == '__main__':
    fns = [v for k, v in sorted(globals().items()) if k.startswith('test_')]; bad = 0
    for fn in fns:
        try: fn(); print('ok  ', fn.__name__)
        except Exception as e: bad += 1; print('FAIL', fn.__name__, repr(e)[:300])
    print(f'{len(fns) - bad}/{len(fns)} passed'); sys.exit(bad)
