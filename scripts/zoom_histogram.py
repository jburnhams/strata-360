import os, json, numpy as np
import matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt
from strata360.edit import framing as FR, project as PJ, upscale as UP, pointcam as PCM, pointcam_clip as PK
from strata360.render import camera as cam
from strata360.analysis.views import NATIVE_PPD
from strata360.pipeline import config
F = "/Volumes/Expansion/2026-02-19 - Legends"; W = 3840; HI, STD = 21.33, 10.67
plan = PJ.load(F)['plan']; fr = FR.resolve(F, plan, head=True); rd = config.race_dir(F)
foot_shot, foot_sec = [], []; samples = []; w_s = []
for g in plan['segments']:
    if g.get('synthetic'): continue
    if UP.skip_reason(os.path.join(rd, 'clips', g['clip'])): night = True
    else: night = False
    p = cam.CameraPath.from_dict(fr[g['id']]); z = lambda fov: (W / fov) / NATIVE_PPD
    foot_shot.append((z(float(p.fov.min())), g['dur_s'], night))
    ts = np.linspace(p.t[0], p.t[-1], 40) if len(p.t) > 1 and p.t[-1] > p.t[0] else np.array([p.t[0]])
    fv = np.interp(ts, p.t, p.fov); samples += [z(f) for f in fv]; w_s += [g['dur_s'] / len(fv)] * len(fv)
# street view: the chosen section's own clip (85 degrees) and the point camera (its fov along the path)
sv_shot, sv_samples, sv_w = [], [], []
ch = json.load(open(f'{rd}/streetview/choices.json')); hires = ch.get('hires') or {}
for key, how in (ch.get('choices') or {}).items():
    ppd = HI if hires.get(key) else STD; sv_shot.append(('section ' + key, (W / 85.0) / ppd, 'fov 85'))
    sv_samples += [(W / 85.0) / ppd]; sv_w += [1.0]
for c in PCM.load(rd)['cams']:
    if c['source']['kind'] != 'streetview': continue
    try: pl = PK.plan(F, c)
    except Exception as e: print('pointcam', c['id'], e); continue
    ppd = HI if hires.get(c['source']['key']) else STD; fv = np.array(pl['samples']['fov']); zz = (W / fv) / ppd
    sv_shot.append(('point camera ' + c['id'], float(zz.max()), f'fov {fv.min():.0f}-{fv.max():.0f}')); sv_samples += list(zz); sv_w += [pl['seconds'] / len(zz)] * len(zz)
bins = np.arange(0.5, 7.01, 0.25)
shot_h, _ = np.histogram([s[0] for s in foot_shot], bins); sec_h, _ = np.histogram(samples, bins, weights=w_s)
night_h, _ = np.histogram([s[0] for s in foot_shot if s[2]], bins)
sv_h, _ = np.histogram(sv_samples, bins, weights=sv_w)
fig, ax = plt.subplots(3, 1, figsize=(11, 10), sharex=True); xc = bins[:-1]
ax[0].bar(xc, shot_h, 0.23, align='edge', color='#3b6ea5', label='shots'); ax[0].bar(xc, night_h, 0.23, align='edge', color='#555', label='of which night (not enlarged)'); ax[0].set_ylabel('footage shots'); ax[0].legend(); ax[0].set_title('Legends film at 4K: zoom needed (output pixels per degree / the camera\'s 20 per degree), 0.25x bins')
ax[1].bar(xc, sec_h, 0.23, align='edge', color='#c0662b'); ax[1].set_ylabel('footage seconds (moments)')
ax[2].bar(xc, sv_h, 0.23, align='edge', color='#2d8a5b'); ax[2].set_ylabel('street view seconds'); ax[2].set_xlabel('zoom: how many times the source must be enlarged (1.0 = enough pixels)')
for a in ax: a.axvline(1.5, color='#999', ls=':'); a.grid(axis='y', alpha=.3)
plt.tight_layout(); plt.savefig(f'{os.environ["S"]}/zoom_hist.png', dpi=110)
print('footage shots:', len(foot_shot), 'seconds', round(sum(s[1] for s in foot_shot), 1))
print('shots by zoom bin:', {round(b, 2): int(n) for b, n in zip(xc, shot_h) if n})
print('seconds by zoom bin:', {round(b, 2): round(float(n), 1) for b, n in zip(xc, sec_h) if n})
print('street view:', sv_shot); print('sv seconds by bin:', {round(b, 2): round(float(n), 1) for b, n in zip(xc, sv_h) if n})
tot = sum(sec_h); print('share of footage seconds needing >=1.5x:', round(float(sec_h[xc >= 1.5].sum() / tot), 3), ' >=2x:', round(float(sec_h[xc >= 2].sum() / tot), 3), ' >=2.75x:', round(float(sec_h[xc >= 2.75].sum() / tot), 3))
