"""Experiment: cut the front and rear views (100 degrees, square, as the scenes stage sees them) at chosen times from the proxies, for trying new VLM prompts.
  python scripts/vlm_exp/make_views.py FOLDER OUT_DIR   -> OUT_DIR/imgs/<clip>_<t>_<front|rear>.jpg and OUT_DIR/manifest.json (with the old scenes.json answers)"""
import json, os, sys
import numpy as np, cv2
from strata360.analysis import views as V
folder, out = sys.argv[1], sys.argv[2]; os.makedirs(out + '/imgs', exist_ok=True)
PICK = {'CAM_20260222130830_0023_D': [0, 25, 60, 100, 125, 150, 190, 205], 'CAM_20260221115831_0018_D': [5, 20, 25, 55, 70, 85], 'CAM_20260220065728_0009_D': [0, 10, 20],
        'CAM_20260219170541_0004_D': [25, 45, 65, 100], 'CAM_20260219205325_0006_D': [0, 5, 10], 'CAM_20260221081441_0017_D': [0, 10, 20], 'CAM_20260222081045_0021_D': [10, 30, 50],
        'CAM_20260220154933_0014_D': [5, 20, 35]}
man = []
for clip, ts in PICK.items():
    cd = f'{folder}/strata360/clips/{clip}'; items = {(round(i['t_s']), i['view']): i for i in json.load(open(cd + '/scenes.json'))['items']}
    for t in ts:
        e = {'id': f'{clip[4:19]}_{t}', 'clip': clip, 't': t}
        for view, yaw in (('front', 0), ('rear', 180)):
            fn = f'{out}/imgs/{clip[4:19]}_{t}_{view}.jpg'
            if not os.path.exists(fn):
                try: b = V.render_thumb_proxy(f'{cd}/proxy.mp4', f'{folder}/{clip}.OSV', float(t), yaw=yaw, pitch=0, hfov=100, w=768, h=768)
                except Exception as ex: print('skip', clip, t, view, ex); b = None
                if b: open(fn, 'wb').write(b)
            old = items.get((t, view)) or {}; e[view] = dict(file=fn, old_scenic=old.get('scenic'), old_setting=old.get('setting'), old_lens=old.get('lens_problems'), old_desc=old.get('description'))
        if os.path.exists(e['front']['file']) and os.path.exists(e['rear']['file']): man.append(e)
json.dump(man, open(out + '/manifest.json', 'w'), indent=1); print(len(man), 'moments,', 2 * len(man), 'images')
