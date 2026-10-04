import sys, os, json, cv2, numpy as np
S = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, S); from terms import TERMS
from ultralytics import YOLOE
EX = [('0013', '0001.8', 240), ('0013', '0001.8', 300), ('0013', '0003.1', 300), ('0016', '0016.4', 0), ('0009', '0012.1', 0), ('0002', '0001.6', 60), ('0002', '0014.6', 60), ('0018', '0052.2', 0)]
PERSONISH = ('person', 'hat', 'helmet', 'backpack', 'glove', 'glass', 'jacket', 'hand', 'face', 'man', 'woman', 'runner', 'head', 'hair')
BROAD = ['object', 'animal', 'bird', 'building', 'structure', 'sign', 'vehicle', 'plant', 'tree', 'water', 'rock']
MID = ['animal', 'bird', 'farm animal', 'building', 'house', 'shed', 'fence', 'gate', 'wall', 'sign', 'bridge', 'boat', 'car', 'truck', 'tractor', 'bench', 'platform', 'table', 'tent', 'tower', 'pole', 'hedge', 'rock', 'tree stump', 'waterfall', 'portable toilet', 'container']
WORN = ['person', 'backpack', 'helmet', 'hat', 'glove', 'jacket']
COMMON = WORN + ['tree', 'river', 'mountain', 'hill', 'road', 'path', 'building', 'house', 'car', 'fence', 'bridge', 'field', 'rock', 'snow', 'water', 'bush', 'grass', 'pole', 'sign', 'wall', 'forest']
MODES = {'A prompt-free': None, 'B broad (11 words)': BROAD, 'C mid list (27)': MID, 'D our 50 terms': TERMS, 'E common+other': 'E'}
out = {}; sheets = {m: [] for m in MODES}
pf = YOLOE(S + '/yw/yoloe-26s-seg-pf.pt'); tx = YOLOE(S + '/yw/yoloe-26s-seg.pt')
def boxes(model, path, keep_worn=False):
    r = model.predict(path, imgsz=1024, conf=0.15, iou=0.5, agnostic_nms=True, device='mps', verbose=False)[0]; res = []
    for j in range(len(r.boxes)):
        lab = model.names[int(r.boxes.cls[j])]
        if not keep_worn and any(p in lab.lower() for p in PERSONISH): continue
        res.append(dict(label=lab, conf=round(float(r.boxes.conf[j]), 2), box=[round(float(z)) for z in r.boxes.xyxy[j]]))
    return res
cur = None
def inside(a, b):      # share of box a that lies inside box b
    w = max(0, min(a[2], b[2]) - max(a[0], b[0])); h = max(0, min(a[3], b[3]) - max(a[1], b[1])); return w * h / max(1, (a[2] - a[0]) * (a[3] - a[1]))
for mode, names in MODES.items():
    for clip, t, yaw in EX:
        p = f'{S}/bake/{clip}/{t}_yaw{yaw:03d}.jpg'; im = cv2.imread(p)
        if names == 'E':
            tx.set_classes(COMMON, tx.get_text_pe(COMMON)); lab = boxes(tx, p, keep_worn=True); pr = boxes(pf, p)
            other = [x for x in pr if not any(inside(x['box'], y['box']) >= 0.5 for y in lab)]
            b = [dict(x, kind='person' if x['label'] in WORN else 'named') for x in lab] + [dict(x, kind='other', label='?') for x in other]
        else:
            if names is None: model = pf
            else: tx.set_classes(names, tx.get_text_pe(names)); model = tx
            b = [dict(x, kind='named') for x in boxes(model, p)]
        out.setdefault(f'{clip}_{t}_y{yaw}', {})[mode] = b
        for x in b:
            q = x['box']; col = {'other': (0, 0, 255), 'person': (255, 128, 0)}.get(x['kind'], (0, 255, 0)); cv2.rectangle(im, (q[0], q[1]), (q[2], q[3]), col, 4); cv2.putText(im, x['label'][:14], (q[0] + 3, q[1] + 28), 0, 0.9, (0, 0, 0), 5); cv2.putText(im, x['label'][:14], (q[0] + 3, q[1] + 28), 0, 0.9, (0, 255, 255), 2)
        n_o = sum(x['kind'] == 'other' for x in b); cap = f'{mode}: {len(b)} boxes' + (f' ({n_o} to Qwen)' if names == 'E' else '')
        cv2.putText(im, cap, (10, 1010), 0, 1.4, (0, 0, 0), 8); cv2.putText(im, cap, (10, 1010), 0, 1.4, (255, 255, 255), 3)
        sheets[mode].append(cv2.resize(im, (380, 380)))
    print(mode, sum(len(out[k][mode]) for k in out), 'boxes', flush=True)
json.dump(out, open(S + '/yoloe_prompts.json', 'w'), indent=1)
rows = [np.hstack([sheets[m][i] for m in MODES]) for i in range(len(EX))]
cv2.imwrite(S + '/yoloe_prompts_1.jpg', np.vstack(rows[:4])); cv2.imwrite(S + '/yoloe_prompts_2.jpg', np.vstack(rows[4:])); print('done')
