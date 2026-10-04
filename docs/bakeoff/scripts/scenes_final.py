import sys, os, json, glob, math, subprocess, time
import numpy as np, cv2
from strata360.analysis import views as V, scenes as SC
S = os.path.dirname(os.path.abspath(__file__)); D = "/Volumes/Expansion/2026-02-19 - Legends/strata360/clips"; rows = json.load(open(S + '/sc_eval/rows.json'))
T = eval(open(S + '/scenes_eval4.py').read().split("T = ")[1].split("\nF = ")[0])
WATER = {3: {'river', 'stream', 'lake', 'waterfall'}, 7: {'none', 'puddle'}, 8: {'river', 'stream', 'waterfall'}, 9: {'river', 'stream', 'waterfall'}}; SNOW = {0, 5, 9, 10}
F = [('weather', 'w'), ('setting', 's'), ('lighting', 'l'), ('lens_problems', 'lens'), ('crowd', 'c')]
def render(px, fov, out):
    os.makedirs(out, exist_ok=True)
    for r in rows:
        d = glob.glob(f'{D}/CAM_*_{r["clip"]}_D')[0]; side = json.load(open(d + '/proxy.json')); ft = np.array([f['t_s'] for f in side['frames']]); j = int(np.argmin(np.abs(ft - r['t'])))
        cap = cv2.VideoCapture(d + '/proxy.mp4'); cap.set(cv2.CAP_PROP_POS_FRAMES, j); ok, eq = cap.read(); hd = math.radians(V.heading_fn(d)(r['t'])); yaw = 0.0 if r['view'] == 'front' else 180.0
        img = V._equirect_view(eq[:, :, ::-1], V._rect_rays(yaw, hd, px, px, fov), px, px); cv2.imwrite(f"{out}/s{r['id']:05d}_v000.jpg", img[:, :, ::-1], [cv2.IMWRITE_JPEG_QUALITY, 93])
for name, px, fov in (('100deg 768 px', 768, 100.0), ('100deg 512 px', 512, 100.0), ('120deg 768 px', 768, 120.0)):
    out = f'{S}/final_{px}_{int(fov)}'; render(px, fov, out); t0 = time.time()
    subprocess.run([sys.executable, '-m', 'strata360.analysis.scenes_vlm', out, out + '/log.json', '--prompt', 'log'], check=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env={**os.environ, 'PYTHONPATH': os.environ['PYTHONPATH']})
    secs = (time.time() - t0) / len(rows); ans = {i['frame']: SC.item(i['answer'], None) for i in json.load(open(out + '/log.json'))['items']}; score = {f: 0 for f, _ in F}; wat = snow = 0; unans = 0
    for r in rows:
        a = ans.get(r['id']) or {}; unans += not a.get('ok')
        for f, k in F: v = a.get(f); score[f] += (str(v).lower() in T[r['id']][k]) if v is not None else 0
        w = str(a.get('water')).lower(); wat += (w in WATER[r['id']]) if r['id'] in WATER else (w in ('none', 'puddle')); snow += (a.get('ground_snow') is True) == (r['id'] in SNOW)
    print(f'{name:16} {sum(score.values())}/60 {score} | water {wat}/12 | ground_snow {snow}/12 | unanswered {unans} | {secs:.1f} s a picture', flush=True)
print('done')
