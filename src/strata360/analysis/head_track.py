"""Where the HEAD of a person is at every frame of a stretch of a clip, found directly (implementation plan: tracking for the You views).

The once-a-second detections of a person (their box and the face box) are not accurate enough to centre a tight shot on: the box centre moves with the arms, and the stored face centre is on the face in only a third of the frames checked. Here, for each proxy frame (25 a second) of the stretch, a stabilised perspective crop is taken around where the person is expected to be (the detections
of the neighbouring seconds, interpolated), YOLO pose is run on the crops (in `.venv-vision`, analysis/head_detect.py), and the head is the middle of the nose and the eyes it finds, as a direction in the world frame (yaw, pitch degrees).

crop_dirs(yaw, pitch, fov, px) and ray_to_yaw_pitch: the geometry of the crops; head_positions(...) the driver."""
import json, os, shutil, subprocess, tempfile

import cv2, numpy as np

from strata360.render.camera import direction

CROP_FOV, CROP_PX = 80.0, 640


def _basis(yaw, pitch):
    f = direction(np.radians(yaw), np.radians(pitch)); r = np.cross(f, [0.0, 0.0, 1.0]); r = r / max(np.linalg.norm(r), 1e-9); u = np.cross(r, f); return f, r, u


def crop_map(yaw, pitch, W, H, fov=CROP_FOV, px=CROP_PX):
    """cv2.remap maps (x, y) from the equirect (W x H) for a perspective crop of `fov` degrees, `px` pixels square, centred on (yaw, pitch)."""
    f, r, u = _basis(yaw, pitch); fp = (px / 2.0) / np.tan(np.radians(fov) / 2.0); i = (np.arange(px) - (px - 1) / 2.0) / fp
    X, Y = np.meshgrid(i, -i); ray = f[None, None, :] + X[..., None] * r[None, None, :] + Y[..., None] * u[None, None, :]
    lon = np.arctan2(ray[..., 0], ray[..., 1]); lat = np.arcsin(np.clip(ray[..., 2] / np.linalg.norm(ray, axis=-1), -1, 1))
    return (((lon / (2 * np.pi) + 0.5) % 1.0) * W).astype(np.float32), ((0.5 - lat / np.pi) * H).astype(np.float32)


def ray_to_yaw_pitch(x, y, yaw, pitch, fov=CROP_FOV, px=CROP_PX):
    """The world direction (yaw, pitch degrees) of the crop pixel (x, y)."""
    f, r, u = _basis(yaw, pitch); fp = (px / 2.0) / np.tan(np.radians(fov) / 2.0); ray = f + ((x - (px - 1) / 2.0) / fp) * r - ((y - (px - 1) / 2.0) / fp) * u; ray = ray / np.linalg.norm(ray)
    return float(np.degrees(np.arctan2(ray[0], ray[1]))), float(np.degrees(np.arcsin(np.clip(ray[2], -1, 1))))


def head_from_people(people, px=CROP_PX, min_conf=0.3):
    """(x, y, n) in crop pixels: the middle of the nose and eyes of the person nearest the centre of the crop that has at least one of them, n how many were used; None when there are none."""
    best = None
    for p in people:
        pts = [k for k in p['kp'][:3] if k[2] >= min_conf]
        if not pts: continue
        c = np.mean([[k[0], k[1]] for k in pts], axis=0); d = float(np.hypot(c[0] - px / 2, c[1] - px / 2))
        if best is None or d < best[0]: best = (d, c, len(pts))
    return None if best is None else (float(best[1][0]), float(best[1][1]), best[2])


def clean(yaw, pitch, win=9, max_jump=12.0):
    """The head series with the points that jump more than `max_jump` degrees from the running median of the `win` frames round them set to NaN (a wrong person or a mis-fired keypoint), and the lone survivors of a long gap dropped. Returns new arrays."""
    from scipy.ndimage import median_filter
    y = np.asarray(yaw, float).copy(); p = np.asarray(pitch, float).copy(); ok = np.isfinite(y) & np.isfinite(p)
    if ok.sum() < 3: return y, p
    idx = np.arange(len(y)); uy = np.degrees(np.unwrap(np.radians(np.interp(idx, idx[ok], y[ok])))); my = median_filter(uy, size=win, mode='nearest'); mp = median_filter(np.interp(idx, idx[ok], p[ok]), size=win, mode='nearest')
    bad = ok & (np.hypot((uy - my) * np.cos(np.radians(mp)), np.interp(idx, idx[ok], p[ok]) - mp) > max_jump); y[bad] = np.nan; p[bad] = np.nan; return y, p


def fill(t, yaw, pitch, max_gap_s=0.5):
    """The series with gaps of at most `max_gap_s` seconds filled by straight lines (yaw the short way round); longer gaps stay NaN."""
    t = np.asarray(t, float); y = np.asarray(yaw, float).copy(); p = np.asarray(pitch, float).copy(); ok = np.isfinite(y) & np.isfinite(p)
    if ok.sum() < 2: return y, p
    uy = np.degrees(np.unwrap(np.radians(y[ok]))); fy = np.interp(t, t[ok], uy); fp = np.interp(t, t[ok], p[ok]); idx = np.flatnonzero(ok); gap = np.zeros(len(t), bool)
    for a, b in zip(idx[:-1], idx[1:]):
        if t[b] - t[a] <= max_gap_s: gap[a + 1:b] = True
    y[gap] = fy[gap]; p[gap] = fp[gap]; return y, p


def head_positions(proxy_path, proxy_frames, t0, t1, centre, work_dir=None, keep=False, py=None):
    """(t, yaw, pitch, n) per proxy frame in [t0, t1] (NaN where no head was found; n the keypoints used), or None. `centre(t) -> (yaw, pitch)` is where the person is expected. The crops are made from the full-size proxy frames and detected in .venv-vision."""
    ts = np.array([f['t_s'] for f in proxy_frames]); k0 = int(np.argmin(np.abs(ts - t0))); k1 = int(np.argmin(np.abs(ts - t1))); n = k1 - k0 + 1
    probe = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries', 'stream=width,height', '-of', 'csv=p=0', proxy_path], capture_output=True, text=True).stdout.strip().split(','); W, H = int(probe[0]), int(probe[1])
    tmp = work_dir or tempfile.mkdtemp(prefix='s360head_'); os.makedirs(tmp, exist_ok=True); cens = []
    dec = subprocess.Popen(['ffmpeg', '-v', 'error', '-ss', f'{k0 / 25.0:.4f}', '-i', proxy_path, '-frames:v', str(n), '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-'], stdout=subprocess.PIPE, bufsize=W * H * 3 * 2)
    try:
        for i in range(n):
            buf = dec.stdout.read(W * H * 3)
            if len(buf) < W * H * 3: n = i; break
            fr = np.frombuffer(buf, np.uint8).reshape(H, W, 3); yaw, pitch = centre(float(ts[k0 + i])); cens.append((yaw, pitch)); mx, my = crop_map(yaw, pitch, W, H)
            cv2.imwrite(os.path.join(tmp, f'c{i:05d}.jpg'), cv2.remap(fr, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_WRAP), [cv2.IMWRITE_JPEG_QUALITY, 92])
    finally: dec.stdout.close(); dec.terminate(); dec.wait()
    if n == 0: return None
    py = py or os.path.join(os.path.dirname(__file__), '..', '..', '..', '.venv-vision', 'bin', 'python'); src = os.path.join(os.path.dirname(__file__), '..', '..'); out_json = os.path.join(tmp, 'det.json')
    subprocess.run([py, '-m', 'strata360.analysis.head_detect', tmp, out_json], check=True, env={**os.environ, 'PYTHONPATH': src, 'PYTHONWARNINGS': 'ignore'}, stdout=subprocess.PIPE)
    det = json.load(open(out_json))['frames']; yaw = np.full(n, np.nan); pitch = np.full(n, np.nan); used = np.zeros(n, int)
    for i in range(n):
        h = head_from_people(det.get(str(i), []))
        if h: yaw[i], pitch[i] = ray_to_yaw_pitch(h[0], h[1], *cens[i]); used[i] = h[2]
    if not keep and not work_dir: shutil.rmtree(tmp, ignore_errors=True)
    yaw, pitch = clean(yaw, pitch); return ts[k0:k0 + n], yaw, pitch, used
