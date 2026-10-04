import json, os, re, glob, random, cv2, numpy as np
from mlx_vlm import load, generate
from mlx_vlm.prompt_utils import apply_chat_template
from mlx_vlm.utils import load_config
S = os.path.dirname(os.path.abspath(__file__)); random.seed(5)
data = json.load(open(S + '/scan/cands.json')); allc = [dict(c, clip=f['clip'], t=f['t']) for f in data for c in f['cands']]
grp = lambda c: 'wearer' if c['f_wearer'] else 'verify' if c['f_verify'] else 'flat_grid' if c['f_flat_grid'] else 'flat_local' if c['f_flat_local'] else 'kept'
G = {}
for c in allc: G.setdefault(grp(c), []).append(c)
print({k: len(v) for k, v in G.items()})
sample = {'kept': 30, 'flat_local': 16, 'verify': 14, 'wearer': 14, 'flat_grid': 6}
mp = glob.glob(os.path.expanduser('~/.cache/huggingface/hub/models--mlx-community--Qwen3.5-9B-4bit/snapshots/') + '*')[0]; vlm, proc = load(mp); cfg = load_config(mp)
Q = ('This is a close-up crop of something seen while running outdoors. What is the main object or thing in the centre of the image? '
     'Answer with a specific noun phrase of 1 to 4 words. If you cannot tell, or the centre is just ground, sky, grass, water or blur, answer "unclear".')
try: prompt = apply_chat_template(proc, cfg, Q, num_images=1, enable_thinking=False)
except TypeError: prompt = apply_chat_template(proc, cfg, Q, num_images=1)
def ask(path):
    r = generate(vlm, proc, prompt, image=[path], max_tokens=16, temperature=0.0, repetition_penalty=1.05, verbose=False); return re.sub(r'[`"\n]', ' ', (r.text if hasattr(r, 'text') else str(r))).strip()
res = {}
for g, n in sample.items():
    pick = random.sample(G.get(g, []), min(n, len(G.get(g, [])))); tiles = []
    for c in pick:
        c['label'] = ask(c['img']); im = cv2.resize(cv2.imread(c['img']), (300, 300)); txt = f"{c['clip']} {c['label']}"[:34]
        cv2.putText(im, txt, (5, 24), 0, 0.65, (0, 0, 0), 4); cv2.putText(im, txt, (5, 24), 0, 0.65, (0, 255, 255), 2); tiles.append(im)
    while len(tiles) % 6: tiles.append(np.zeros((300, 300, 3), np.uint8))
    cv2.imwrite(f'{S}/scan/sheet_{g}.jpg', np.vstack([np.hstack(tiles[i:i + 6]) for i in range(0, len(tiles), 6)]))
    u = sum(c['label'].lower().startswith('unclear') for c in pick); res[g] = dict(n=len(pick), unclear=u, labels=[c['label'] for c in pick]); print(g, len(pick), 'unclear', u, flush=True)
json.dump(res, open(S + '/scan/labels.json', 'w'), indent=1); print('done')
