"""Experiment: the project's ways of enlarging a video clip against SeedVR2, on the same clip.

  python scripts/win_exp/vsr_compare.py INPUT.mp4 OUT_DIR FACTOR

Makes OUT_DIR/<method>.mp4 for: lanczos (the plain scaler: what the film does with enlarging off), realplksr (edit/upscale.py's default model, per frame), scunet_lanczos (SCUNet denoise at the source size, then the plain scaler: the
best of the earlier Mac tests, docs/progress/2026-10-music-upscale.md). SeedVR2 is run separately (models/exp/seedvr2-code, see docs/progress/2026-10-windows-gpu.md) into the same folder. `report` scores every mp4 there:
sharpness (Laplacian variance of the luma), flicker (mean absolute change between neighbouring frames of the luma, relative to the plain scaler's) and, with the source, the drift of the picture from the plain scaler's
(PSNR of the two downsampled to the source size: a method that invents less stays closer to what the camera saw)."""
import glob, os, subprocess, sys, time
import cv2
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))


def frames(path):
    cap = cv2.VideoCapture(path); out = []
    while True:
        ok, f = cap.read()
        if not ok: break
        out.append(f)
    return out


def write(path, imgs, fps=25):
    h, w = imgs[0].shape[:2]
    p = subprocess.Popen(['ffmpeg', '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-s', f'{w}x{h}', '-r', str(fps), '-i', '-', '-c:v', 'libx264', '-crf', '12', '-pix_fmt', 'yuv420p', path], stdin=subprocess.PIPE)
    for f in imgs: p.stdin.write(np.ascontiguousarray(f).tobytes())
    p.stdin.close(); p.wait()


def scunet(imgs):
    import torch
    from spandrel import ModelLoader
    m = ModelLoader().load_from_file('models/scunet/scunet_color_real_psnr.pth').model.eval().cuda(); out = []
    for f in imgs:
        x = torch.from_numpy(f[..., ::-1].copy()).permute(2, 0, 1).float().div(255)[None].cuda(); H, W = x.shape[-2:]; ph, pw = (-H) % 64, (-W) % 64
        with torch.no_grad(): y = m(torch.nn.functional.pad(x, (0, pw, 0, ph), mode='reflect'))[0, :, :H, :W].clamp(0, 1)
        out.append((y.permute(1, 2, 0).cpu().numpy()[..., ::-1] * 255 + .5).astype(np.uint8))
    return out


def report(folder, src):
    s = frames(src); rows = {}
    base = None
    for p in sorted(glob.glob(os.path.join(folder, '*.mp4'))):
        f = frames(p); g = [cv2.cvtColor(x, cv2.COLOR_BGR2GRAY).astype(np.float32) for x in f]
        sharp = float(np.mean([cv2.Laplacian(x, cv2.CV_32F).var() for x in g])); flick = float(np.mean([np.abs(g[i] - g[i - 1]).mean() for i in range(1, len(g))]))
        small = [cv2.resize(x, (s[0].shape[1], s[0].shape[0]), interpolation=cv2.INTER_AREA) for x in f]; mse = np.mean([np.mean((a.astype(np.float32) - b.astype(np.float32)) ** 2) for a, b in zip(small, s)])
        rows[os.path.basename(p)] = dict(frames=len(f), sharpness=round(sharp, 1), flicker=round(flick, 3), drift_psnr=round(float(10 * np.log10(255 ** 2 / max(mse, 1e-9))), 1))
    for k, v in rows.items(): print(k, v)
    return rows


def main():
    if sys.argv[1] == 'report': report(sys.argv[2], sys.argv[3]); return
    src, out, factor = sys.argv[1], sys.argv[2], int(sys.argv[3]); os.makedirs(out, exist_ok=True); imgs = frames(src); h, w = imgs[0].shape[:2]; size = (w * factor, h * factor); T = {}
    t = time.time(); lz = [cv2.resize(f, size, interpolation=cv2.INTER_LANCZOS4) for f in imgs]; T['lanczos'] = time.time() - t; write(os.path.join(out, 'lanczos.mp4'), lz)
    from strata360.edit import upscale as UP
    t = time.time(); m = UP.load(); y = [UP.upscale(f, factor, model=m) for f in imgs]; T['realplksr'] = time.time() - t; write(os.path.join(out, 'realplksr.mp4'), y)
    t = time.time(); d = scunet(imgs); z = [cv2.resize(f, size, interpolation=cv2.INTER_LANCZOS4) for f in d]; T['scunet_lanczos'] = time.time() - t; write(os.path.join(out, 'scunet_lanczos.mp4'), z)
    print({k: round(v / len(imgs), 3) for k, v in T.items()}, 's per frame')


if __name__ == '__main__': main()
