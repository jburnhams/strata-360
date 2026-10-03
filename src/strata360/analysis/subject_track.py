"""Where a person is at EVERY frame of a stretch of a clip, from the once-a-second detections and the proxy video (implementation plan: tracking for the You views).

A runner swings and bobs about the camera at running cadence, so detections a second apart sample that motion at random (on clip 0021 of the Legends race the direction to the wearer, in the camera's own frame, varies by about 10 degrees from one detection to the next and cannot be predicted from its neighbours). Between two detections the person is
followed through the proxy video (upright equirect, world-locked: the camera's swing shows as the person's motion) by tracking features inside their box frame to frame (Lucas-Kanade, the median displacement of the features: the person's translation); the track forward from the earlier detection and the track backward from the later one
are blended (the first at the start, the second at the end), so the result passes through both detections and follows the motion between them.

track_positions(frames, boxes, anchors) -> (yaw, pitch) in degrees per frame, from `frames` (gray equirect pictures, consecutive), the anchors [(frame index, yaw, pitch, height_deg)];
window_track(proxy_path, proxy_frames, t0, t1, anchors) -> (t, yaw, pitch) per proxy frame in [t0, t1], or None.
Equirect layout (render/proxy.py): the centre column is world +Y, longitude (yaw) grows to the right, latitude (pitch) up."""
import hashlib, json, os, subprocess

import cv2, numpy as np

SCALE_W = 1920                 # the proxy frames are tracked at this width
MIN_FEATURES = 12


def to_px(yaw, pitch, W, H): return ((np.asarray(yaw, float) / 360.0 + 0.5) % 1.0) * W, (0.5 - np.asarray(pitch, float) / 180.0) * H


def to_deg(x, y, W, H):
    yaw = (np.asarray(x, float) / W - 0.5) * 360.0; pitch = (0.5 - np.asarray(y, float) / H) * 180.0; return yaw, pitch


def _box(cx, cy, height_deg, W, H):
    hh = max(float(height_deg or 40.0) / 180.0 * H, 24.0) / 2.0; ww = hh * 0.6; return int(max(cx - ww, 0)), int(max(cy - hh, 0)), int(min(cx + ww, W - 1)), int(min(cy + hh, H - 1))


def _follow(frames, k0, k1, x, y, height_deg, W, H):
    """The (x, y) pixel position of a person at frame k0 followed to frame k1 (either direction): positions per frame from k0 to k1 inclusive."""
    step = 1 if k1 >= k0 else -1; ks = list(range(k0, k1 + step, step)); out = [(x, y)]; pts = None; cur = np.array([x, y], float)
    for a, b in zip(ks[:-1], ks[1:]):
        if pts is None or len(pts) < MIN_FEATURES:
            x0, y0, x1, y1 = _box(cur[0], cur[1], height_deg, W, H); m = np.zeros(frames[a].shape[:2], np.uint8); m[y0:y1, x0:x1] = 255
            pts = cv2.goodFeaturesToTrack(frames[a], maxCorners=200, qualityLevel=0.01, minDistance=5, mask=m)
        if pts is None or len(pts) < 4: out.append(tuple(cur)); pts = None; continue
        nxt, st, _ = cv2.calcOpticalFlowPyrLK(frames[a], frames[b], pts, None, winSize=(21, 21), maxLevel=3); ok = st.ravel() == 1
        if ok.sum() < 4: out.append(tuple(cur)); pts = None; continue
        d = np.median((nxt - pts).reshape(-1, 2)[ok], axis=0); cur = cur + d; out.append(tuple(cur)); pts = nxt[ok]
    return np.array(out)


def blend(fwd, bwd):
    """Positions between two detections from the track forward from the first (fwd, starting at the first detection) and the track backward from the second (bwd, starting at the second, so reversed here): the first counts at the start, the second at the end."""
    n = len(fwd); s = np.linspace(0.0, 1.0, n)[:, None]; return (1.0 - s) * fwd + s * bwd[::-1]


def track_positions(frames, anchors):
    """(yaw, pitch) in degrees for every frame from the first anchor to the last, tracked between consecutive anchors and blended; NaN outside that range. `frames` are gray pictures, consecutive, frame 0 being the first; `anchors` are [(frame, yaw, pitch, height_deg)] sorted by frame.
    Each stretch is rolled sideways so the person starts in the middle of the picture (the equirect wraps round at the edges), and the result is rolled back."""
    H, W = frames[0].shape[:2]; out = np.full((len(frames), 2), np.nan)
    px = [(a[0],) + tuple(float(v) for v in to_px(a[1], a[2], W, H)) + (a[3],) for a in anchors]
    for (ka, xa, ya, ha), (kb, xb, yb, hb) in zip(px, px[1:]):
        if kb <= ka: continue
        shift = int(round(W / 2 - xa)); seg = [np.roll(f, shift, axis=1) for f in frames[ka:kb + 1]]; xa2 = xa + shift; xb2 = xa2 + (((xb - xa + W / 2) % W) - W / 2)               # the shorter way round
        fwd = _follow(seg, 0, len(seg) - 1, xa2, ya, ha, W, H); bwd = _follow(seg, len(seg) - 1, 0, xb2, yb, hb, W, H)
        pos = blend(fwd, bwd); out[ka:kb + 1, 0] = pos[:, 0] - shift; out[ka:kb + 1, 1] = pos[:, 1]
    yaw, pitch = to_deg(out[:, 0], out[:, 1], W, H); return yaw, pitch


def decode_gray(proxy_path, first_frame, count, fps=25.0, width=SCALE_W):
    """`count` consecutive frames of the proxy video from frame `first_frame` (the file is written at a fixed `fps`, so frame i is at i / fps), gray, scaled to `width`; fewer when the file ends."""
    probe = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries', 'stream=width,height', '-of', 'csv=p=0', proxy_path], capture_output=True, text=True).stdout.strip().split(',')
    w0, h0 = int(probe[0]), int(probe[1]); w = width; h = int(round(h0 * w / w0 / 2)) * 2
    cmd = ['ffmpeg', '-v', 'error', '-ss', f'{first_frame / fps:.4f}', '-i', proxy_path, '-frames:v', str(count), '-vf', f'scale={w}:{h},format=gray', '-f', 'rawvideo', '-']
    raw = subprocess.run(cmd, capture_output=True).stdout; n = len(raw) // (w * h)
    return [np.frombuffer(raw[i * w * h:(i + 1) * w * h], np.uint8).reshape(h, w) for i in range(n)]


def window_track(proxy_path, proxy_frames, t0, t1, samples, fps=25.0, reach_s=2.5, cache_dir=None):
    """(t, yaw, pitch) per proxy frame from the first to the last detection inside [t0 - reach_s, t1 + reach_s], or None when fewer than two detections (or no proxy). `proxy_frames` is proxy.json's `frames` ([{proxy_frame, t_s}]), `samples` the you detections ({t, yaw, pitch, height})."""
    if not proxy_path or not os.path.exists(proxy_path) or not proxy_frames: return None
    s = sorted((x for x in samples if t0 - reach_s <= x['t'] <= t1 + reach_s), key=lambda x: x['t'])
    if len(s) < 2: return None
    ts = np.array([f['t_s'] for f in proxy_frames]); idx = [int(np.argmin(np.abs(ts - x['t']))) for x in s]; k0, k1 = idx[0], idx[-1]
    if k1 <= k0: return None
    anchors = [(i - k0, x['yaw'], x['pitch'], x.get('height')) for i, x in zip(idx, s)]; cache = None
    if cache_dir:                                                                                          # the same stretch is asked for again every time a plan is resolved: kept, until the proxy or the detections change
        st = os.stat(proxy_path); key = hashlib.sha1(json.dumps([st.st_mtime_ns, st.st_size, k0, k1, [[a[0], round(a[1], 2), round(a[2], 2), a[3]] for a in anchors]]).encode()).hexdigest()[:16]; cache = os.path.join(cache_dir, f'{key}.npz')
        if os.path.exists(cache):
            with np.load(cache) as z: return ts[k0:k1 + 1], z['yaw'], z['pitch']
    frames = decode_gray(proxy_path, k0, k1 - k0 + 1, fps)
    if len(frames) < k1 - k0 + 1: return None
    yaw, pitch = track_positions(frames, anchors)
    if cache: os.makedirs(cache_dir, exist_ok=True); np.savez(cache + '.tmp.npz', yaw=yaw, pitch=pitch); os.replace(cache + '.tmp.npz', cache)
    return ts[k0:k1 + 1], yaw, pitch
