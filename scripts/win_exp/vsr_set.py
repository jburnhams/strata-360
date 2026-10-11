"""Experiment: a varied set of short clips for the video upscaler comparison (scripts/win_exp/vsr_compare.py, SeedVR2).

  python scripts/win_exp/vsr_set.py build PROJECT_FOLDER OUT_DIR       make the inputs: footage/ (1080p25 clips cut from the final film), streetview/ (the generated Google and Mapillary clips, 960x540, and a view of a panorama as the film would render it)
  python scripts/win_exp/vsr_set.py classic OUT_DIR                    the project's methods on every input: lanczos, realplksr, scunet_lanczos -> OUT_DIR/<set>/<method>/<name>.mp4
  python scripts/win_exp/vsr_set.py sheets OUT_DIR                     one picture per clip with the same crop of every method (OUT_DIR/sheets/<name>.jpg)
SeedVR2 goes into OUT_DIR/<set>/seedvr2/ (inference_cli.py on the folder)."""
import glob, os, subprocess, sys
import cv2
import numpy as np
sys.path.insert(0, os.path.dirname(__file__)); sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))
import vsr_compare as VC

FILM_TIMES = {'crowd_start': 3.0, 'you_close_a': 36.0, 'you_close_b': 45.0, 'speech_trail': 70.0, 'scene_forest': 97.0, 'person': 103.0, 'speech_a': 125.0, 'you_close_c': 192.0, 'you_close_d': 205.0, 'end_town': 247.0}
IN = {'footage': 'footage', 'streetview': 'streetview'}


def cut(src, t, out, n=9):
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-ss', f'{t}', '-i', src, '-vf', 'fps=25,scale=1920:1080:flags=lanczos', '-frames:v', str(n), '-c:v', 'libx264', '-crf', '8', '-pix_fmt', 'yuv420p', out], check=True)


def pano_view(pano, out, n=9, fov=85.0, yaw0=0.0, sweep=10.0, W=1920, H=1080):
    """The flat view the film renders from a panorama (rectilinear, `fov` wide), panning `sweep` degrees over n frames."""
    img = cv2.imread(pano); h, w = img.shape[:2]; f = (W / 2) / np.tan(np.radians(fov) / 2); xs, ys = np.meshgrid(np.arange(W) - W / 2 + 0.5, np.arange(H) - H / 2 + 0.5)
    frames = []
    for i in range(n):
        yaw = np.radians(yaw0 + sweep * i / max(n - 1, 1)); d = np.stack([xs, ys, np.full_like(xs, f)], -1); d /= np.linalg.norm(d, axis=-1, keepdims=True)
        x = d[..., 0] * np.cos(yaw) + d[..., 2] * np.sin(yaw); z = -d[..., 0] * np.sin(yaw) + d[..., 2] * np.cos(yaw); lon = np.arctan2(x, z); lat = np.arcsin(np.clip(-d[..., 1], -1, 1))
        frames.append(cv2.remap(img, ((lon / np.pi + 1) * 0.5 * w).astype(np.float32), ((0.5 - lat / np.pi) * h).astype(np.float32), cv2.INTER_CUBIC, borderMode=cv2.BORDER_WRAP))
    VC.write(out, frames)


def build(folder, out):
    P = os.path.join(folder, 'strata360'); film = glob.glob(os.path.join(P, 'final', 'af061ea030', 'film.mp4'))[0]
    for name, t in FILM_TIMES.items(): os.makedirs(os.path.join(out, 'footage', 'in'), exist_ok=True); cut(film, t, os.path.join(out, 'footage', 'in', name + '.mp4'))
    d = os.path.join(out, 'streetview', 'in'); os.makedirs(d, exist_ok=True)
    for name, f in (('google_flat', 'video/G+1-faa54de19a75.mp4'), ('mapillary_flat', 'video/M31-b587048f0955.mp4')):
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-ss', '2', '-i', os.path.join(P, 'streetview', f), '-frames:v', '9', '-c:v', 'libx264', '-crf', '8', '-pix_fmt', 'yuv420p', os.path.join(d, name + '.mp4')], check=True)
    panos = sorted(glob.glob(os.path.join(P, 'streetview', 'src', 'google', '*.pano.jpg')))
    for k, p in enumerate(panos[:2]): pano_view(p, os.path.join(d, f'google_pano_view{k}.mp4'), yaw0=60.0 * k)


def classic(out):
    for sset in ('footage', 'streetview'):
        for src in sorted(glob.glob(os.path.join(out, sset, 'in', '*.mp4'))):
            name = os.path.splitext(os.path.basename(src))[0]; imgs = VC.frames(src); h, w = imgs[0].shape[:2]; f = 2; size = (w * f, h * f)
            for m in ('lanczos', 'realplksr', 'scunet_lanczos'): os.makedirs(os.path.join(out, sset, m), exist_ok=True)
            VC.write(os.path.join(out, sset, 'lanczos', name + '.mp4'), [cv2.resize(x, size, interpolation=cv2.INTER_LANCZOS4) for x in imgs])
            from strata360.edit import upscale as UP
            m = UP.load(); VC.write(os.path.join(out, sset, 'realplksr', name + '.mp4'), [UP.upscale(x, f, model=m) for x in imgs])
            VC.write(os.path.join(out, sset, 'scunet_lanczos', name + '.mp4'), [cv2.resize(x, size, interpolation=cv2.INTER_LANCZOS4) for x in VC.scunet(imgs)]); print(sset, name, flush=True)


def sheets(out, frame=4):
    os.makedirs(os.path.join(out, 'sheets'), exist_ok=True)
    for sset in ('footage', 'streetview'):
        for src in sorted(glob.glob(os.path.join(out, sset, 'in', '*.mp4'))):
            name = os.path.splitext(os.path.basename(src))[0]; cells = []
            for m in ('lanczos', 'realplksr', 'scunet_lanczos', 'seedvr2'):
                p = os.path.join(out, sset, m, name + '.mp4')
                if not os.path.exists(p): continue
                cap = cv2.VideoCapture(p); cap.set(cv2.CAP_PROP_POS_FRAMES, frame); ok, f = cap.read()
                if not ok: continue
                c = f
                H, W = c.shape[:2]; c = c[H // 3:H // 3 + 540, W // 3:W // 3 + 800].copy(); cv2.putText(c, m, (8, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2); cells.append(c)
            if len(cells) >= 2:
                while len(cells) % 2: cells.append(np.zeros_like(cells[0]))
                cv2.imwrite(os.path.join(out, 'sheets', f'{sset}_{name}.jpg'), np.vstack([np.hstack(cells[i:i + 2]) for i in range(0, len(cells), 2)]), [cv2.IMWRITE_JPEG_QUALITY, 88])


if __name__ == '__main__':
    {'build': lambda: build(sys.argv[2], sys.argv[3]), 'classic': lambda: classic(sys.argv[2]), 'sheets': lambda: sheets(sys.argv[2])}[sys.argv[1]]()
