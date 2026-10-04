import sys, os, glob, json, math, re, time, random
import numpy as np, cv2
from ultralytics import YOLOE
from strata360.analysis import views as VW
S = os.path.dirname(os.path.abspath(__file__)); D = "/Volumes/Expansion/2026-02-19 - Legends"; CL = D + "/strata360/clips"; OUT = S + '/scan'; os.makedirs(OUT, exist_ok=True)
FRAMES = [('0013', 1.8), ('0013', 3.1), ('0016', 14.0), ('0009', 12.0), ('0018', 40.6), ('0002', 1.6)]
WORN = ['person', 'backpack', 'helmet', 'hat', 'glove', 'jacket']
ANIMALS = ['chicken', 'duck', 'goat', 'pig', 'sheep', 'cow', 'bird', 'animal']
COMMON = ['tree', 'river', 'mountain', 'hill', 'road', 'path', 'building', 'house', 'car', 'fence', 'bridge', 'field', 'rock', 'snow', 'water', 'bush', 'grass', 'pole', 'sign', 'wall', 'forest']
NAMED = WORN + COMMON + ANIMALS
PERSONISH = ('person', 'hat', 'helmet', 'backpack', 'glove', 'glass', 'jacket', 'hand', 'face', 'man', 'woman', 'runner', 'head', 'hair')
RINGS = [(-90, [0.0]), (-55, list(np.arange(0, 360, 60.0))), (-20, list(np.linspace(0, 360, 7, endpoint=False))), (15, list(np.linspace(0, 360, 7, endpoint=False))), (50, list(np.linspace(0, 360, 5, endpoint=False)))]
TFOV, TPX = 60.0, 1024; PPD = TPX / (2 * math.degrees(math.tan(math.radians(TFOV / 2))))        # pixels per degree at the middle of a tile (about 17)
tx = YOLOE(S + '/yw/yoloe-26s-seg.pt'); tx.set_classes(NAMED, tx.get_text_pe(NAMED)); pf = YOLOE(S + '/yw/yoloe-26s-seg-pf.pt')
def preds(model, img, conf):
    r = model.predict(img, imgsz=1024, conf=conf, iou=0.5, agnostic_nms=True, device='mps', verbose=False)[0]
    return [(model.names[int(r.boxes.cls[j])], float(r.boxes.conf[j]), [float(z) for z in r.boxes.xyxy[j]]) for j in range(len(r.boxes))]
def inside(a, b): return max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1])) / max(1, (a[2] - a[0]) * (a[3] - a[1]))
def iou(a, b):
    i = max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1])); return i / max(1, (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - i)
def angdist(a, b):
    la, lb = math.radians(a[0]), math.radians(b[0]); pa, pb = math.radians(a[1]), math.radians(b[1])
    return math.degrees(math.acos(float(np.clip(math.sin(pa) * math.sin(pb) + math.cos(pa) * math.cos(pb) * math.cos(la - lb), -1, 1))))
def lonlat(d): return math.degrees(math.atan2(d[0], d[1])), math.degrees(math.asin(float(np.clip(d[2], -1, 1))))
allc = []; t0 = time.time(); renderers = {}
for clip, t in FRAMES:
    cdir = glob.glob(f'{CL}/CAM_*_{clip}_D')[0]; osv = D + '/' + os.path.basename(cdir) + '.OSV'
    if clip not in renderers: renderers[clip] = VW.CropRenderer(osv)
    cr = renderers[clip]; foc = [s for s in json.load(open(cdir + '/focus.json'))['samples'] if abs(s['t'] - t) <= 1.0]
    q = np.load(cdir + '/quality_grid.npz'); tex = q['tex'].astype(np.float32); gi = int(np.clip(round(t * float(q['hz'])), 0, len(tex) - 1)); tex_p25 = float(np.percentile(tex, 25))
    cands = []
    for lat0, lons in RINGS:
        for lon0 in lons:
            img = cr.crop(t, math.radians(lon0), math.radians(lat0), TFOV, TPX)[:, :, ::-1].copy(); rays = VW.crop_rays(math.radians(lon0), math.radians(lat0), TFOV, TPX)
            named = preds(tx, img, 0.10); strong = [n for n in named if n[1] >= 0.25 or n[0] in ANIMALS]
            pr = [p for p in preds(pf, img, 0.30) if not any(k in p[0].lower() for k in PERSONISH)]
            cover = [n for n in named if n[1] >= 0.25]
            resid = [p for p in pr if not any(inside(p[2], n[2]) >= 0.5 for n in cover)]
            for kind, lst in (('other', resid), ('animal', [n for n in named if n[0] in ANIMALS and n[1] >= 0.10])):
                for lab, cf, b in lst:
                    w, h = b[2] - b[0], b[3] - b[1]
                    if min(w, h) < 8 or w * h > 0.25 * TPX * TPX: continue
                    cx, cy = int((b[0] + b[2]) / 2), int((b[1] + b[3]) / 2); lon, lat = lonlat(rays[min(cy, TPX - 1), min(cx, TPX - 1)])
                    cands.append(dict(kind=kind, yoloe=lab, conf=cf, lon=lon, lat=lat, deg=max(w, h) / PPD, tile=(lat0, lon0)))
            cands.extend([dict(kind='person', yoloe=n[0], conf=n[1], lon=lonlat(rays[min(int((n[2][1] + n[2][3]) / 2), TPX - 1), min(int((n[2][0] + n[2][2]) / 2), TPX - 1)])[0], lat=lonlat(rays[min(int((n[2][1] + n[2][3]) / 2), TPX - 1), min(int((n[2][0] + n[2][2]) / 2), TPX - 1)])[1], deg=max(n[2][2] - n[2][0], n[2][3] - n[2][1]) / PPD, tile=(lat0, lon0)) for n in named if n[0] in WORN and n[1] >= 0.25])
    # one candidate per object: the same thing is found by neighbouring tiles
    cands.sort(key=lambda c: -c['conf']); kept = []
    for c in cands:
        if any(angdist((c['lon'], c['lat']), (k['lon'], k['lat'])) < max(1.5, 0.4 * max(c['deg'], k['deg'])) and (c['kind'] == k['kind'] or 'person' in (c['kind'], k['kind'])) for k in kept): continue
        kept.append(c)
    people = [c for c in kept if c['kind'] == 'person']; cand = [c for c in kept if c['kind'] != 'person']
    for c in cand:
        # filter 1: the wearer (focus.json: the direction of the wearer, world frame) and the people YOLOE named
        c['f_wearer'] = bool(any(angdist((c['lon'], c['lat']), (s['yaw'] if s['yaw'] <= 180 else s['yaw'] - 360, s['pitch'])) < max((s.get('height') or 40) / 2, 12) + 8 for s in foc)) or any(angdist((c['lon'], c['lat']), (p['lon'], p['lat'])) < p['deg'] * 0.6 for p in people)
        # filter 2: the quality grid says this direction is featureless
        row = int(np.clip((90 - c['lat']) / 15, 0, 11)); col = int(((c['lon'] + 180) / 15) % 24); c['grid_tex'] = float(tex[gi, row, col]); c['f_flat_grid'] = c['grid_tex'] < tex_p25
        # a zoomed render around the box (also the picture Qwen gets), a second YOLOE look, and the texture inside the box
        fov = float(np.clip(c['deg'] * 2.5, 8, 40)); z = cr.crop(t, math.radians(c['lon']), math.radians(c['lat']), fov, 640)[:, :, ::-1].copy(); c['fov'] = fov
        exp = [640 * 0.3, 640 * 0.3, 640 * 0.7, 640 * 0.7]; got = [p for p in preds(pf, z, 0.25) + [n for n in preds(tx, z, 0.20) if n[0] not in WORN] if not any(k in p[0].lower() for k in PERSONISH)]
        c['verified'] = any(iou(p[2], exp) >= 0.3 for p in got); c['f_verify'] = not c['verified']
        g = cv2.cvtColor(z[192:448, 192:448], cv2.COLOR_BGR2GRAY).astype(np.float32); c['local_std'] = float(g.std()); c['local_edge'] = float(np.abs(cv2.Laplacian(g, cv2.CV_32F)).mean()); c['f_flat_local'] = c['local_edge'] < 4.0
        p = f'{OUT}/{clip}_{t}_{len(os.listdir(OUT))}.jpg'; cv2.imwrite(p, z); c['img'] = p
    allc.append(dict(clip=clip, t=t, n_people=len(people), cands=cand)); n = len(cand)
    cnt = lambda k: sum(c[k] for c in cand)
    print(f'{clip} t={t}: tiles {sum(len(l) for _, l in RINGS)}, {len(people)} people/gear, {n} candidates | wearer {cnt("f_wearer")} flat_grid {cnt("f_flat_grid")} flat_local {cnt("f_flat_local")} verify_fail {cnt("f_verify")} | left after all: {sum(not(c["f_wearer"] or c["f_flat_grid"] or c["f_verify"]) for c in cand)} ({time.time()-t0:.0f}s)', flush=True)
json.dump(allc, open(OUT + '/cands.json', 'w'), indent=1); print('done')
