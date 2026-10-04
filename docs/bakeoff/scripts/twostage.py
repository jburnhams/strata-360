import sys, os, glob, json, time, math, re
import numpy as np, cv2
from ultralytics import YOLOE
from strata360.analysis import views as VW
from mlx_vlm import load, generate
from mlx_vlm.prompt_utils import apply_chat_template
from mlx_vlm.utils import load_config
S = os.path.dirname(os.path.abspath(__file__)); D = "/Volumes/Expansion/2026-02-19 - Legends"; CL = D + "/strata360/clips"
EX = [('0013', '0001.8', 240), ('0013', '0001.8', 300), ('0013', '0003.1', 300), ('0016', '0016.4', 0), ('0009', '0012.1', 0), ('0002', '0001.6', 60), ('0002', '0014.6', 60), ('0018', '0052.2', 0)]
WORN = ['person', 'backpack', 'helmet', 'hat', 'glove', 'jacket']
COMMON = WORN + ['tree', 'river', 'mountain', 'hill', 'road', 'path', 'building', 'house', 'car', 'fence', 'bridge', 'field', 'rock', 'snow', 'water', 'bush', 'grass', 'pole', 'sign', 'wall', 'forest']
PERSONISH = ('person', 'hat', 'helmet', 'backpack', 'glove', 'glass', 'jacket', 'hand', 'face', 'man', 'woman', 'runner', 'head', 'hair')
MAX_AREA = 0.25; MIN_PX = 12
OUT = S + '/two'; os.makedirs(OUT, exist_ok=True)
V, FOV, W, H = VW.VIEW_PX, VW.VIEW_FOV, 3840, 1920; F = (V / 2) / math.tan(math.radians(FOV / 2))
pf = YOLOE(S + '/yw/yoloe-26s-seg-pf.pt'); tx = YOLOE(S + '/yw/yoloe-26s-seg.pt'); tx.set_classes(COMMON, tx.get_text_pe(COMMON))
def preds(model, path, conf):
    r = model.predict(path, imgsz=1024, conf=conf, iou=0.5, agnostic_nms=True, device='mps', verbose=False)[0]
    return [(model.names[int(r.boxes.cls[j])], float(r.boxes.conf[j]), [float(z) for z in r.boxes.xyxy[j]]) for j in range(len(r.boxes))]
def inside(a, b): return max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1])) / max(1, (a[2] - a[0]) * (a[3] - a[1]))
mp = glob.glob(os.path.expanduser('~/.cache/huggingface/hub/models--mlx-community--Qwen3.5-9B-4bit/snapshots/') + '*')[0]; vlm, proc = load(mp); cfg = load_config(mp)
Q = ('This is a close-up crop of something seen while running outdoors. What is the main object or thing in the centre of the image? '
     'Answer with a specific noun phrase of 1 to 4 words (for example "wooden platform", "chicken", "stone bridge", "hedge", "street light"). If you cannot tell, answer "unclear".')
try: prompt = apply_chat_template(proc, cfg, Q, num_images=1, enable_thinking=False)
except TypeError: prompt = apply_chat_template(proc, cfg, Q, num_images=1)
def ask(path):
    r = generate(vlm, proc, prompt, image=[path], max_tokens=24, temperature=0.0, repetition_penalty=1.05, verbose=False); return re.sub(r'[`"\n]', ' ', (r.text if hasattr(r, 'text') else str(r))).strip()
def view_dir(yaw_deg, cx, cy):
    a = math.radians(yaw_deg); x = (cx - V / 2) / F; z = -(cy - V / 2) / F; d = np.array([x * math.cos(a) + math.sin(a), -x * math.sin(a) + math.cos(a), z]); d /= np.linalg.norm(d); return math.atan2(d[0], d[1]), math.asin(d[2])
renderers = {}; results = []; t0 = time.time(); stat = dict(named=0, person=0, residual=0, view=0, native=0, tiny=0)
for clip, tt, yaw in EX:
    cdir = glob.glob(f'{CL}/CAM_*_{clip}_D')[0]; osv = D + '/' + os.path.basename(cdir) + '.OSV'; t = float(tt)
    if clip not in renderers: renderers[clip] = VW.CropRenderer(osv)
    cr = renderers[clip]
    cap = cv2.VideoCapture(cdir + '/proxy.mp4'); cap.set(cv2.CAP_PROP_POS_FRAMES, int(round(t * cap.get(cv2.CAP_PROP_FPS)))); ok, eq = cap.read()
    vp = f'{S}/bake/{clip}/{tt}_yaw{yaw:03d}.jpg'; img = cv2.imread(vp)
    named = preds(tx, vp, 0.25); pr = [p for p in preds(pf, vp, 0.30) if not any(k in p[0].lower() for k in PERSONISH)]
    resid = [p for p in pr if not any(inside(p[2], n[2]) >= 0.5 for n in named)]
    resid = [p for p in resid if min(p[2][2] - p[2][0], p[2][3] - p[2][1]) >= MIN_PX * 0.7 and (p[2][2] - p[2][0]) * (p[2][3] - p[2][1]) <= MAX_AREA * V * V]
    items = []; sheet = img.copy()
    for lab, cf, b in named:
        kind = 'person' if lab in WORN else 'named'; stat[kind] += 1; items.append(dict(kind=kind, label=lab, conf=round(cf, 2), box=[round(z) for z in b]))
        cv2.rectangle(sheet, (int(b[0]), int(b[1])), (int(b[2]), int(b[3])), (255, 128, 0) if kind == 'person' else (0, 255, 0), 3); cv2.putText(sheet, lab, (int(b[0]) + 3, int(b[1]) + 24), 0, 0.8, (0, 255, 255), 2)
    for n, (_, cf, b) in enumerate(sorted(resid, key=lambda p: -p[1])[:10]):
        stat['residual'] += 1; mode, deg = VW.crop_plan(b); stat[mode] += 1
        if mode == 'tiny':
            items.append(dict(kind='other', plan=mode, deg=round(deg, 1), conf=round(cf, 2), box=[round(z) for z in b], label_proxy=None, label_orig=None, n=n)); print(clip, tt, yaw, n, 'tiny', f'{deg:.1f}deg', 'skipped', flush=True); continue
        lon, lat = view_dir(yaw, (b[0] + b[2]) / 2, (b[1] + b[3]) / 2); fov = float(np.clip(deg * 1.8, 10, 60)); d = VW.crop_rays(lon, lat, fov, VW.CROP_PX)
        mxp = (((np.arctan2(d[..., 0], d[..., 1])) / np.pi + 1) / 2 * W).astype(np.float32); myp = ((0.5 - np.arcsin(np.clip(d[..., 2], -1, 1)) / np.pi) * H).astype(np.float32)
        cp = cv2.remap(eq, mxp, myp, cv2.INTER_CUBIC); base = f'{OUT}/{clip}_{tt}_y{yaw}_{n}'; cv2.imwrite(base + '_proxy.jpg', cp); lp = ask(base + '_proxy.jpg'); lo = None
        if mode != 'view':
            co = cr.crop(t, lon, lat, fov)[:, :, ::-1]; cv2.imwrite(base + '_orig.jpg', co); lo = ask(base + '_orig.jpg')
        items.append(dict(kind='other', plan=mode, deg=round(deg, 1), conf=round(cf, 2), box=[round(z) for z in b], fov=round(fov, 1), label_proxy=lp, label_orig=lo, n=n))
        cv2.rectangle(sheet, (int(b[0]), int(b[1])), (int(b[2]), int(b[3])), (0, 0, 255), 3); cv2.putText(sheet, str(n), (int(b[0]) + 3, int(b[1]) + 24), 0, 0.9, (0, 255, 255), 3)
        print(clip, tt, yaw, n, mode, f'{deg:.1f}deg', '| proxy:', lp, '| orig:', lo, f'({time.time()-t0:.0f}s)', flush=True)
    cv2.imwrite(f'{OUT}/{clip}_{tt}_y{yaw}_sheet.jpg', sheet); results.append(dict(clip=clip, t=t, yaw=yaw, items=items))
json.dump(dict(stat=stat, results=results), open(OUT + '/two.json', 'w'), indent=1); print('stat', stat, 'done', round(time.time() - t0))
