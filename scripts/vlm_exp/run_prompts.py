"""Experiment (run in .venv-vision): new scenic prompts on the views from make_views.py.
  python -m ... run_prompts.py MANIFEST.json OUT.json [--model models/qwen25vl3b-4bit]
Per moment: GRADED prompt on the front and the rear view; PAIR prompt with both views, in both orders (to see position bias)."""
import argparse, json, os, re, time
GRADED = ("You are choosing shots for a film of an ultramarathon, from a 360 camera worn by the runner. Rate this view as a shot, 1 to 10. "
          "1-2: nothing worth showing (black, blocked, lens glare, blank wall, thick featureless fog). 3-4: dull or ugly (car park, bland road, a crowd of backs, cluttered). "
          "5-6: ordinary but fine (plain trail or forest). 7-8: attractive (good light, depth, an interesting composition or subject). 9-10: stunning (dramatic landscape, golden light, a striking moment). "
          "Use the whole scale; most views are 3 to 7. Answer with ONE JSON object and nothing else: {\"score\": number, \"clarity\": number 1 to 5 (5 = sharp and clear, 1 = foggy, wet lens or blurred), \"reason\": \"short\"}.")
PAIR = ("You are choosing shots for a film of an ultramarathon, from a 360 camera worn by the runner. Image A and image B are two views from the same moment. Which is the better shot to put in the film "
        "(attractive scenery, light, depth, a clear subject, sharp and clear)? Answer with ONE JSON object and nothing else: {\"better\": \"A\" or \"B\" or \"equal\", \"margin\": 1 (slightly) to 3 (far better), \"reason\": \"short\"}.")
def parse(t):
    m = re.search(r'\{.*\}', t, re.S)
    try: return json.loads(m.group(0)) if m else None
    except ValueError: return None
ap = argparse.ArgumentParser(); ap.add_argument('manifest'); ap.add_argument('out'); ap.add_argument('--model', default='models/qwen25vl3b-4bit'); a = ap.parse_args()
from mlx_vlm import load, generate
from mlx_vlm.prompt_utils import apply_chat_template
from mlx_vlm.utils import load_config
mp = os.path.abspath(a.model); model, proc = load(mp); cfg = load_config(mp); t0 = time.time(); man = json.load(open(a.manifest)); res = []
def ask(prompt, files):
    p = apply_chat_template(proc, cfg, prompt, num_images=len(files)); r = generate(model, proc, p, image=files, max_tokens=140, temperature=0.0, verbose=False); txt = r.text if hasattr(r, 'text') else str(r); return parse(txt), txt[:200]
for k, e in enumerate(man):
    f, r = e['front']['file'], e['rear']['file']; row = dict(id=e['id'])
    row['front'], row['front_raw'] = ask(GRADED, [f]); row['rear'], row['rear_raw'] = ask(GRADED, [r])
    row['fr'], row['fr_raw'] = ask(PAIR, [f, r]); row['rf'], row['rf_raw'] = ask(PAIR, [r, f]); res.append(row)
    json.dump(dict(seconds=round(time.time() - t0, 1), items=res), open(a.out, 'w'), indent=1); print(k + 1, '/', len(man), e['id'], f'{time.time() - t0:.0f}s', flush=True)
