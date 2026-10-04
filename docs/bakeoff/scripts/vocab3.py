import sys, json, time
import mlx.core as mx
from mlx_lm import load
from mlx_lm.models.cache import make_prompt_cache, trim_prompt_cache
tags = [l.strip() for l in open(sys.argv[1]) if l.strip()]; out = sys.argv[2]
model, tok = load('/Users/jburnhams/Code/strata-360/models/qwen25-7b-instruct-4bit')
SYS = "Answer Y or N. Question: could a runner see this thing outdoors while running through towns, villages, countryside, forests, mountains or along a coast (as a real object, animal, plant, building, structure, vehicle, sign or piece of scenery, or as terrain or weather)? People, clothes, actions, ideas, art, media and indoor-only things are N."
yn = [tok.encode(x, add_special_tokens=False)[0] for x in ('Y', 'N')]
MARK = 'XXQXX'; full = tok.apply_chat_template([{'role': 'system', 'content': SYS}, {'role': 'user', 'content': MARK}], add_generation_prompt=True, tokenize=False)
pre, post = full.split(MARK); cache = make_prompt_cache(model); model(mx.array([tok.encode(pre, add_special_tokens=False)]), cache=cache); mx.eval([c.state for c in cache])
t0 = time.time()
with open(out, 'w') as f:
    for i, t in enumerate(tags):
        suf = tok.encode(t + post, add_special_tokens=False); lg = model(mx.array([suf]), cache=cache)[0, -1]
        p = float(mx.softmax(lg[mx.array(yn)])[0]); trim_prompt_cache(cache, len(suf)); f.write(json.dumps(dict(tag=t, y=round(p, 3))) + '\n')
        if i % 500 == 0: print(i, len(tags), round(time.time() - t0), flush=True)
print('done', round(time.time() - t0))
