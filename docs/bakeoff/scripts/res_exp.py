import sys, os, json, glob, re, time, gc, math
import numpy as np, cv2
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import scanlib as L
from strata360.analysis.scenes_vlm import PROMPT, parse
S = L.S; H = os.path.expanduser('~/.cache/huggingface/hub/')
def sharpen(im, amt=0.8, sigma=1.0): return cv2.addWeighted(im, 1 + amt, cv2.GaussianBlur(im, (0, 0), sigma), -amt, 0)
def resize(im, n): return cv2.resize(im, (n, n), interpolation=cv2.INTER_AREA if n < im.shape[1] else cv2.INTER_CUBIC)
from mlx_vlm import load, generate
from mlx_vlm.prompt_utils import apply_chat_template
from mlx_vlm.utils import load_config
def model(repo):
    mp = glob.glob(H + f'models--mlx-community--{repo}/snapshots/')[0:0] or glob.glob(H + f'models--mlx-community--{repo}/snapshots/*')[0]; m, p = load(mp); return m, p, load_config(mp)
def asker(m, p, c, text):
    try: pr = apply_chat_template(p, c, text, num_images=1, enable_thinking=False)
    except TypeError: pr = apply_chat_template(p, c, text, num_images=1)
    def ask(path, n):
        g = generate(m, p, pr, image=[path], max_tokens=n, temperature=0.0, repetition_penalty=1.05, verbose=False); return (g.text if hasattr(g, 'text') else str(g)).strip()
    return ask
T = json.load(open(S + '/sc_eval/truth.json')) if os.path.exists(S + '/sc_eval/truth.json') else None
out = {}
# ---- part 1: scene labels against the size of the picture -------------------------------------------------------------------------------------------------------------------
rows = json.load(open(S + '/sc_eval/rows.json')); os.makedirs(S + '/res_tmp', exist_ok=True)
TR = {0: dict(w={'snow', 'cloud'}, s={'trail', 'field', 'other'}, l={'overcast', 'bright'}, lens={'blocked'}, c={'none'}), 1: dict(w={'cloud', 'clear'}, s={'town', 'building', 'other', 'trail', 'road'}, l={'overcast', 'dusk', 'bright'}, lens={'none'}, c={'few'}),
      2: dict(w={'unknown'}, s={'night_scene'}, l={'dark', 'headlamp'}, lens={'none'}, c={'none', 'few'}), 3: dict(w={'cloud', 'fog'}, s={'river', 'other', 'forest', 'building'}, l={'overcast', 'dusk'}, lens={'none'}, c={'none'}),
      4: dict(w={'cloud', 'clear'}, s={'road', 'town'}, l={'overcast', 'dusk', 'bright'}, lens={'none'}, c={'many'}), 5: dict(w={'snow', 'fog'}, s={'trail', 'field', 'forest'}, l={'overcast'}, lens={'none'}, c={'none'}),
      6: dict(w={'unknown'}, s={'night_scene', 'other'}, l={'dark', 'headlamp'}, lens={'glare', 'blocked'}, c={'none'}), 7: dict(w={'fog'}, s={'trail', 'field'}, l={'overcast'}, lens={'none'}, c={'none'}),
      8: dict(w={'fog', 'cloud'}, s={'river', 'forest', 'trail'}, l={'overcast'}, lens={'none'}, c={'none'}), 9: dict(w={'fog', 'snow'}, s={'forest', 'river'}, l={'overcast'}, lens={'none'}, c={'none'}),
      10: dict(w={'snow', 'cloud'}, s={'field', 'mountain', 'trail'}, l={'overcast'}, lens={'none'}, c={'none'}), 11: dict(w={'unknown', 'clear'}, s={'indoor', 'aid_station', 'building'}, l={'bright'}, lens={'none'}, c={'many'})}
F = [('weather', 'w'), ('setting', 's'), ('lighting', 'l'), ('lens_problems', 'lens'), ('crowd', 'c')]
out['scene'] = {}
for repo in ('Qwen3.5-4B-4bit', 'Qwen3.5-9B-4bit'):
    m, p, c = model(repo); ask = asker(m, p, c, PROMPT)
    for label, n, sh in (('384', 384, False), ('512', 512, False), ('768 (as the stage cuts it)', 768, False), ('512 sharpened', 512, True)):
        score = 0; t0 = time.time()
        for r in rows:
            im = cv2.imread(r['img']); im = resize(im, n); im = sharpen(im) if sh else im; q = f'{S}/res_tmp/s.jpg'; cv2.imwrite(q, im, [cv2.IMWRITE_JPEG_QUALITY, 95]); a = parse(ask(q, 300)) or {}
            for f, k in F: v = a.get(f); score += (str(v).lower() in TR[r['id']][k]) if v is not None else 0
        out['scene'][f'{repo} {label}'] = dict(correct=score, of=len(rows) * len(F), sec_per_image=round((time.time() - t0) / len(rows), 1)); print('scene', repo, label, out['scene'][f'{repo} {label}'], flush=True)
    del m, p; gc.collect()
    try:
        import mlx.core as mx; mx.clear_cache()
    except Exception: pass
json.dump(out, open(S + '/res_exp.json', 'w'), indent=1); print('part1 done', flush=True)
