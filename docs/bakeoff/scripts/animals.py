import sys, os, glob, json, math, re, time
import numpy as np, cv2
from ultralytics import YOLOE
from strata360.analysis import views as VW
from mlx_vlm import load, generate
from mlx_vlm.prompt_utils import apply_chat_template
from mlx_vlm.utils import load_config
S = os.path.dirname(os.path.abspath(__file__)); D = "/Volumes/Expansion/2026-02-19 - Legends"; CL = D + "/strata360/clips"
ANIMALS = ['chicken', 'duck', 'goat', 'pig', 'sheep', 'cow', 'bird', 'animal']
tx = YOLOE(S + '/yw/yoloe-26s-seg.pt'); tx.set_classes(ANIMALS, tx.get_text_pe(ANIMALS))
cdir = glob.glob(f'{CL}/CAM_*_0013_D')[0]; osv = D + '/' + os.path.basename(cdir) + '.OSV'; cr = VW.CropRenderer(osv)
mp = glob.glob(os.path.expanduser('~/.cache/huggingface/hub/models--mlx-community--Qwen3.5-9B-4bit/snapshots/') + '*')[0]; vlm, proc = load(mp); cfg = load_config(mp)
Q = 'This is a close-up crop of something seen on a farm. What animal or object is in the centre? Answer with 1 to 3 words (for example "chicken", "duck", "pig", "goat", "fence post"). If you cannot tell, answer "unclear".'
try: prompt = apply_chat_template(proc, cfg, Q, num_images=1, enable_thinking=False)
except TypeError: prompt = apply_chat_template(proc, cfg, Q, num_images=1)
def ask(path):
    r = generate(vlm, proc, prompt, image=[path], max_tokens=16, temperature=0.0, repetition_penalty=1.05, verbose=False); return re.sub(r'[`"\n]', ' ', (r.text if hasattr(r, 'text') else str(r))).strip()
def detect(img, conf):
    cv2.imwrite(S + '/_a.jpg', img); r = tx.predict(S + '/_a.jpg', imgsz=1024, conf=conf, iou=0.5, agnostic_nms=True, device='mps', verbose=False)[0]
    return [(tx.names[int(r.boxes.cls[j])], float(r.boxes.conf[j]), [int(z) for z in r.boxes.xyxy[j]]) for j in range(len(r.boxes))]
os.makedirs(S + '/ani', exist_ok=True); out = []; tiles = []
for t in (0.6, 1.8, 3.1):
    cap = cv2.VideoCapture(cdir + '/proxy.mp4'); cap.set(cv2.CAP_PROP_POS_FRAMES, int(round(t * cap.get(cv2.CAP_PROP_FPS)))); ok, eq = cap.read()
    lon, lat, fov = math.radians(270), math.radians(-6), 60.0           # the pen lies between the 240 and 300 degree views
    d = VW.crop_rays(lon, lat, fov, 1024); mx = (((np.arctan2(d[..., 0], d[..., 1])) / np.pi + 1) / 2 * 3840).astype(np.float32); my = ((0.5 - np.arcsin(np.clip(d[..., 2], -1, 1)) / np.pi) * 1920).astype(np.float32)
    prox = cv2.remap(eq, mx, my, cv2.INTER_CUBIC); orig = cr.crop(t, lon, lat, fov, px=1024)[:, :, ::-1].copy()
    for name, im in (('proxy 60deg/1024', prox), ('original 60deg/1024', orig)):
        for conf in (0.30, 0.15, 0.08):
            b = detect(im, conf); out.append(dict(t=t, src=name, conf=conf, n=len(b), labels=sorted(set(x[0] for x in b))))
            print(t, name, conf, len(b), sorted(set(x[0] for x in b)), flush=True)
        if t == 1.8:
            b = detect(im, 0.08); sheet = im.copy()
            for lab, cf, q in b: cv2.rectangle(sheet, (q[0], q[1]), (q[2], q[3]), (0, 255, 0), 2)
            cv2.putText(sheet, f'{name} conf0.08: {len(b)} boxes', (10, 40), 0, 1.2, (0, 0, 0), 6); cv2.putText(sheet, f'{name} conf0.08: {len(b)} boxes', (10, 40), 0, 1.2, (0, 255, 255), 2); tiles.append(cv2.resize(sheet, (900, 900)))
            if name.startswith('original'):
                lab_out = []
                for k, (lab, cf, q) in enumerate(sorted(b, key=lambda x: -x[1])[:12]):
                    cx, cy = (q[0] + q[2]) / 2, (q[1] + q[3]) / 2; s = max(q[2] - q[0], q[3] - q[1]) * 2.2 + 24; x0, y0 = int(max(0, cx - s / 2)), int(max(0, cy - s / 2)); crop = im[y0:int(cy + s / 2), x0:int(cx + s / 2)]
                    p = f'{S}/ani/c{k}.jpg'; cv2.imwrite(p, cv2.resize(crop, (448, 448), interpolation=cv2.INTER_CUBIC)); lab_out.append((k, lab, round(cf, 2), ask(p)))
                    print('qwen', k, lab, round(cf, 2), '->', lab_out[-1][3], flush=True)
                out.append(dict(qwen=lab_out))
cv2.imwrite(S + '/ani/pen_compare.jpg', np.hstack(tiles)); json.dump(out, open(S + '/ani/animals.json', 'w'), indent=1); print('done')
