"""Experiment (run in .venv-vision): a scenery-only graded prompt (people ignored, since the people stage knows about them) on the views from make_views.py.
  python run_scenery.py MANIFEST.json OUT.json [--model models/qwen25vl3b-4bit]"""
import argparse, json, os, re, time
SCENERY = ("You are choosing scenery shots for a film of an ultramarathon, from a 360 camera worn by the runner. Rate the SCENERY in this view, 1 to 10, as a shot for the film. "
           "IGNORE any people, including the runner who wears the camera and their pole: people neither add to nor take away from the score; judge only the landscape, light, depth, composition and how clear the picture is. "
           "1-2: nothing worth showing (black, blocked, lens glare, blank wall, thick featureless fog). 3-4: dull or ugly (car park, bland road, cluttered, hazy). "
           "5-6: ordinary but fine (plain trail or forest). 7-8: attractive (good light, depth, an interesting composition). 9-10: stunning (dramatic landscape, golden light). "
           "Use the whole scale; most views are 3 to 7. Answer with ONE JSON object and nothing else: {\"score\": number, \"clarity\": number 1 to 5 (5 = sharp and clear, 1 = foggy, wet lens or blurred), \"reason\": \"short\"}.")
def parse(t):
    m = re.search(r'\{.*\}', t, re.S)
    try: return json.loads(m.group(0)) if m else None
    except ValueError: return None
ap = argparse.ArgumentParser(); ap.add_argument('manifest'); ap.add_argument('out'); ap.add_argument('--model', default='models/qwen25vl3b-4bit'); a = ap.parse_args()
from mlx_vlm import load, generate
from mlx_vlm.prompt_utils import apply_chat_template
from mlx_vlm.utils import load_config
mp = os.path.abspath(a.model); model, proc = load(mp); cfg = load_config(mp); t0 = time.time(); man = json.load(open(a.manifest)); res = []
prompt = apply_chat_template(proc, cfg, SCENERY, num_images=1)
for k, e in enumerate(man):
    row = dict(id=e['id'])
    for v in ('front', 'rear'):
        r = generate(model, proc, prompt, image=[e[v]['file']], max_tokens=140, temperature=0.0, verbose=False); txt = r.text if hasattr(r, 'text') else str(r); row[v] = parse(txt); row[v + '_raw'] = txt[:200]
    res.append(row); json.dump(dict(seconds=round(time.time() - t0, 1), items=res), open(a.out, 'w'), indent=1); print(k + 1, '/', len(man), e['id'], f'{time.time() - t0:.0f}s', flush=True)
