import sys, os, json, glob, re, random, time, gc
import numpy as np, cv2
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import scanlib as L
S = L.S; random.seed(2)
d = json.load(open(S + '/vocab_cmp.json'))['res']['B text only, 35 + 38 extra words']; WORN = set(L.WORN); ANIM = set(L.ANIMALS)
boxes = []
for key, lst in d.items():
    for lab, cf, b in lst:
        if lab in WORN or (cf < 0.25 and lab not in ANIM) or cf < 0.10: continue
        boxes.append(dict(key=key, label=lab, conf=cf, box=b))
by = {}
for x in boxes: by.setdefault(x['label'], []).append(x)
pick = []
for lab, v in by.items(): pick += random.sample(v, min(len(v), 8))
random.shuffle(pick); pick = pick[:220]; print(len(boxes), 'named boxes; labelling', len(pick), flush=True)
os.makedirs(S + '/calib', exist_ok=True)
for i, x in enumerate(pick):
    im = cv2.imread(f"{S}/tiles/{x['key']}.jpg"); b = x['box']; cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2; s = max(b[2] - b[0], b[3] - b[1]) * 2.0 + 40
    x0, y0, x1, y1 = int(max(0, cx - s / 2)), int(max(0, cy - s / 2)), int(min(im.shape[1], cx + s / 2)), int(min(im.shape[0], cy + s / 2)); x['img'] = f'{S}/calib/{i}.jpg'
    cv2.imwrite(x['img'], cv2.resize(im[y0:y1, x0:x1], (448, 448), interpolation=cv2.INTER_CUBIC))
from mlx_vlm import load, generate
from mlx_vlm.prompt_utils import apply_chat_template
from mlx_vlm.utils import load_config
Q = ('This is a close-up crop of something seen while running outdoors. What is the main object or thing in the centre of the image? Answer with a specific noun phrase of 1 to 4 words. If you cannot tell, answer "unclear".')
for tag, repo in (('q35_9b', 'Qwen3.5-9B-4bit'), ('q35_4b', 'Qwen3.5-4B-4bit')):
    mp = glob.glob(os.path.expanduser(f'~/.cache/huggingface/hub/models--mlx-community--{repo}/snapshots/') + '*')[0]; vlm, proc = load(mp); cfg = load_config(mp)
    try: prompt = apply_chat_template(proc, cfg, Q, num_images=1, enable_thinking=False)
    except TypeError: prompt = apply_chat_template(proc, cfg, Q, num_images=1)
    t0 = time.time()
    for x in pick:
        g = generate(vlm, proc, prompt, image=[x['img']], max_tokens=16, temperature=0.0, repetition_penalty=1.05, verbose=False); x[tag] = re.sub(r'[`"\n]', ' ', (g.text if hasattr(g, 'text') else str(g))).strip()
    print(tag, 'done', round(time.time() - t0), 's', flush=True)
    del vlm, proc; gc.collect()
    try:
        import mlx.core as mx; mx.clear_cache()
    except Exception: pass
json.dump(pick, open(S + '/calib/calib.json', 'w'), indent=1); print('done')
