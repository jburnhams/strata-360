import sys, json, time, numpy as np
import mlx.core as mx
from mlx_lm import load
from mlx_lm.models.cache import make_prompt_cache, trim_prompt_cache
inp, out = sys.argv[1], sys.argv[2]
rows = [json.loads(l) for l in open(inp)]; rows = [r for r in rows if r['y'] >= 0.1]
CATS = {'urban': 'a city or dense built-up urban area', 'town_village': 'a small town or village', 'rural_farm': 'farmland, fields and farmyards', 'forest_trail': 'forests, woodland and trails',
        'mountain_snow': 'mountains, alpine terrain, snow and ice', 'water_inland': 'rivers, streams, lakes and wetlands', 'coast_sea': 'the coast, beaches and the sea',
        'road_traffic': 'roads, streets and traffic', 'race_event': 'a running race or outdoor event (aid stations, spectators, banners, tents)', 'wildlife': 'wild nature where wild animals live'}
model, tok = load('/Users/jburnhams/Code/strata-360/models/qwen25-7b-instruct-4bit')
SYS = "You answer Y or N. Question: would a runner plausibly see the given thing in the given setting while running outdoors (not in a zoo, shop, museum or indoors)? Answer Y only if it is a typical sight there, otherwise N."
yn = [tok.encode(x, add_special_tokens=False)[0] for x in ('Y', 'N')]
MARK = 'XXQXX'; full = tok.apply_chat_template([{'role': 'system', 'content': SYS}, {'role': 'user', 'content': MARK}], add_generation_prompt=True, tokenize=False)
pre, post = full.split(MARK); cache = make_prompt_cache(model); model(mx.array([tok.encode(pre, add_special_tokens=False)]), cache=cache); mx.eval([c.state for c in cache])
t0 = time.time()
with open(out, 'w') as f:
    for i, r in enumerate(rows):
        cats = {}
        suf = tok.encode(f'Thing: {r["tag"]}\nSetting: has a clear outline: it is a separate object, animal, plant, vehicle, building or sign that you could draw a box around (not terrain, weather, sky, light or an area)' + post, add_special_tokens=False)
        lg = model(mx.array([suf]), cache=cache)[0, -1]; cats['boxable'] = round(float(mx.softmax(lg[mx.array(yn)])[0]), 2); trim_prompt_cache(cache, len(suf))
        for c, d in CATS.items():
            suf = tok.encode(f'Thing: {r["tag"]}\nSetting: {d}' + post, add_special_tokens=False)
            lg = model(mx.array([suf]), cache=cache)[0, -1]; p = float(mx.softmax(lg[mx.array(yn)])[0]); trim_prompt_cache(cache, len(suf)); cats[c] = round(p, 2)
        f.write(json.dumps(dict(tag=r['tag'], y=r['y'], cats=cats)) + '\n')
        if i % 100 == 0: print(i, len(rows), round(time.time() - t0), flush=True); f.flush()
print('done', round(time.time() - t0))
