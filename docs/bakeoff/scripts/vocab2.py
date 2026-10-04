import sys, json, time, os, numpy as np
import mlx.core as mx
from mlx_lm import load
tags = [l.strip() for l in open(sys.argv[1]) if l.strip()]; out = sys.argv[2]
model, tok = load('/Users/jburnhams/Code/strata-360/models/qwen25-7b-instruct-4bit')
SYS = """You sort image tags for outdoor running footage (trails, forests, fields, villages, towns, mountains, coast, races) filmed by a runner. For each tag answer with ONE letter:
A = THING: a concrete physical object, animal, plant, vehicle, building, structure or sign a runner could plausibly pass outdoors, with a clear outline. Examples: cow, bridge, fence, bus stop, traffic light, boat, cairn, tent, signpost, bench, church, tractor, bin, deer, gate, waterfall.
B = SCENE: terrain, weather, sky, light, water body or general outdoor setting with no sensible box. Examples: river, fog, snow, forest, beach, mountain, sunset, mud, field, city street.
C = SKIP: everything else: people, body parts, clothing, actions, jobs, abstract ideas, emotions, photo or art styles, media, objects found only indoors or in studios, labs, factories or kitchens, food, small tools, sports equipment, anything you would not expect outdoors on a run. Examples: actor, adult, act, 3D glasses, abacus, accordion, acrylic paint, alarm clock, album cover, alphabet, altar, amplifier, angle, ancient, adventure.
Borderline outdoor objects and places (ambulance, alley, acorn, anchor) are A or B, not C. Answer with the letter only."""
ids = [tok.encode(x, add_special_tokens=False)[0] for x in ('A', 'B', 'C')]
from mlx_lm.models.cache import make_prompt_cache, trim_prompt_cache
MARK = 'XXTAGXX'
full = tok.apply_chat_template([{'role': 'system', 'content': SYS}, {'role': 'user', 'content': MARK}], add_generation_prompt=True, tokenize=False)
pre, post = full.split(MARK); pre_ids = tok.encode(pre, add_special_tokens=False)
cache = make_prompt_cache(model); model(mx.array([pre_ids]), cache=cache); mx.eval([c.state for c in cache])
t0 = time.time()
with open(out, 'w') as f:
    for i, t in enumerate(tags):
        suf = tok.encode(t + post, add_special_tokens=False)
        lg = model(mx.array([suf]), cache=cache)[0, -1]; pr = mx.softmax(lg[mx.array(ids)]).tolist(); trim_prompt_cache(cache, len(suf))
        k = 'THING' if pr[0] > 0.25 and pr[0] >= pr[1] else 'SCENE' if pr[1] > 0.25 else 'SKIP'
        f.write(json.dumps(dict(tag=t, kind=k, p=[round(x, 2) for x in pr])) + '\n')
        if i % 300 == 0: print(i, len(tags), round(time.time() - t0), flush=True); f.flush()
print('done', round(time.time() - t0))
