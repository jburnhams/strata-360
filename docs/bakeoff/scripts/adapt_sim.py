import sys, os, json, math, time, re, glob
import numpy as np, cv2
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import scanlib as L
from adapt import *
dense = json.load(open(OUT + '/dense.json')); ad = json.load(open(OUT + '/adapt.json'))
POLS = {'tight (changes of 4+ levels)': (4, 30), 'medium (7 / 45)': (7, 45), 'loose (12 / 70)': (12, 70)}; CHOSEN = 'medium (7 / 45)'
def keepers(cands, scanned_tiles):
    return [c for c in cands if not c['wearer'] and tuple(c['tile']) in scanned_tiles]
# ---- dense tracks (the reference: objects seen again and again 2 to 2.5 s apart) ------------------------------------------------------------------------------------------------------
def tracks_of(frames):
    tr = []
    for f in frames:
        for c in [c for c in f['cands'] if not c['wearer']]:
            best = None
            for k in tr:
                if f['t'] - k['pts'][-1][0] > 6.0: continue
                d = L.angdist((c['lon'], c['lat']), (k['pts'][-1][1], k['pts'][-1][2]))
                if d < max(3.0, 1.0 * max(c['deg'], k['deg'])) and (best is None or d < best[0]): best = (d, k)
            if best: best[1]['pts'].append((f['t'], c['lon'], c['lat'])); best[1]['deg'] = max(best[1]['deg'], c['deg'])
            else: tr.append(dict(pts=[(f['t'], c['lon'], c['lat'])], deg=c['deg'], kind=c['kind'], yoloe=c['yoloe']))
    return tr
def pos_at(tr, t):
    p = tr['pts']; ts = [x[0] for x in p]
    if t < ts[0] - 3.0 or t > ts[-1] + 3.0: return None
    i = int(np.argmin([abs(x - t) for x in ts])); return (p[i][1], p[i][2])
rows = []; tables = {}
for c in CLIPS:
    dfr = dense[c]['frames']; afr = ad[c]['frames']; thumbs = np.load(f'{OUT}/thumbs_{c}.npy'); info = ad[c]['info']
    trs = [k for k in tracks_of(dfr) if len(k['pts']) >= 2]; ndense_c = sum(len([x for x in f['cands'] if not x['wearer']]) for f in dfr)
    every2 = sum(len([x for x in f['cands'] if not x['wearer']]) for f in dfr[::2]); fixed_frames = int(info['dur'] // 5) + 1
    allt = {k for k in range(len(L.TILES))}
    for pname, (tm, tp) in POLS.items():
        sc = tiles_scanned(thumbs, tm, tp); fc = []; nt = 0
        for j, f in enumerate(afr):
            ts = {L.TILES[k] for k in sc[j]}; nt += len(sc[j]); fc.append((f['t'], keepers(f['cands'], ts)))
        mem, flags = remember(fc); n_cand = sum(len(x[1]) for x in fc); n_new = len(mem)
        # coverage of the dense tracks: a track is observable when some adaptive frame falls inside its lifetime; covered when an object of the adaptive memory was seen there
        obs = cov = aobs = acov = 0
        for k in trs:
            t_in = [f['t'] for f in afr if k['pts'][0][0] - 3.0 <= f['t'] <= k['pts'][-1][0] + 3.0]
            if not t_in: continue
            obs += 1; hit = False
            for m in mem:
                for (ts_, lo, la) in m['sight']:
                    p = pos_at(k, ts_)
                    if p and L.angdist((lo, la), p) < max(3.0, 1.0 * max(m['deg'], k['deg'])): hit = True; break
                if hit: break
            cov += hit
            if k['kind'] == 'animal': aobs += 1; acov += hit
        tables[(c, pname)] = dict(frames=len(afr), tiles_scanned=nt, tiles_all=len(afr) * 26, cands=n_cand, new_objects=n_new, tracks=obs, covered=cov, animal_tracks=aobs, animal_covered=acov, mem=mem if pname == CHOSEN else None)
    rows.append((c, info, len(dfr), ndense_c, every2, fixed_frames, len(afr), trs))
print('clip | frames: dense / fixed 5 s / adaptive | candidates reaching Qwen: dense-all / every-other-dense / adaptive+skip(policy) / +memory | tiles scanned | stable dense objects found')
for c, info, nd, ndc, ev2, ff, na, trs in rows:
    print(f"{c} ({info['dur']:.0f}s {info['speed']:.1f} m/s): frames {nd} / {ff} / {na}")
    print(f"    candidates, all tiles every frame: dense {ndc}, every other dense frame {ev2}")
    for pname in POLS:
        t_ = tables[(c, pname)]; print(f"    {pname:30} tiles {t_['tiles_scanned']:4d}/{t_['tiles_all']:4d} ({100*t_['tiles_scanned']/t_['tiles_all']:3.0f}%)  candidates {t_['cands']:4d}  -> new objects (Qwen calls) {t_['new_objects']:4d} | dense objects found {t_['covered']}/{t_['tracks']} animals {t_['animal_covered']}/{t_['animal_tracks']}")
json.dump({f'{c}|{p}': {k: v for k, v in d.items() if k != 'mem'} for (c, p), d in tables.items()}, open(OUT + '/sim_table.json', 'w'), indent=1)
# ---- Qwen on the new objects of the chosen policy ----------------------------------------------------------------------------------------------------------------------------------------
from strata360.analysis import views as VWm
from mlx_vlm import load, generate
from mlx_vlm.prompt_utils import apply_chat_template
from mlx_vlm.utils import load_config
mp = glob.glob(os.path.expanduser('~/.cache/huggingface/hub/models--mlx-community--Qwen3.5-9B-4bit/snapshots/') + '*')[0]; vlm, proc = load(mp); cfg = load_config(mp)
Q = ('This is a close-up crop of something seen while running outdoors. What is the main object or thing in the centre of the image? Answer with a specific noun phrase of 1 to 4 words. '
     'If you cannot tell, or the centre is just ground, sky, grass, water or blur, answer "unclear".')
try: prompt = apply_chat_template(proc, cfg, Q, num_images=1, enable_thinking=False)
except TypeError: prompt = apply_chat_template(proc, cfg, Q, num_images=1)
def ask(path):
    r = generate(vlm, proc, prompt, image=[path], max_tokens=16, temperature=0.0, repetition_penalty=1.05, verbose=False); return re.sub(r'[`"\n]', ' ', (r.text if hasattr(r, 'text') else str(r))).strip()
labelled = {}; t0 = time.time(); os.makedirs(OUT + '/crops', exist_ok=True)
for c in CLIPS:
    cr = VWm.CropRenderer(L.osv_of(c)); mem = tables[(c, CHOSEN)]['mem']; out = []
    for i, m in enumerate(sorted(mem, key=lambda x: x['t0'])):
        fov = float(np.clip(m['deg'] * 2.5, 8, 40)); im = cr.crop(m['t0'], math.radians(m['sight'][0][1]), math.radians(m['sight'][0][2]), fov, 640)[:, :, ::-1]
        p = f'{OUT}/crops/{c}_{i}.jpg'; cv2.imwrite(p, im); lab = ask(p); out.append(dict(t0=m['t0'], lon=round(m['sight'][0][1], 1), lat=round(m['sight'][0][2], 1), deg=round(m['deg'], 1), kind=m['kind'], yoloe=m['yoloe'], n_seen=len(m['sight']), label=lab, stop=stoplisted(lab), img=p))
        print(c, i, m['kind'], m['yoloe'], '->', lab, 'STOP' if out[-1]['stop'] else '', f'({time.time()-t0:.0f}s)', flush=True)
    labelled[c] = out
json.dump(labelled, open(OUT + '/objects.json', 'w'), indent=1)
for c in CLIPS: print(c, 'objects', len(labelled[c]), 'kept after stop-list', sum(not o['stop'] for o in labelled[c]))
print('done', round(time.time() - t0))
