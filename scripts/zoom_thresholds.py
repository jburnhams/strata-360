"""How many shots and seconds of the plan's footage an enlarging rule would touch: a whole shot is enlarged when more than MIN_S seconds of it need at least the threshold zoom (zoom = output pixels a degree at the film's width over the camera's native pixels a degree). Usage: zoom_thresholds.py FOLDER [thresholds...]"""
import os, sys, numpy as np
from strata360.edit import framing as FR, project as PJ, upscale as UP
from strata360.render import camera as cam
from strata360.analysis.views import NATIVE_PPD
from strata360.pipeline import config
F = sys.argv[1]; thr = [float(x) for x in sys.argv[2:]] or [2.0, 2.25, 2.5, 2.75, 3.0]; W = 3840; MIN_S = 0.5; FPS = 50
SEC_PER_MP = 17.0 / 2.07                                                          # RealPLKSR on this Mac: 17 s for a 1080p picture (2.07 MP), scaled by the input's pixels
plan = PJ.load(F)['plan']; fr = FR.resolve(F, plan, head=True); rows = []
for g in plan['segments']:
    if g.get('synthetic'): continue
    p = cam.CameraPath.from_dict(fr[g['id']]); n = max(int(g['dur_s'] * 20), 2); ts = np.linspace(0, g['dur_s'], n)
    fov = np.interp(ts, p.t, p.fov) if len(p.t) > 1 else np.full(n, p.fov[0]); z = (W / fov) / NATIVE_PPD; dt = g['dur_s'] / (n - 1)
    night = bool(UP.skip_reason(os.path.join(config.race_dir(F), 'clips', g['clip']))); rows.append((g['dur_s'], z, night, UP.factor_for(NATIVE_PPD, W, float(p.fov.min()))))
tot_s = sum(r[0] for r in rows); print(f'{len(rows)} footage shots, {tot_s:.1f} s ({tot_s * FPS:.0f} frames at {FPS} fps); night shots are never enlarged\n')
print(f'{"threshold":>9} {"shots":>6} {"seconds":>8} {"share":>6} {"frames":>7} {"night skipped":>14} {"est. hours (Mac, RealPLKSR)":>28}')
for t in thr:
    sel = [r for r in rows if not r[2] and (r[1] >= t).sum() * (r[0] / (len(r[1]) - 1)) > MIN_S]; sk = [r for r in rows if r[2] and (r[1] >= t).sum() * (r[0] / (len(r[1]) - 1)) > MIN_S]
    s = sum(r[0] for r in sel); frames = s * FPS; hours = sum(r[0] * FPS * SEC_PER_MP * (W // r[3] * (W // r[3]) * 9 / 16) / 1e6 for r in sel) / 3600
    print(f'{t:>9.2f} {len(sel):>6} {s:>8.1f} {s / tot_s:>6.0%} {frames:>7.0f} {len(sk):>14} {hours:>28.1f}')
