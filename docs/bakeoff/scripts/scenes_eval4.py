import sys, os, json, glob, time
from strata360.analysis.scenes_vlm import PROMPT, parse
S = os.path.dirname(os.path.abspath(__file__)); rows = json.load(open(S + '/sc_eval/rows.json'))
from mlx_vlm import load, generate
from mlx_vlm.prompt_utils import apply_chat_template
from mlx_vlm.utils import load_config
mp = glob.glob(os.path.expanduser('~/.cache/huggingface/hub/models--mlx-community--Qwen3.5-4B-4bit/snapshots/') + '*')[0]; model, proc = load(mp); cfg = load_config(mp)
try: prompt = apply_chat_template(proc, cfg, PROMPT, num_images=1, enable_thinking=False)
except TypeError: prompt = apply_chat_template(proc, cfg, PROMPT, num_images=1)
t0 = time.time()
for r in rows:
    g = generate(model, proc, prompt, image=[r['img']], max_tokens=300, temperature=0.0, repetition_penalty=1.05, verbose=False); a = parse(g.text if hasattr(g, 'text') else str(g)) or {}
    r['new4'] = {k: a.get(k) for k in ('setting', 'people', 'crowd', 'lighting', 'weather', 'lens_problems', 'tags', 'scenic')}
print('4B seconds per image', round((time.time() - t0) / len(rows), 1))
json.dump(rows, open(S + '/sc_eval/rows4.json', 'w'), indent=1)
T = {0: dict(w={'snow', 'cloud'}, s={'trail', 'field', 'other'}, l={'overcast', 'bright'}, lens={'blocked'}, c={'none'}), 1: dict(w={'cloud', 'clear'}, s={'town', 'building', 'other', 'trail', 'road'}, l={'overcast', 'dusk', 'bright'}, lens={'none'}, c={'few'}),
     2: dict(w={'unknown'}, s={'night_scene'}, l={'dark', 'headlamp'}, lens={'none'}, c={'none', 'few'}), 3: dict(w={'cloud', 'fog'}, s={'river', 'other', 'forest', 'building'}, l={'overcast', 'dusk'}, lens={'none'}, c={'none'}),
     4: dict(w={'cloud', 'clear'}, s={'road', 'town'}, l={'overcast', 'dusk', 'bright'}, lens={'none'}, c={'many'}), 5: dict(w={'snow', 'fog'}, s={'trail', 'field', 'forest'}, l={'overcast'}, lens={'none'}, c={'none'}),
     6: dict(w={'unknown'}, s={'night_scene', 'other'}, l={'dark', 'headlamp'}, lens={'glare', 'blocked'}, c={'none'}), 7: dict(w={'fog'}, s={'trail', 'field'}, l={'overcast'}, lens={'none'}, c={'none'}),
     8: dict(w={'fog', 'cloud'}, s={'river', 'forest', 'trail'}, l={'overcast'}, lens={'none'}, c={'none'}), 9: dict(w={'fog', 'snow'}, s={'forest', 'river'}, l={'overcast'}, lens={'none'}, c={'none'}),
     10: dict(w={'snow', 'cloud'}, s={'field', 'mountain', 'trail'}, l={'overcast'}, lens={'none'}, c={'none'}), 11: dict(w={'unknown', 'clear'}, s={'indoor', 'aid_station', 'building'}, l={'bright'}, lens={'none'}, c={'many'})}
F = [('weather', 'w'), ('setting', 's'), ('lighting', 'l'), ('lens_problems', 'lens'), ('crowd', 'c')]; score = {w: {f: 0 for f, _ in F} for w in ('old', 'new', 'new4')}
for r in rows:
    for who in score:
        for f, k in F:
            v = r[who].get(f); score[who][f] += (str(v).lower() in T[r['id']][k]) if v is not None else 0
for who, s in score.items(): print({'old': 'Qwen2.5-VL-3B (the stage today)', 'new': 'Qwen3.5-9B', 'new4': 'Qwen3.5-4B'}[who], s, 'total', sum(s.values()), '/ 60')
print('done')
