import sys, os, json, glob, random, math, re, time
import numpy as np, cv2
from strata360.analysis import views as V
from strata360.analysis.scenes_vlm import PROMPT, parse
S = os.path.dirname(os.path.abspath(__file__)); D = "/Volumes/Expansion/2026-02-19 - Legends/strata360/clips"; OUT = S + '/sc_eval'; os.makedirs(OUT, exist_ok=True); random.seed(3)
CLIPS = ['0002', '0004', '0006', '0007', '0009', '0011', '0012', '0016', '0018', '0020', '0023', '0025']; items = []
for c in CLIPS:
    d = glob.glob(f'{D}/CAM_*_{c}_D')[0]; sc = json.load(open(d + '/scenes.json'))['items']; ok = [i for i in sc if i.get('ok') and i['t_s'] >= 1.0]
    for view in ('front', 'rear'):
        pool = [i for i in ok if i['view'] == view]
        if pool: items.append((c, d, random.choice(pool)))
random.shuffle(items); rows = []
for n, (c, d, it) in enumerate(items):
    side = json.load(open(d + '/proxy.json')); Wd, Hd = side['size']; times = np.array([f['t_s'] for f in side['frames']]); j = int(np.argmin(np.abs(times - it['t_s'])))
    cap = cv2.VideoCapture(d + '/proxy.mp4'); cap.set(cv2.CAP_PROP_POS_FRAMES, j); ok_, eq = cap.read(); hd = math.radians(V.heading_fn(d)(it['t_s']))
    yaw = 0.0 if it['view'] == 'front' else 180.0; img = V._equirect_view(eq[:, :, ::-1], V._rect_rays(yaw, hd, 768, 768, 100.0), 768, 768)
    p = f'{OUT}/{n:02d}.jpg'; cv2.imwrite(p, img[:, :, ::-1]); rows.append(dict(id=n, clip=c, t=it['t_s'], view=it['view'], img=p, old={k: it.get(k) for k in ('setting', 'people', 'crowd', 'lighting', 'weather', 'lens_problems', 'tags', 'scenic')}))
from mlx_vlm import load, generate
from mlx_vlm.prompt_utils import apply_chat_template
from mlx_vlm.utils import load_config
mp = glob.glob(os.path.expanduser('~/.cache/huggingface/hub/models--mlx-community--Qwen3.5-9B-4bit/snapshots/') + '*')[0]; model, proc = load(mp); cfg = load_config(mp)
try: prompt = apply_chat_template(proc, cfg, PROMPT, num_images=1, enable_thinking=False)
except TypeError: prompt = apply_chat_template(proc, cfg, PROMPT, num_images=1)
t0 = time.time()
for r in rows:
    g = generate(model, proc, prompt, image=[r['img']], max_tokens=300, temperature=0.0, repetition_penalty=1.05, verbose=False); txt = g.text if hasattr(g, 'text') else str(g)
    a = parse(txt) or {}; r['new'] = {k: a.get(k) for k in ('setting', 'people', 'crowd', 'lighting', 'weather', 'lens_problems', 'tags', 'scenic')}; print(r['id'], r['clip'], r['view'], f'({time.time()-t0:.0f}s)', flush=True)
json.dump(rows, open(OUT + '/rows.json', 'w'), indent=1)
for s in range(2):
    tiles = []
    for r in rows[s * 12:(s + 1) * 12]:
        im = cv2.resize(cv2.imread(r['img']), (420, 420)); t = f"#{r['id']} {r['view']}"; cv2.putText(im, t, (8, 34), 0, 1.0, (0, 0, 0), 6); cv2.putText(im, t, (8, 34), 0, 1.0, (0, 255, 255), 2); tiles.append(im)
    cv2.imwrite(f'{OUT}/sheet{s}.jpg', np.vstack([np.hstack(tiles[i:i + 4]) for i in range(0, 12, 4)]))
print('done')
