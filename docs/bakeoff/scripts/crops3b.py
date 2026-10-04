import json, re, time, os
from mlx_vlm import load, generate
from mlx_vlm.prompt_utils import apply_chat_template
from mlx_vlm.utils import load_config
S = os.path.dirname(os.path.abspath(__file__)); c = json.load(open(S + '/calib/calib.json'))
Q = ('This is a close-up crop of something seen while running outdoors. What is the main object or thing in the centre of the image? Answer with a specific noun phrase of 1 to 4 words. If you cannot tell, answer "unclear".')
mp = '/Users/jburnhams/Code/strata-360/models/qwen25vl3b-4bit'; m, p = load(mp); cfg = load_config(mp); pr = apply_chat_template(p, cfg, Q, num_images=1); t0 = time.time()
for x in c:
    g = generate(m, p, pr, image=[x['img']], max_tokens=16, temperature=0.0, verbose=False); x['q25_3b'] = re.sub(r'[`"\n]', ' ', (g.text if hasattr(g, 'text') else str(g))).strip()
json.dump(c, open(S + '/calib/calib3.json', 'w'), indent=1); print('done', round(time.time() - t0), 's')
