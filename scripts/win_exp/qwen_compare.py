"""Experiment: a newer, larger Qwen vision model (through llama-server) against the project's scene and object answers from Qwen3.5-9B-4bit (MLX, made on the Mac).

  llama-server -m Qwen3.6-35B-A3B-Q4_K_M.gguf --mmproj mmproj-....gguf -c 8192 --port 8081 --jinja --no-webui
  python scripts/win_exp/qwen_compare.py PROJECT_FOLDER OUT.json [--clips PATTERN ...] [--per-clip N] [--port 8081]

Scenes: for N moments of each clip, the two body-frame views (front, rear) are made exactly as the scenes stage makes them (512 px, 120 degrees) and asked the stage's own two prompts (`log`, `scenery`, from
analysis/scenes_vlm.py); the answers are set against the ones in scenes.json for the same frame. Objects: every crop of the object stage (clips/<clip>/objects/o###.jpg) is asked the stage's prompt (objects_vlm.py)
and set against the label in objects.json. Thinking is off, as in the stage."""
import argparse, base64, glob, json, os, re, sys, tempfile, time
import numpy as np
import requests
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))
from strata360.analysis import scenes_vlm as SV, objects_vlm as OV, views as V
from strata360.pipeline import config


def ask(port, prompt, path, max_tokens, model='qwen'):
    b = base64.b64encode(open(path, 'rb').read()).decode()
    body = dict(model=model, temperature=0.0, max_tokens=max_tokens, messages=[dict(role='user', content=[dict(type='image_url', image_url=dict(url='data:image/jpeg;base64,' + b)), dict(type='text', text=prompt)])], chat_template_kwargs=dict(enable_thinking=False))
    t = time.time(); r = requests.post(f'http://127.0.0.1:{port}/v1/chat/completions', json=body, timeout=600).json(); return r['choices'][0]['message']['content'], time.time() - t


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('folder'); ap.add_argument('out'); ap.add_argument('--clips', nargs='*', default=['*0004_D', '*0014_D', '*0023_D', '*0008_D']); ap.add_argument('--per-clip', type=int, default=12); ap.add_argument('--port', type=int, default=8081); a = ap.parse_args()
    res = dict(scenes=[], objects=[]); T = dict(scenes=0.0, objects=0.0)
    for pat in a.clips:
        for cdir in sorted(glob.glob(os.path.join(a.folder, 'strata360', 'clips', pat))):
            clip = os.path.basename(cdir); sj = json.load(open(os.path.join(cdir, 'scenes.json'))); cj = json.load(open(os.path.join(cdir, 'clip.json'))); osv = config.source(cj['source_files']['osv'], cdir)
            items = {(i['frame'], i['view']): i for i in sj['items'] if i['ok']}; frames = sorted({k[0] for k in items}); pick = [frames[int(x)] for x in np.linspace(0, len(frames) - 1, min(a.per_clip, len(frames)))]
            times = [items[(f, 'front')]['t_s'] for f in pick if (f, 'front') in items]
            with tempfile.TemporaryDirectory() as tmp:
                V.write_stab_views_proxy(os.path.join(cdir, 'proxy.mp4'), osv, tmp, times=times, yaws=(0, 180), px=sj.get('px', 512), fov=sj.get('fov', 120.0))
                for fn in sorted(glob.glob(os.path.join(tmp, 's*_v*.jpg'))):
                    m = re.search(r's(\d+)_v(\d+)\.jpg', fn); f, view = int(m.group(1)), SV_NAME[int(m.group(2))]
                    near = min((k for k in items if k[1] == view), key=lambda k: abs(k[0] - f), default=None)
                    if near is None or abs(near[0] - f) > 3: continue
                    row = dict(clip=clip, frame=near[0], view=view, old=items[near]);
                    for kind, mt in (('log', 260), ('scenery', 140)):
                        txt, dt = ask(a.port, SV.PROMPTS[kind], fn, mt); T['scenes'] += dt; row[kind] = SV.parse(txt); row[kind + '_raw'] = None if row[kind] else txt[:200]
                    res['scenes'].append(row)
            print(clip, 'scenes', len(res['scenes']), f"{T['scenes']:.0f}s", flush=True)
            oj = json.load(open(os.path.join(cdir, 'objects.json'))); labels = {f"o{o['id']:03d}.jpg": o for o in oj['objects'] if o.get('source') == 'vlm'}
            for fn in sorted(glob.glob(os.path.join(cdir, 'objects', 'o*.jpg'))):
                o = labels.get(os.path.basename(fn))
                if o is None: continue
                txt, dt = ask(a.port, OV.PROMPT, fn, 24); T['objects'] += dt; res['objects'].append(dict(clip=clip, file=os.path.basename(fn), old=o['label'], yoloe=o['yoloe'], new=OV.clean(txt)))
            print(clip, 'objects', len(res['objects']), f"{T['objects']:.0f}s", flush=True)
    res['seconds'] = T; json.dump(res, open(a.out, 'w'), indent=1, ensure_ascii=False); print(json.dumps(summary(res), indent=1))


SV_NAME = {0: 'front', 180: 'rear'}


def spearman(a, b):
    from scipy.stats import spearmanr
    return round(float(spearmanr(a, b)[0]), 3) if len(a) > 2 else None


def summary(res):
    rows = res['scenes']; out = dict(scenes=len(rows), objects=len(res['objects']), seconds_per_scene_image=round(res['seconds']['scenes'] / max(len(rows) * 2, 1), 2), seconds_per_crop=round(res['seconds']['objects'] / max(len(res['objects']), 1), 2))
    out['parsed'] = dict(log=sum(1 for r in rows if r['log']), scenery=sum(1 for r in rows if r['scenery']), of=len(rows))
    agree = {}
    for k in ('setting', 'weather', 'lighting', 'water', 'crowd', 'lens_problems', 'ground_snow'):
        pairs = [(r['old'].get(k), r['log'].get(k)) for r in rows if r['log'] and r['old'].get(k) is not None]; agree[k] = round(float(np.mean([str(x).lower() == str(y).lower() for x, y in pairs])), 3) if pairs else None
    out['agreement'] = agree
    for k, src in (('people', 'log'), ('scenic', 'log'), ('scenery', 'scenery'), ('clarity', 'scenery')):
        key = 'score' if (k == 'scenery') else k; pairs = [(r['old'][k], r[src][key]) for r in rows if r[src] and isinstance(r[src].get(key), (int, float)) and isinstance(r['old'].get(k), (int, float))]
        if pairs: x, y = np.array(pairs, float).T; out[k] = dict(n=len(pairs), mean_old=round(float(x.mean()), 2), mean_new=round(float(y.mean()), 2), mean_abs_diff=round(float(np.abs(x - y).mean()), 2), spearman=spearman(x, y))
    ob = res['objects']; norm = lambda s: re.sub(r'[^a-z ]', '', s.lower()).strip()
    if ob: out['object_labels'] = dict(same=round(float(np.mean([norm(o['old']) == norm(o['new']) for o in ob])), 3), share_a_word=round(float(np.mean([bool(set(norm(o['old']).split()) & set(norm(o['new']).split())) for o in ob])), 3), unclear_old=sum(o['old'] == 'unclear' for o in ob), unclear_new=sum(o['new'] == 'unclear' for o in ob))
    return out


if __name__ == '__main__': main()
