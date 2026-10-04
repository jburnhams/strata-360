"""Shared pieces of the dense-scan experiments: frame selection, the 26-tile scan of one moment, tile thumbnails."""
import os, glob, json, math, datetime
import numpy as np, cv2
S = os.path.dirname(os.path.abspath(__file__)); D = "/Volumes/Expansion/2026-02-19 - Legends"; CL = D + "/strata360/clips"
WORN = ['person', 'backpack', 'helmet', 'hat', 'glove', 'jacket']
ANIMALS = ['chicken', 'duck', 'goat', 'pig', 'sheep', 'cow', 'bird', 'animal']
COMMON = ['tree', 'river', 'mountain', 'hill', 'road', 'path', 'building', 'house', 'car', 'fence', 'bridge', 'field', 'rock', 'snow', 'water', 'bush', 'grass', 'pole', 'sign', 'wall', 'forest']
NAMED = WORN + COMMON + ANIMALS
PERSONISH = ('person', 'hat', 'helmet', 'backpack', 'glove', 'glass', 'jacket', 'hand', 'face', 'man', 'woman', 'runner', 'head', 'hair')
RINGS = [(-90, [0.0]), (-55, list(np.arange(0, 360, 60.0))), (-20, list(np.linspace(0, 360, 7, endpoint=False))), (15, list(np.linspace(0, 360, 7, endpoint=False))), (50, list(np.linspace(0, 360, 5, endpoint=False)))]
TILES = [(lat0, lon0) for lat0, lons in RINGS for lon0 in lons]
TFOV, TPX = 60.0, 1024; PPD = TPX / (2 * math.degrees(math.tan(math.radians(TFOV / 2))))
def clip_dir(c): return glob.glob(f'{CL}/CAM_*_{c}_D')[0]
def osv_of(c): return D + '/' + os.path.basename(clip_dir(c)) + '.OSV'
def iou(a, b):
    i = max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1])); return i / max(1, (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - i)
def inside(a, b): return max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1])) / max(1, (a[2] - a[0]) * (a[3] - a[1]))
def angdist(a, b):
    la, lb = math.radians(a[0]), math.radians(b[0]); pa, pb = math.radians(a[1]), math.radians(b[1])
    return math.degrees(math.acos(float(np.clip(math.sin(pa) * math.sin(pb) + math.cos(pa) * math.cos(pb) * math.cos(la - lb), -1, 1))))
def lonlat(d): return math.degrees(math.atan2(d[0], d[1])), math.degrees(math.asin(float(np.clip(d[2], -1, 1))))
# ---- which frames: movement and change -------------------------------------------------------------------------------------------------------------------------------------
def select_frames(c, dist_m=5.0, mingap=1.0, maxgap=10.0, change_x=1.5, sharp_back=1.5):
    """Times (s) to scan: a new frame once the runner has moved `dist_m` metres or the scene has changed (the world-locked luma and detail grids of quality_grid.npz) by `change_x` times its usual change over 4 s,
    never later than `maxgap` seconds; the trigger frame is swapped for the sharpest frame (the `blur` channel) of the `sharp_back` seconds before it."""
    d = clip_dir(c); tr = np.load(f'{S}/../../../../../../Volumes/Expansion/2026-02-19 - Legends/strata360/track.fit.npz') if False else np.load(D + '/strata360/track.fit.npz')
    T, SP = tr['t'], np.nan_to_num(tr['speed'], nan=0.0); cj = json.load(open(d + '/clip.json')); su = cj.get('start_utc') or json.load(open(d + '/exposure.json'))['start_utc']
    t0 = datetime.datetime.fromisoformat(su.replace('Z', '+00:00')).timestamp(); q = np.load(d + '/quality_grid.npz'); hz = float(q['hz']); n = len(q['luma'])
    g = np.concatenate([q['luma'].astype(np.float32).reshape(n, -1) / (float(q['luma'].max()) or 1), q['fine'].astype(np.float32).reshape(n, -1) / (float(q['fine'].max()) or 1)], 1)
    sharp = np.nan_to_num(q['blur'].astype(np.float32).reshape(n, -1).mean(1)); sp = np.interp(t0 + np.arange(n) / hz, T, SP); dist = np.cumsum(sp / hz); k = int(4 * hz)
    typ = float(np.median([np.abs(g[i + k] - g[i]).mean() for i in range(0, max(1, n - k), k)])) if n > k else 1.0
    sel = [0]
    for i in range(1, n):
        last = sel[-1]
        if (i - last) / hz < mingap: continue
        if dist[i] - dist[last] >= dist_m or np.abs(g[i] - g[last]).mean() >= change_x * typ or (i - last) / hz >= maxgap:
            lo = max(last + int(mingap * hz), i - int(sharp_back * hz)); j = lo + int(np.argmax(sharp[lo:i + 1])); sel.append(j if j > last else i)
    return [round(i / hz, 2) for i in sel], dict(speed=float(sp.mean()), dur=n / hz, typ=typ)
# ---- one moment: the tiles ---------------------------------------------------------------------------------------------------------------------------------------------------
_rays = {}
def tile_rays(lat0, lon0, px):
    k = (lat0, lon0, px)
    if k not in _rays: _rays[k] = VWmod.crop_rays(math.radians(lon0), math.radians(lat0), TFOV, px)
    return _rays[k]
def tile_thumb(eq, lat0, lon0, px=160):
    d = tile_rays(lat0, lon0, px); mx = (((np.arctan2(d[..., 0], d[..., 1])) / np.pi + 1) / 2 * eq.shape[1]).astype(np.float32); my = ((0.5 - np.arcsin(np.clip(d[..., 2], -1, 1)) / np.pi) * eq.shape[0]).astype(np.float32)
    return cv2.GaussianBlur(cv2.cvtColor(cv2.remap(eq, mx, my, cv2.INTER_AREA), cv2.COLOR_BGR2GRAY), (0, 0), 1.5)
def scan_moment(cr, t, tx, pf, foc, tiles=TILES):
    """Candidates of one moment (no labelling): [{kind other|animal, yoloe, conf, lon, lat, deg, tile, wearer}], plus the people/gear boxes found."""
    def preds(model, img, conf):
        r = model.predict(img, imgsz=1024, conf=conf, iou=0.5, agnostic_nms=True, device='mps', verbose=False)[0]
        return [(model.names[int(r.boxes.cls[j])], float(r.boxes.conf[j]), [float(z) for z in r.boxes.xyxy[j]]) for j in range(len(r.boxes))]
    cands = []; people = []
    for (lat0, lon0) in tiles:
        img = cr.crop(t, math.radians(lon0), math.radians(lat0), TFOV, TPX)[:, :, ::-1].copy(); rays = tile_rays(lat0, lon0, TPX)
        named = preds(tx, img, 0.10); cover = [n for n in named if n[1] >= 0.25]
        pr = [p for p in preds(pf, img, 0.30) if not any(k in p[0].lower() for k in PERSONISH)]; resid = [p for p in pr if not any(inside(p[2], n[2]) >= 0.5 for n in cover)]
        at = lambda b: lonlat(rays[min(int((b[1] + b[3]) / 2), TPX - 1), min(int((b[0] + b[2]) / 2), TPX - 1)])
        for kind, lst in (('other', resid), ('animal', [n for n in named if n[0] in ANIMALS and n[1] >= 0.10])):
            for lab, cf, b in lst:
                w, h = b[2] - b[0], b[3] - b[1]
                if min(w, h) < 8 or w * h > 0.25 * TPX * TPX: continue
                lo, la = at(b); cands.append(dict(kind=kind, yoloe=lab, conf=cf, lon=lo, lat=la, deg=max(w, h) / PPD, tile=(lat0, lon0)))
        for n in named:
            if n[0] in WORN and n[1] >= 0.25: lo, la = at(n[2]); people.append(dict(lon=lo, lat=la, deg=max(n[2][2] - n[2][0], n[2][3] - n[2][1]) / PPD))
    cands.sort(key=lambda c: -c['conf']); kept = []
    for c in cands:
        if any(angdist((c['lon'], c['lat']), (k['lon'], k['lat'])) < max(1.5, 0.4 * max(c['deg'], k['deg'])) for k in kept): continue
        kept.append(c)
    for c in kept:
        c['wearer'] = bool(any(angdist((c['lon'], c['lat']), (s['yaw'] if s['yaw'] <= 180 else s['yaw'] - 360, s['pitch'])) < max((s.get('height') or 40) / 2, 12) + 8 for s in foc)) or any(angdist((c['lon'], c['lat']), (p['lon'], p['lat'])) < p['deg'] * 0.6 for p in people)
    return kept, people
from strata360.analysis import views as VWmod
