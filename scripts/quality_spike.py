"""Experiment (implementation plan C1 / cameras): per-area quality of a clip from its equirect proxy, on a 15 degree grid (12 x 24 cells) at a few frames a second.

  python scripts/quality_spike.py FOLDER CLIP_ID OUT_DIR [--hz 2] [--sheet T1,T2,...]

Writes OUT_DIR/<clip>.npz (channels below, shape (n, 12, 24)) and OUT_DIR/<clip>_sheet.jpg (frame + heat maps at chosen times).
Channels: fine (mean fine detail), mid (mean mid-scale detail), blur (fine/mid: low = blurry whatever the texture), tex (mid detail: low = featureless, sky, fog, a hand),
dark (dark channel mean: haze and fog raise it), contrast (luma std), sat (saturation), clip_hi / clip_lo (fraction of near-white / near-black pixels), luma."""
import argparse, os, subprocess, sys
import numpy as np, cv2

W, H, GR, GC = 1920, 960, 12, 24


def frames(path, hz):
    cmd = ['ffmpeg', '-v', 'error', '-threads', '2', '-i', path, '-an', '-vf', f'fps={hz},scale={W}:{H}:flags=area', '-pix_fmt', 'bgr24', '-f', 'rawvideo', '-']
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, bufsize=W * H * 3 * 2); n = W * H * 3
    while True:
        b = p.stdout.read(n)
        if len(b) < n: break
        yield np.frombuffer(b, np.uint8).reshape(H, W, 3)
    p.wait()


def cells(a): return a.reshape(GR, H // GR, GC, W // GC).mean((1, 3))


def measure(img):
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32); b1 = cv2.GaussianBlur(g, (0, 0), 1.0); b4 = cv2.GaussianBlur(g, (0, 0), 4.0)
    fine = np.abs(g - b1); mid = np.abs(b1 - b4); fc, mc = cells(fine), cells(mid)
    dark = cells(img.min(2).astype(np.float32)); mean = cells(g); contrast = np.sqrt(np.maximum(cells(g * g) - mean ** 2, 0))
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV); sat = cells(hsv[..., 1].astype(np.float32))
    return dict(fine=fc, mid=mc, blur=fc / (mc + 1.0), tex=mc, dark=dark, contrast=contrast, sat=sat, clip_hi=cells((g > 250).astype(np.float32)), clip_lo=cells((g < 8).astype(np.float32)), luma=mean)


def heat(m, lo, hi, cmap=cv2.COLORMAP_VIRIDIS):
    v = (np.clip((m - lo) / max(hi - lo, 1e-9), 0, 1) * 255).astype(np.uint8); return cv2.applyColorMap(cv2.resize(v, (W // 2, H // 2), interpolation=cv2.INTER_NEAREST), cmap)


def sheet(path, picks, series, ranges):
    rows = []
    for t, img in picks:
        i = int(round(t * series['hz'])); small = cv2.resize(img, (W // 2, H // 2), interpolation=cv2.INTER_AREA); cv2.putText(small, f't={t:.1f}s', (8, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2)
        panels = [small]
        for k in ('blur', 'tex', 'dark'):
            h = heat(series[k][i], *ranges[k]); cv2.putText(h, k, (8, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2); panels.append(h)
        rows.append(np.hstack([cv2.resize(p, (W // 4, H // 4)) for p in panels]))
    cv2.imwrite(path, np.vstack(rows), [cv2.IMWRITE_JPEG_QUALITY, 85])


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('folder'); ap.add_argument('clip'); ap.add_argument('out'); ap.add_argument('--hz', type=float, default=2.0); ap.add_argument('--sheet', default='')
    a = ap.parse_args(); os.makedirs(a.out, exist_ok=True)
    path = os.path.join(a.folder, 'strata360', 'clips', a.clip, 'proxy.mp4'); want = [float(x) for x in a.sheet.split(',') if x]; want_i = {int(round(t * a.hz)): t for t in want}
    out = {}; picks = []
    for i, img in enumerate(frames(path, a.hz)):
        for k, v in measure(img).items(): out.setdefault(k, []).append(v)
        if i in want_i: picks.append((want_i[i], img.copy()))
    series = {k: np.array(v, np.float32) for k, v in out.items()}; np.savez_compressed(os.path.join(a.out, a.clip + '.npz'), hz=a.hz, **series); series['hz'] = a.hz
    print(a.clip, 'frames', len(series['blur']), {k: (round(float(np.percentile(v, 5)), 3), round(float(np.median(v)), 3), round(float(np.percentile(v, 95)), 3)) for k, v in series.items() if k != 'hz'})
    if picks:
        ranges = {k: (float(np.percentile(series[k], 2)), float(np.percentile(series[k], 98))) for k in ('blur', 'tex', 'dark')}; sheet(os.path.join(a.out, a.clip + '_sheet.jpg'), picks, series, ranges)


if __name__ == '__main__':
    main()
