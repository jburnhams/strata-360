"""Experiment: lens contamination = featureless in the BODY frame over time but not in the WORLD frame. Usage: persist.py FOLDER CLIP OUT_PREFIX T1,T2.. [win_s]"""
import sys, os, json, subprocess
import numpy as np, cv2
from strata360.render import proxy as P
from strata360.osv.telemetry import read_frames
folder, clip, outp, picks = sys.argv[1], sys.argv[2], sys.argv[3], [float(x) for x in sys.argv[4].split(',')]; win_s = float(sys.argv[5]) if len(sys.argv) > 5 else 10.0
W, H, HZ = 480, 240, 2.0
cd = f'{folder}/strata360/clips/{clip}'; osv = f'{folder}/{clip}.OSV'
R = P.EquirectRenderer(osv, 64, 32); tel = read_frames(osv); side = json.load(open(cd + '/proxy.json')); fr = side['frames']; pfps = side['nominal_fps']
X, Y = np.meshgrid((np.arange(W) + .5) / W, (np.arange(H) + .5) / H); lon = (X - .5) * 2 * np.pi; lat = (.5 - Y) * np.pi
D0 = np.stack([np.sin(lon) * np.cos(lat), np.cos(lon) * np.cos(lat), np.sin(lat)], -1).reshape(-1, 3)
def to_map(d): lo = np.arctan2(d[:, 0], d[:, 1]); la = np.arcsin(np.clip(d[:, 2], -1, 1)); return ((lo / (2 * np.pi) + .5) * W).reshape(H, W).astype(np.float32), ((.5 - la / np.pi) * H).reshape(H, W).astype(np.float32)
def remap(a, d): u, v = to_map(d); return cv2.remap(a, u, v, cv2.INTER_LINEAR, borderMode=cv2.BORDER_WRAP)
cmd = ['ffmpeg', '-v', 'error', '-threads', '2', '-i', cd + '/proxy.mp4', '-an', '-vf', f'fps={HZ},scale={W}:{H}:flags=area', '-pix_fmt', 'gray', '-f', 'rawvideo', '-']
p = subprocess.Popen(cmd, stdout=subprocess.PIPE); imgs = []
while True:
    b = p.stdout.read(W * H)
    if len(b) < W * H: break
    imgs.append(np.frombuffer(b, np.uint8).reshape(H, W).astype(np.float32))
n = len(imgs); Ms = []
for i in range(n):
    j = min(len(fr) - 1, int(round(i / HZ * pfps))); Ms.append(R.stab_matrix(tel['quat'][fr[j]['source_frame']]))
def detail(g): return cv2.GaussianBlur(np.abs(g - cv2.GaussianBlur(g, (0, 0), 1.0)), (0, 0), 4.0)
Dw = [detail(g) for g in imgs]                                                  # detail in the world frame (as the proxy shows it)
Db = [remap(Dw[i], D0 @ Ms[i].T.T) if False else remap(Dw[i], (D0 @ Ms[i])) for i in range(n)]    # body-frame detail: body direction d_b -> world direction d_E = M^T d_b  (row-vector form: d_b @ M)
w = int(win_s * HZ); out = {}
for t in picks:
    c = int(round(t * HZ)); lo, hi = max(0, c - w // 2), min(n, c + w // 2 + 1)
    body_p = np.percentile(np.stack(Db[lo:hi]), 80, axis=0); world_p = np.percentile(np.stack(Dw[lo:hi]), 80, axis=0)
    exp_b = np.mean([remap(world_p, D0 @ Ms[i]) for i in range(lo, hi)], axis=0)                    # what the world passing through each body direction offers
    score = np.log(exp_b + 1.0) - np.log(body_p + 1.0)                                              # > 0: the body direction stays featureless although the world there is not
    # back to the world frame at time c for overlay: world direction d_E -> body direction d_b = M d_E (row form d_E @ M^T)
    sw = remap(score.astype(np.float32), D0 @ Ms[c].T)
    np.save(f'{outp}_score_{int(t)}.npy', score); out[t] = (score, sw)
    print(f't={t}: score pctl 50/90/99 = {np.percentile(score, 50):.2f} {np.percentile(score, 90):.2f} {np.percentile(score, 99):.2f}; cells>0.5: {(score > .5).mean() * 100:.1f}%  rotation over window: {np.degrees(np.arccos(np.clip((np.trace(Ms[lo].T @ Ms[hi - 1]) - 1) / 2, -1, 1))):.0f} deg')
    img = cv2.imread(f'{outp}_f{int(t)}.jpg')
    if img is not None:
        m = cv2.resize((np.clip(sw, 0, 1.5) / 1.5 * 255).astype(np.uint8), (img.shape[1], img.shape[0])); heat = cv2.applyColorMap(m, cv2.COLORMAP_INFERNO)
        a = (np.clip(sw - 0.3, 0, 1)[..., None]); a = cv2.resize(a, (img.shape[1], img.shape[0]))[..., None]; cv2.imwrite(f'{outp}_ov{int(t)}.jpg', (img * (1 - .7 * a) + heat * .7 * a).astype(np.uint8))
