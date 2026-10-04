import sys, os, json, math, time, glob
import numpy as np, cv2
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import scanlib as L
from strata360.analysis import views as VW
from ultralytics import YOLOE
S = L.S; os.makedirs(S + '/tiles', exist_ok=True)
FR = [('0013', 1.8), ('0013', 3.1), ('0016', 14.0), ('0009', 12.0), ('0018', 40.6), ('0002', 1.6)]
EXTRA = ['platform', 'container', 'hedge', 'signpost', 'street light', 'overhead wire', 'church', 'steeple', 'chimney', 'tractor', 'truck', 'van', 'bus', 'motorcycle', 'bicycle', 'boat', 'bench', 'bin', 'tent', 'banner', 'flag', 'gate', 'stairs', 'statue', 'tower', 'weir', 'waterfall', 'cabin', 'shed', 'barn', 'toilet', 'table', 'log', 'tree stump', 'boulder', 'cairn', 'puddle', 'railing']
SMALL = L.NAMED + EXTRA; BIG = L.WORN + sorted(set(json.load(open(S + '/vocab_big.json')) + L.COMMON + L.ANIMALS + EXTRA))
KEY = {'0013': ['chicken', 'duck', 'goat', 'pig', 'sheep', 'cow', 'bird', 'animal', 'hen', 'goose', 'turkey', 'fowl', 'rooster', 'poultry', 'rabbit', 'partridge'], '0016': ['platform', 'bench', 'deck', 'bridge', 'pier', 'dock', 'table', 'stage'],
       '0009': ['bridge', 'weir', 'dam', 'waterfall', 'railing', 'rail', 'fence'], '0002': ['toilet', 'container', 'cabin', 'sign'], '0018': ['river', 'rapid', 'stream', 'waterfall', 'water']}
# 1. the tiles, rendered once
items = []
for clip, t in FR:
    cr = VW.CropRenderer(L.osv_of(clip))
    for k, (lat0, lon0) in enumerate(L.TILES):
        p = f'{S}/tiles/{clip}_{t}_{k}.jpg'
        if not os.path.exists(p): cv2.imwrite(p, cr.crop(t, math.radians(lon0), math.radians(lat0), L.TFOV, L.TPX)[:, :, ::-1], [cv2.IMWRITE_JPEG_QUALITY, 95])
        items.append((clip, t, k, p))
print('tiles', len(items), flush=True)
tx = YOLOE(S + '/yw/yoloe-26s-seg.pt'); pf = YOLOE(S + '/yw/yoloe-26s-seg-pf.pt')
def run(model, p, conf_fn):
    r = model.predict(p, imgsz=1024, conf=0.10, iou=0.5, agnostic_nms=True, device='mps', verbose=False)[0]; out = []
    for j in range(len(r.boxes)):
        lab = model.names[int(r.boxes.cls[j])]; cf = float(r.boxes.conf[j]); b = [float(z) for z in r.boxes.xyxy[j]]
        if cf < conf_fn(lab): continue
        w, h = b[2] - b[0], b[3] - b[1]
        if min(w, h) < 8 or w * h > 0.25 * L.TPX * L.TPX: continue
        out.append((lab, round(cf, 2), [round(z) for z in b]))
    return out
cfg_time = {}; res = {}
for name in ('A two models (35 words + prompt-free)', 'B text only, 35 + 38 extra words', 'C text only, ~1,100 curated words', 'D prompt-free only'):
    t0 = time.time(); res[name] = {}
    if name.startswith('B'): tx.set_classes(SMALL, tx.get_text_pe(SMALL))
    if name.startswith('C'): tx.set_classes(BIG, tx.get_text_pe(BIG))
    if name.startswith('A'): tx.set_classes(L.NAMED, tx.get_text_pe(L.NAMED))
    for clip, t, k, p in items:
        if name.startswith('D'): b = [x for x in run(pf, p, lambda l: 0.30)]
        else:
            nm = run(tx, p, lambda l: 0.10 if l in L.ANIMALS else 0.25)
            if name.startswith('A'):
                cover = [x for x in nm]; pr = run(pf, p, lambda l: 0.30); pr = [x for x in pr if not any(c in x[0].lower() for c in L.PERSONISH)]
                b = nm + [(('?' + x[0]), x[1], x[2]) for x in pr if not any(L.inside(x[2], n[2]) >= 0.5 for n in nm if n[1] >= 0.25)]
            else: b = nm
        res[name][f'{clip}_{t}_{k}'] = b
    cfg_time[name] = round((time.time() - t0) / len(items), 3); print(name, 'sec/tile', cfg_time[name], flush=True)
json.dump(dict(res=res, time=cfg_time), open(S + '/vocab_cmp.json', 'w'))
# 2. numbers
print('\nconfig | boxes per frame | person/gear boxes | boxes named by YOLOE | known objects found (any tile, label keyword)')
for name, r in res.items():
    tot = sum(len(v) for v in r.values()); person = sum(1 for v in r.values() for x in v if x[0] in L.WORN or any(c in x[0].lower() for c in L.PERSONISH)); named = sum(1 for v in r.values() for x in v if not x[0].startswith('?'))
    found = {}
    for clip, t in FR:
        kw = KEY.get(clip, []); found[f'{clip}@{t}'] = sum(1 for k2, v in r.items() if k2.startswith(f'{clip}_{t}_') for x in v if any(w in x[0].lower() for w in kw))
    print(f'{name[:38]:38} | {tot/len(FR):6.0f} | {person:4d} | {named:5d} | {found}')
# 3. one tile per config side by side: the pen (0013@1.8) and the aid station (0002@1.6)
for clip, t in (('0013', 1.8), ('0002', 1.6)):
    base = res['B text only, 35 + 38 extra words']; k = max(range(len(L.TILES)), key=lambda i: len(base[f'{clip}_{t}_{i}'])); tiles = []
    for name, r in res.items():
        im = cv2.imread(f'{S}/tiles/{clip}_{t}_{k}.jpg')
        for lab, cf, b in r[f'{clip}_{t}_{k}']:
            col = (0, 0, 255) if lab.startswith('?') else (255, 128, 0) if lab in L.WORN else (0, 255, 0); cv2.rectangle(im, (b[0], b[1]), (b[2], b[3]), col, 3); cv2.putText(im, lab[:16], (b[0] + 3, b[1] + 22), 0, 0.7, (0, 0, 0), 4); cv2.putText(im, lab[:16], (b[0] + 3, b[1] + 22), 0, 0.7, (0, 255, 255), 2)
        cap = name[:2] + f' {len(r[f"{clip}_{t}_{k}"])} boxes'; cv2.putText(im, cap, (10, 1000), 0, 1.5, (0, 0, 0), 8); cv2.putText(im, cap, (10, 1000), 0, 1.5, (255, 255, 255), 3); tiles.append(cv2.resize(im, (640, 640)))
    cv2.imwrite(f'{S}/vocab_cmp_{clip}.jpg', np.vstack([np.hstack(tiles[:2]), np.hstack(tiles[2:])]))
print('done')
