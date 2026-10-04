import sys, glob, json, time, os
from mlx_vlm import load, generate
from mlx_vlm.prompt_utils import apply_chat_template
from mlx_vlm.utils import load_config
mp, root, out = sys.argv[1], sys.argv[2], sys.argv[3]; limit = int(sys.argv[4]) if len(sys.argv) > 4 else 0
model, proc = load(mp); cfg = load_config(mp)
Q = ('Describe what is visible in this outdoor photo as JSON only, with exactly these keys: "animals" (list of animals you can see with counts, [] if none), "vehicles" ([] if none), '
     '"structures" (buildings, bridges, fences, gates, signs, tents, etc; [] if none), "water" ("none", or what it is if you can see it), "terrain" (short), "weather" (short), "other" (anything else notable, [] if none). '
     'Only list what is clearly visible. Do not guess.' + os.environ.get('VLM_HINT', ''))
try: prompt = apply_chat_template(proc, cfg, Q, num_images=1, enable_thinking=False)
except TypeError: prompt = apply_chat_template(proc, cfg, Q, num_images=1)
files = sorted(glob.glob(root + '/*/*.jpg')); files = files[:limit] if limit else files; res = []; t0 = time.time()
for k, fn in enumerate(files):
    r = generate(model, proc, prompt, image=[fn], max_tokens=220, temperature=0.0, repetition_penalty=1.15, verbose=False)
    res.append(dict(file='/'.join(fn.split('/')[-2:]), answer=(r.text if hasattr(r, 'text') else str(r)).strip()))
    if k % 40 == 0: print(k, len(files), round(time.time() - t0), flush=True)
json.dump(res, open(out, 'w')); print('done', round(time.time() - t0), 's')
