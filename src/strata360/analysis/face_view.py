"""`face_view` stage: how clearly the wearer's FACE is seen, once a second, for the close view of you (implementation plan: the close view is for clear face shots, not the top of the head).

At every second the wearer was found (identity.json, as the `focus_samples`), a stabilised crop of the proxy video around them is taken (analysis/head_track.py) and YOLO pose is run on it (analysis/head_detect.py, in `.venv-vision`). The face is clear when the nose and BOTH eyes are found with confidence: a view of the top of the head, a face turned down or away, or a hat over the eyes does not give them.
Output `face_view.json`: samples [{t, score}] with score = the lowest confidence of nose, left eye and right eye (0 when the wearer or a keypoint is missing)."""
import json, os, subprocess, tempfile

import cv2, numpy as np

from strata360.analysis import head_track as HT, views

CLEAR = 0.5                   # a sample counts as a clear face from this score


def analyse(clip_dir, osv, log=print):
    samples = sorted(views.focus_samples(clip_dir, osv), key=lambda x: x['t']); pj = os.path.join(clip_dir, 'proxy.json'); proxy = os.path.join(clip_dir, 'proxy.mp4')
    if not samples or not os.path.exists(pj) or not os.path.exists(proxy): return dict(samples=[], note='no wearer samples or no proxy')
    frames = json.load(open(pj))['frames']; ts = np.array([f['t_s'] for f in frames]); idx = [int(np.argmin(np.abs(ts - x['t']))) for x in samples]; order = sorted(set(idx))
    probe = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries', 'stream=width,height', '-of', 'csv=p=0', proxy], capture_output=True, text=True).stdout.strip().split(','); W, H = int(probe[0]), int(probe[1]); tmp = tempfile.mkdtemp(prefix='s360face_')
    where = {k: j for j, k in enumerate(order)}; crops = {}
    for k in order:                                                                                      # one frame at a time by seeking (the proxy is written at a fixed 25 fps, so frame k is at k / 25 s)
        r = subprocess.run(['ffmpeg', '-v', 'error', '-ss', f'{k / 25.0:.4f}', '-i', proxy, '-frames:v', '1', '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-'], capture_output=True)
        if len(r.stdout) < W * H * 3: raise RuntimeError(f'face_view: could not read proxy frame {k} of {os.path.basename(clip_dir)}: {r.stderr.decode(errors="replace")[-200:]}')
        fr = np.frombuffer(r.stdout, np.uint8)[:W * H * 3].reshape(H, W, 3); x = samples[idx.index(k)]; mx, my = HT.crop_map(x['yaw'], x['pitch'], W, H)
        cv2.imwrite(os.path.join(tmp, f'c{where[k]:05d}.jpg'), cv2.remap(fr, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_WRAP), [cv2.IMWRITE_JPEG_QUALITY, 92]); crops[k] = where[k]
    py = os.path.join(os.path.dirname(__file__), '..', '..', '..', '.venv-vision', 'bin', 'python'); src = os.path.join(os.path.dirname(__file__), '..', '..'); out_json = os.path.join(tmp, 'det.json')
    subprocess.run([py, '-m', 'strata360.analysis.head_detect', tmp, out_json], check=True, env={**os.environ, 'PYTHONPATH': src, 'PYTHONWARNINGS': 'ignore'}, stdout=subprocess.PIPE)
    det = json.load(open(out_json))['frames']; out = []
    for x, k in zip(samples, idx):
        score = 0.0
        if k in crops:
            best = None
            for p in det.get(str(crops[k]), []):                                                          # the person nearest the middle of the crop
                kp = p['kp'][:3]; c = np.hypot((p['box'][0] + p['box'][2]) / 2 - HT.CROP_PX / 2, (p['box'][1] + p['box'][3]) / 2 - HT.CROP_PX / 2)
                if best is None or c < best[0]: best = (c, min(q[2] for q in kp))
            score = 0.0 if best is None else float(best[1])
        out.append(dict(t=x['t'], score=round(score, 2)))
    log(f'face_view: {sum(1 for o in out if o["score"] >= CLEAR)} of {len(out)} seconds with a clear face')
    return dict(samples=out, clear=CLEAR)
