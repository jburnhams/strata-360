import sys, os, math, json
import numpy as np, cv2
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import scanlib as L
from strata360.analysis import views as VW
from ultralytics import YOLOE
from adapt import SMALL
S = L.S
SNOW = ['snow', 'snowy ground', 'snow field', 'ice', 'frost']; WATER = ['river', 'stream', 'rapids', 'lake', 'water', 'waterfall', 'weir', 'puddle']
TRUTH = {'0016@14.0': 'snow', '0012@12.0': 'snow', '0017@14.0': 'snow', '0018@40.6': 'snow patches + river', '0009@12.0': 'lake + weir', '0020@6.0': 'stream', '0019@2.0': 'stream',
         '0013@1.8': '-', '0013@3.1': '-', '0002@1.6': '-', '0010@16.0': '-', '0023@100.0': '-', '0014@20.0': '-', '0021@30.0': '-'}
tx = YOLOE(S + '/yw/yoloe-26s-seg.pt'); terms = SMALL + [w for w in SNOW + WATER if w not in SMALL]; tx.set_classes(terms, tx.get_text_pe(terms))
def tiles_of(clip, t):
    out = []; cr = None
    for k, (lat0, lon0) in enumerate(L.TILES):
        p = f'{S}/tiles/{clip}_{t}_{k}.jpg'
        if not os.path.exists(p):
            if cr is None: cr = VW.CropRenderer(L.osv_of(clip))
            cv2.imwrite(p, cr.crop(t, math.radians(lon0), math.radians(lat0), L.TFOV, L.TPX)[:, :, ::-1], [cv2.IMWRITE_JPEG_QUALITY, 95])
        out.append(p)
    return out
res = {}
for key, truth in TRUTH.items():
    clip, t = key.split('@'); t = float(t); cov = {w: np.zeros(26) for w in SNOW + WATER}
    for k, p in enumerate(tiles_of(clip, t)):
        r = tx.predict(p, imgsz=1024, conf=0.25, iou=0.5, agnostic_nms=False, device='mps', verbose=False)[0]
        for w in cov:
            m = np.zeros((256, 256), np.uint8)
            for j in range(len(r.boxes)):
                if tx.names[int(r.boxes.cls[j])] == w: b = (r.boxes.xyxy[j].cpu().numpy() / 4).astype(int); m[b[1]:b[3], b[0]:b[2]] = 1
            cov[w][k] = m.mean()
    res[key] = {w: [round(float(x), 3) for x in v] for w, v in cov.items()}; print(key, 'done', flush=True)
json.dump(res, open(S + '/area_check.json', 'w'))
def row(group, ws):
    print(f'\n== {group}: number of tiles (of 26) where the term covers at least 10% of the tile, at confidence 0.25')
    print(f"{'frame':11} {'truth':22} " + ' '.join(f'{w[:12]:>12}' for w in ws))
    for key, truth in TRUTH.items(): print(f"{key:11} {truth:22} " + ' '.join(f"{int((np.array(res[key][w]) >= 0.10).sum()):12d}" for w in ws))
row('SNOW', SNOW); row('WATER', WATER); print('done')
