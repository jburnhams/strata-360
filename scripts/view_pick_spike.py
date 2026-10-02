"""Experiment (cameras / per-area quality): score virtual-camera views from the 15 degree quality grid (scripts/quality_spike.py), compare the simple score with the VLM's scenic rating, and draw the
preferred views on frames for checking by eye.

  python scripts/view_pick_spike.py corr  FOLDER GRID_DIR                          # Spearman correlation of the simple measures with the scenes stage (VLM) answers, all clips
  python scripts/view_pick_spike.py draw  FOLDER GRID_DIR OUT_DIR CLIP T1,T2,...   # best and runner-up views at those clip times, edges drawn on frames of the proxy

A view is (yaw, pitch, hfov, aspect); yaw is the equirect longitude of the proxy (centre column 0; the scenes stage's views are heading + 0 or 180). The view is sampled on a regular grid in its own
image plane (so each sample is the same area on screen) and each sample is looked up in the 12 x 24 grid. Score = detail x (1 - penalty(largest continuous flat patch share)) x exposure."""
import argparse, json, os, subprocess, sys
import numpy as np, cv2
from scipy.ndimage import label

GR, GC = 12, 24
FLAT = 3.0                      # mid-scale detail (grey levels) under which a cell is 'flat': sky, fog, smooth ground, a smear
PEN_FROM, PEN_TO = 0.10, 0.50   # penalty starts at 10% of the view in one flat patch and is full at 50%


def load_grid(grid_dir, clip):
    z = np.load(os.path.join(grid_dir, clip + '.npz')); return {k: z[k] for k in z.files}


def view_dirs(yaw, pitch, hfov, aspect, n=24):
    a, p = np.radians(yaw), np.radians(pitch); f = np.array([np.sin(a) * np.cos(p), np.cos(a) * np.cos(p), np.sin(p)]); r = np.array([np.cos(a), -np.sin(a), 0.0]); u = np.cross(r, f)
    tx = np.tan(np.radians(hfov) / 2); ty = tx / aspect; gx = ((np.arange(n) + .5) / n * 2 - 1) * tx; gy = ((np.arange(max(int(n / aspect), 4)) + .5) / max(int(n / aspect), 4) * 2 - 1) * ty
    X, Y = np.meshgrid(gx, -gy); d = f + X[..., None] * r + Y[..., None] * u; return (d / np.linalg.norm(d, axis=-1, keepdims=True)).reshape(-1, 3)


def cell_of(d, shift=0):
    lon = np.degrees(np.arctan2(d[:, 0], d[:, 1])); lat = np.degrees(np.arcsin(np.clip(d[:, 2], -1, 1)))
    c = np.clip(((lon + 180) / 360 * GC).astype(int), 0, GC - 1); r = np.clip(((90 - lat) / 180 * GR).astype(int), 0, GR - 1); return r, (c + shift) % GC


def penalty(share): return float(np.clip((share - PEN_FROM) / (PEN_TO - PEN_FROM), 0, 1))


def view_score(g, i, yaw, pitch, hfov=100.0, aspect=1.0):
    d = view_dirs(yaw, pitch, hfov, aspect); r, c = cell_of(d); mid = int(np.median(c)) if np.ptp(c) < 12 else None
    if mid is None:                                                                                    # the view spans the wrap-around column: roll the grid so the view is in the middle
        r, c = cell_of(d, shift=GC // 2); roll = GC // 2
    else: roll = 0
    tex = np.roll(g['tex'][i], roll, axis=1); hi = np.roll(g['clip_hi'][i], roll, axis=1); lo = np.roll(g['clip_lo'][i], roll, axis=1)
    cnt = np.zeros((GR, GC)); np.add.at(cnt, (r, c), 1); flat = (cnt > 0) & (tex < FLAT); lab, k = label(flat, structure=np.ones((3, 3)))
    big = max([cnt[lab == j].sum() for j in range(1, k + 1)] or [0.0]); share = big / cnt.sum()
    detail = float(np.mean(np.log1p(tex[r, c])) / 2.5); expo = float(1 - min(1.0, 4 * np.mean(hi[r, c] + lo[r, c])))
    return dict(score=detail * (1 - penalty(share)) * expo, detail=detail, flat_share=float(share), expo=expo)


def best_views(g, i, pitches=(-15, 0, 15), hfovs=(70, 90, 110), aspect=16 / 9, step=15):
    out = []
    for yaw in range(-180, 180, step):
        for p in pitches:
            for h in hfovs:
                s = view_score(g, i, yaw, p, h, aspect); s.update(yaw=yaw, pitch=p, hfov=h); out.append(s)
    return sorted(out, key=lambda s: -s['score'])


def corr(folder, grid_dir):
    from scipy.stats import spearmanr
    from strata360.analysis.views import heading_track
    rows = []
    for clip in sorted(os.listdir(os.path.join(folder, 'strata360', 'clips'))):
        cd = os.path.join(folder, 'strata360', 'clips', clip)
        if not clip.startswith('CAM_') or not os.path.exists(os.path.join(grid_dir, clip + '.npz')) or not os.path.exists(cd + '/scenes.json'): continue
        g = load_grid(grid_dir, clip); hz = float(g['hz']); n = len(g['tex']); heading, _ = heading_track(os.path.join(folder, clip + '.OSV')); items = json.load(open(cd + '/scenes.json'))['items']
        for it in items:
            if not it['ok'] or not isinstance(it.get('scenic'), (int, float)): continue
            i = min(int(round(it['t_s'] * hz)), n - 1); yaw = np.degrees(heading[min(it['frame'], len(heading) - 1)]) + (0 if it['view'] == 'front' else 180)
            s = view_score(g, i, ((yaw + 180) % 360) - 180, 0.0, 100.0, 1.0)
            rows.append(dict(clip=clip[4:19], view=it['view'], scenic=float(it['scenic']), energy=float(it.get('energy') or 0), lens=it.get('lens_problems') or 'none', setting=it.get('setting'), **s))
    print(f'{len(rows)} VLM answers on {len({r["clip"] for r in rows})} clips')
    for name in ('score', 'detail', 'flat_share', 'expo'):
        for tgt in ('scenic', 'energy'):
            rho, p = spearmanr([r[name] for r in rows], [r[tgt] for r in rows]); print(f'  {name:10s} vs {tgt:7s} rho = {rho:+.2f}  (p = {p:.3g})')
    for flag in ('droplets', 'fog', 'glare'):
        a = [r['score'] for r in rows if r['lens'] == flag]; b = [r['score'] for r in rows if r['lens'] == 'none']
        if a: print(f'  lens_problems={flag}: n={len(a)} mean score {np.mean(a):.2f} vs none {np.mean(b):.2f};  flat share {np.mean([r["flat_share"] for r in rows if r["lens"] == flag]):.2f} vs {np.mean([r["flat_share"] for r in rows if r["lens"] == "none"]):.2f}')
    for st in sorted({r['setting'] for r in rows}):
        a = [r for r in rows if r['setting'] == st]
        if len(a) >= 8: print(f'  setting {st:12s} n={len(a):3d}  scenic {np.mean([r["scenic"] for r in a]):.2f}  score {np.mean([r["score"] for r in a]):.2f}  flat {np.mean([r["flat_share"] for r in a]):.2f}')
    json.dump(rows, open(os.path.join(grid_dir, 'corr_rows.json'), 'w'))


def edge_points(yaw, pitch, hfov, aspect, k=40):
    a, p = np.radians(yaw), np.radians(pitch); f = np.array([np.sin(a) * np.cos(p), np.cos(a) * np.cos(p), np.sin(p)]); r = np.array([np.cos(a), -np.sin(a), 0.0]); u = np.cross(r, f)
    tx = np.tan(np.radians(hfov) / 2); ty = tx / aspect; t = np.linspace(-1, 1, k)
    pts = [(-tx, -ty * (-t)), (tx * t, ty * np.ones(k)), (tx * np.ones(k), ty * t[::-1]), (tx * t[::-1], -ty * np.ones(k))]
    xs = np.concatenate([np.atleast_1d(a_) * np.ones(k) for a_, _ in pts]); ys = np.concatenate([np.atleast_1d(b_) * np.ones(k) for _, b_ in pts])
    d = f + xs[:, None] * r + ys[:, None] * u; return d / np.linalg.norm(d, axis=1, keepdims=True)


def draw_view(img, v, colour, label_text):
    H, W = img.shape[:2]; d = edge_points(v['yaw'], v['pitch'], v['hfov'], 16 / 9); lon = np.arctan2(d[:, 0], d[:, 1]); lat = np.arcsin(np.clip(d[:, 2], -1, 1))
    x = (lon / (2 * np.pi) + .5) * W; y = (.5 - lat / np.pi) * H; seg = [[]]
    for j in range(len(x)):
        if seg[-1] and abs(x[j] - seg[-1][-1][0]) > W / 2: seg.append([])
        seg[-1].append((x[j], y[j]))
    for s in seg:
        if len(s) > 1: cv2.polylines(img, [np.array(s, np.int32)], False, colour, 3, cv2.LINE_AA)
    cx, cy = int((np.radians(v['yaw']) / (2 * np.pi) + .5) * W) % W, int((.5 - np.radians(v['pitch']) / np.pi) * H)
    cv2.putText(img, label_text, (max(cx - 90, 4), max(cy, 24)), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 4, cv2.LINE_AA); cv2.putText(img, label_text, (max(cx - 90, 4), max(cy, 24)), cv2.FONT_HERSHEY_SIMPLEX, 0.7, colour, 2, cv2.LINE_AA)


def draw(folder, grid_dir, out_dir, clip, times):
    os.makedirs(out_dir, exist_ok=True); g = load_grid(grid_dir, clip); hz = float(g['hz']); n = len(g['tex']); path = os.path.join(folder, 'strata360', 'clips', clip, 'proxy.mp4'); tiles = []
    for t in times:
        raw = subprocess.run(['ffmpeg', '-v', 'error', '-ss', f'{t}', '-i', path, '-frames:v', '1', '-vf', 'scale=1600:800', '-pix_fmt', 'bgr24', '-f', 'rawvideo', '-'], stdout=subprocess.PIPE, check=True).stdout
        img = np.frombuffer(raw, np.uint8).reshape(800, 1600, 3).copy(); i = min(int(round(t * hz)), n - 1); ranked = best_views(g, i); first = ranked[0]
        second = next((v for v in ranked if abs(((v['yaw'] - first['yaw'] + 180) % 360) - 180) >= 60), None)
        for v, col, nm in ((first, (0, 255, 0), '1'), (second, (255, 255, 0), '2')):
            if v: draw_view(img, v, col, f"{nm}: q{v['score']:.2f} flat{v['flat_share']:.0%} fov{v['hfov']}")
        cv2.putText(img, f'{clip[4:19]}  t={t}s', (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2, cv2.LINE_AA); tiles.append(cv2.resize(img, (1200, 600)))
    out = os.path.join(out_dir, f'views_{clip[-6:-2]}.jpg'); cv2.imwrite(out, np.vstack(tiles), [cv2.IMWRITE_JPEG_QUALITY, 88]); print(out)


if __name__ == '__main__':
    ap = argparse.ArgumentParser(); ap.add_argument('mode'); ap.add_argument('folder'); ap.add_argument('grid'); ap.add_argument('out', nargs='?'); ap.add_argument('clip', nargs='?'); ap.add_argument('times', nargs='?'); a = ap.parse_args()
    if a.mode == 'corr': corr(a.folder, a.grid)
    else: draw(a.folder, a.grid, a.out, a.clip, [float(x) for x in a.times.split(',')])
