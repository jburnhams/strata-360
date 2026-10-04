"""Body-frame rectilinear analysis views for the detectors (people, faces, later scenes).

Six 100-degree views around the camera's horizon (body frame: +Y is the front lens, -Y the rear lens, +Z up along the stick), each cut straight from
the fisheye frames with maps computed once per clip, so a sample costs a decode plus six remaps. They are NOT stabilised: detectors do not need it, and
keeping them body-fixed means the wearer (on the selfie stick) is always in the same view. Views are numbered by the yaw of their centre from the front
lens: 0 front, 60, 120, 180 = straight at the wearer (rear lens), 240, 300."""
import json, math, os, subprocess, numpy as np, cv2
from strata360.osv.calib import read_slots, Lens
from strata360 import hw

VIEW_YAWS = (0, 60, 120, 180, 240, 300)
VIEW_PX = 1024
VIEW_FOV = 100.0
LENS_PX = 2048


def view_rays(yaw_deg, px=VIEW_PX, fov=VIEW_FOV, pitch_deg=0.0):
    a = np.radians(yaw_deg); p = np.radians(pitch_deg)
    f = np.array([np.sin(a) * np.cos(p), np.cos(a) * np.cos(p), np.sin(p)]); r = np.array([np.cos(a), -np.sin(a), 0.0]); u = np.cross(r, f)
    t = np.tan(np.radians(fov) / 2); g = ((np.arange(px) + 0.5) / px * 2 - 1) * t
    X, Y = np.meshgrid(g, -g)
    d = f[None, None] + X[..., None] * r[None, None] + Y[..., None] * u[None, None]
    return (d / np.linalg.norm(d, axis=-1, keepdims=True)).reshape(-1, 3)


class Views:
    def __init__(self, osv, yaws=VIEW_YAWS, px=VIEW_PX, fov=VIEW_FOV):
        sl = read_slots(osv); self.master, self.slave = Lens(sl[2]), Lens(sl[1]); self.yaws, self.px, self.fov = yaws, px, fov
        sc = LENS_PX / 3840.0; self.maps = []
        for y in yaws:
            d = view_rays(y, px, fov); um, vm, _ = self.master.project(d, sc); us, vs, _ = self.slave.project(d, sc)
            w = np.clip(0.5 + d[:, 1] / np.sin(np.radians(6.0)), 0, 1).reshape(px, px, 1).astype(np.float32)      # master in front of y=0, slave behind, 6 degree blend
            f = lambda a: a.astype(np.float32).reshape(px, px)
            self.maps.append((f(um), f(vm), f(us), f(vs), w))

    def render(self, frame_m, frame_s):
        out = []
        for um, vm, us, vs, w in self.maps:
            a = cv2.remap(frame_m, um, vm, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT); b = cv2.remap(frame_s, us, vs, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)
            out.append((a * w + b * (1 - w)).astype(np.uint8))
        return out


def decode(osv, stream, every):
    cmd = ['ffmpeg', '-v', 'error', *hw.hwaccel_args(), '-i', osv, '-map', f'0:v:{stream}', '-fps_mode', 'passthrough',
           '-vf', f"select='not(mod(n\\,{every}))',scale={LENS_PX}:{LENS_PX}:flags=area", '-pix_fmt', 'rgb24', '-f', 'rawvideo', '-']
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, bufsize=LENS_PX * LENS_PX * 3 * 2); n = LENS_PX * LENS_PX * 3; k = 0
    while True:
        buf = p.stdout.read(n)
        if len(buf) < n: break
        yield k * every, np.frombuffer(buf, np.uint8).reshape(LENS_PX, LENS_PX, 3); k += 1
    p.wait()


def write_views(osv, out_dir, every=25, first=None, quality=93, yaws=VIEW_YAWS, px=VIEW_PX):
    """Writes out_dir/s{k:05d}_v{yaw:03d}.jpg for every `every`-th frame; returns the list of sampled frame indices."""
    os.makedirs(out_dir, exist_ok=True); V = Views(osv, yaws=yaws, px=px); ks = []
    for (k, m), (k2, s) in zip(decode(osv, 1, every), decode(osv, 0, every)):
        for y, img in zip(V.yaws, V.render(m, s)):
            cv2.imwrite(f'{out_dir}/s{k:05d}_v{y:03d}.jpg', img[:, :, ::-1], [cv2.IMWRITE_JPEG_QUALITY, quality])
        ks.append(int(k))
        if first and len(ks) >= first: break
    return ks


# ---- stabilised (upright, heading-relative) views: what detectors and the VLM should see ---------------------------------------------------------------------------------
# Body-frame views are tilted (the camera on the stick is rolled) and swing with every arm movement, so people, faces and scenes arrive at odd angles. Stabilised views are cut from the
# upright world frame: horizon level, and the view direction is measured from the runner's smoothed heading (0 = ahead, 90 = right, 180 = behind, where the wearer normally is).

STAB_YAWS = (0, 90, 180, 270)


def stab_view_rays(yaw_deg, heading_rad, px, fov, pitch_deg=0.0):
    """Rays (N, 3) in the upright world frame (X right, Y forward, Z up) for a view `yaw_deg` from the heading."""
    psi = heading_rad + np.radians(yaw_deg); p = np.radians(pitch_deg)
    f = np.array([np.sin(psi) * np.cos(p), np.cos(psi) * np.cos(p), np.sin(p)]); r = np.array([np.cos(psi), -np.sin(psi), 0.0]); u = np.cross(r, f)
    t = np.tan(np.radians(fov) / 2); g = ((np.arange(px) + 0.5) / px * 2 - 1) * t; X, Y = np.meshgrid(g, -g)
    d = f[None, None] + X[..., None] * r[None, None] + Y[..., None] * u[None, None]
    return (d / np.linalg.norm(d, axis=-1, keepdims=True)).reshape(-1, 3)


class StabViews:
    def __init__(self, osv, yaws=STAB_YAWS, px=VIEW_PX, fov=VIEW_FOV, lens_px=LENS_PX):
        from strata360.osv.calib import quat_to_R, imu_offsets
        from strata360.osv.telemetry import read_frames
        from strata360.render.camera import heading_series
        sl = read_slots(osv); self.master, self.slave = Lens(sl[2]), Lens(sl[1]); self.yaws, self.px, self.fov, self.lens_px = yaws, px, fov, lens_px
        P, B = imu_offsets(); T = read_frames(osv); fps = (len(T['ts_us']) - 1) / max((T['ts_us'][-1] - T['ts_us'][0]) / 1e6, 1e-6)
        self.Ms = np.array([B.T @ quat_to_R(q).T @ P.T for q in T['quat']]); self.heading = heading_series(self.Ms, tau_s=2.0, fps=fps)

    def render(self, k, frame_m, frame_s):
        M = self.Ms[min(k, len(self.Ms) - 1)]; h = self.heading[min(k, len(self.heading) - 1)]; sc = self.lens_px / 3840.0; out = []
        for y in self.yaws:
            dE = stab_view_rays(y, h, self.px, self.fov); d = np.einsum('nj,ij->ni', dE, M)                         # d_body = M d_E
            um, vm, _ = self.master.project(d, sc); us, vs, _ = self.slave.project(d, sc)
            w = np.clip(0.5 + d[:, 1] / np.sin(np.radians(6.0)), 0, 1).reshape(self.px, self.px, 1).astype(np.float32); f = lambda a: a.astype(np.float32).reshape(self.px, self.px)
            a = cv2.remap(frame_m, f(um), f(vm), cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT); b = cv2.remap(frame_s, f(us), f(vs), cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)
            out.append((a * w + b * (1 - w)).astype(np.uint8))
        return out


def write_stab_views(osv, out_dir, every=25, first=None, quality=93, yaws=STAB_YAWS, px=VIEW_PX, fov=VIEW_FOV):
    """Like write_views but upright and heading-relative; files s{frame}_v{yaw}.jpg (yaw from the heading)."""
    os.makedirs(out_dir, exist_ok=True); V = StabViews(osv, yaws=yaws, px=px, fov=fov); ks = []
    for (k, m), (k2, s) in zip(decode(osv, 1, every), decode(osv, 0, every)):
        for y, img in zip(V.yaws, V.render(k, m, s)):
            cv2.imwrite(f'{out_dir}/s{k:05d}_v{y:03d}.jpg', img[:, :, ::-1], [cv2.IMWRITE_JPEG_QUALITY, quality])
        ks.append(int(k))
        if first and len(ks) >= first: break
    return ks


def _rect_rays(yaw_deg, heading_rad, w, h, hfov, pitch_deg=0.0):
    psi = heading_rad + np.radians(yaw_deg); p = np.radians(pitch_deg)
    f = np.array([np.sin(psi) * np.cos(p), np.cos(psi) * np.cos(p), np.sin(p)]); r = np.array([np.cos(psi), -np.sin(psi), 0.0]); u = np.cross(r, f)
    tx = np.tan(np.radians(hfov) / 2); ty = tx * h / w; X, Y = np.meshgrid(((np.arange(w) + 0.5) / w * 2 - 1) * tx, -((np.arange(h) + 0.5) / h * 2 - 1) * ty)
    d = f[None, None] + X[..., None] * r[None, None] + Y[..., None] * u[None, None]
    return (d / np.linalg.norm(d, axis=-1, keepdims=True)).reshape(-1, 3)


def grab_frame(osv, stream, t, size=LENS_PX):
    """One decoded frame (RGB uint8, size x size) of a lens stream at time t seconds."""
    raw = subprocess.run(['ffmpeg', '-v', 'error', '-ss', f'{max(t, 0):.3f}', '-i', osv, '-map', f'0:v:{stream}', '-frames:v', '1', '-vf', f'scale={size}:{size}:flags=area', '-pix_fmt', 'rgb24', '-f', 'rawvideo', '-'],
                         stdout=subprocess.PIPE, check=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(size, size, 3)


def render_thumb(osv, t, yaw=0.0, pitch=0.0, hfov=95.0, w=960, h=540, stab=None, quality=90):
    """A flat, upright 16:9 view of the clip at time `t` (seconds), `yaw` degrees from the runner's heading (0 = ahead, 180 = behind). Returns JPEG bytes."""
    from strata360.osv.mp4 import video_sample_times
    stab = stab or StabViews(osv, yaws=(0,)); pts = video_sample_times(osv); k = int(np.clip(np.searchsorted(pts, pts[0] + t), 0, len(pts) - 1))
    fm, fs = grab_frame(osv, 1, pts[k]), grab_frame(osv, 0, pts[k]); M = stab.Ms[min(k, len(stab.Ms) - 1)]; hd = stab.heading[min(k, len(stab.heading) - 1)]
    dE = _rect_rays(yaw, hd, w, h, hfov, pitch); d = np.einsum('nj,ij->ni', dE, M); sc = LENS_PX / 3840.0
    um, vm, _ = stab.master.project(d, sc); us, vs, _ = stab.slave.project(d, sc); f = lambda a: a.astype(np.float32).reshape(h, w)
    wt = np.clip(0.5 + d[:, 1] / np.sin(np.radians(6.0)), 0, 1).reshape(h, w, 1).astype(np.float32)
    a = cv2.remap(fm, f(um), f(vm), cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT); b = cv2.remap(fs, f(us), f(vs), cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)
    img = (a * wt + b * (1 - wt)).astype(np.uint8); ok, buf = cv2.imencode('.jpg', img[:, :, ::-1], [cv2.IMWRITE_JPEG_QUALITY, quality]); return buf.tobytes()


# ---- crops: a small detector box re-rendered at lens resolution ---------------------------------------------------------------------------------------------------------------
# A box found in a 1024 px analysis view can be too small for a labelling model to tell what it is. It is then cut straight from the full-size lens frame (about twice the detail of the proxy or
# of the views). One moment's lens frames are decoded once and every box of that moment is cut from them; a crop wholly in front of or behind the seam comes from one lens (no blending, and the
# other lens is not decoded).

CROP_PX = 448
CROP_WANT_PX = 96            # an object this many pixels long in the picture given to the labelling model can be identified
LENS_FULL = 3840             # the lens video's own size
NATIVE_PPD = 20.0            # lens pixels per degree at the middle of a lens (3840 px over about 190 degrees)
SEAM = math.sin(math.radians(6.0))


def crop_plan(box, view_px=VIEW_PX, fov=VIEW_FOV, want_px=CROP_WANT_PX, native_ppd=NATIVE_PPD):
    """How to get a picture of a detector box [x0, y0, x1, y1] found in an analysis view: ('view', deg) when it already has `want_px` pixels on its long side (cut it from the view or the proxy),
    ('native', deg) when it is smaller and the lens frame holds clearly more detail, ('tiny', deg) when even the lens frame cannot give it a third of `want_px` pixels. deg is its long side in degrees."""
    f = (view_px / 2) / math.tan(math.radians(fov / 2)); long_px = max(box[2] - box[0], box[3] - box[1]); deg = math.degrees(long_px / f)
    if long_px >= want_px: return 'view', deg
    if deg * native_ppd < want_px / 3: return 'tiny', deg
    return ('native' if deg * native_ppd > long_px * 1.3 else 'view'), deg


def crop_rays(lon, lat, fov, px=CROP_PX):
    """Unit rays (px, px, 3) in the upright world frame (X right, Y forward, Z up) of a square flat view centred on longitude `lon` and latitude `lat` (radians; lon 0 is the middle column of the proxy)
    with a field of view of `fov` degrees."""
    f = np.array([math.sin(lon) * math.cos(lat), math.cos(lon) * math.cos(lat), math.sin(lat)]); r = np.array([math.cos(lon), -math.sin(lon), 0.0]) if abs(math.cos(lat)) > 1e-6 else np.array([1.0, 0, 0]); u = np.cross(r, f)
    g = ((np.arange(px) + 0.5) / px * 2 - 1) * math.tan(math.radians(fov) / 2); X, Y = np.meshgrid(g, -g)
    d = f[None, None] + X[..., None] * r[None, None] + Y[..., None] * u[None, None]
    return d / np.linalg.norm(d, axis=-1, keepdims=True)


def lens_choice(y):
    """Which lens a set of body-frame rays needs, from their forward components `y`: 'master' (the front lens) when all are ahead of the 6 degree seam, 'slave' when all are behind it, else 'both'."""
    if np.all(y > SEAM): return 'master'
    if np.all(y < -SEAM): return 'slave'
    return 'both'


class CropRenderer:
    """Flat crops of one clip, cut from the full-size lens frames. `crop(t, lon, lat, fov)` returns an RGB uint8 picture; ask for all the boxes of a moment in a row and its lens frames are decoded once."""
    def __init__(self, osv, stab=None):
        from strata360.osv.mp4 import video_sample_times
        self.osv = osv; self.stab = stab or StabViews(osv, yaws=(0,)); self.pts = video_sample_times(osv); self._k = None; self._frames = {}

    def _frame(self, stream, k):
        if k != self._k: self._k, self._frames = k, {}
        if stream not in self._frames: self._frames[stream] = grab_frame(self.osv, stream, self.pts[k], size=LENS_FULL)
        return self._frames[stream]

    def crop(self, t, lon, lat, fov, px=CROP_PX):
        k = int(np.clip(np.searchsorted(self.pts, self.pts[0] + t), 0, len(self.pts) - 1)); M = self.stab.Ms[min(k, len(self.stab.Ms) - 1)]
        db = np.einsum('nj,ij->ni', crop_rays(lon, lat, fov, px).reshape(-1, 3), M); f = lambda a: a.astype(np.float32).reshape(px, px)       # d_body = M d_E
        def cut(lens, stream):
            u, v, _ = lens.project(db, LENS_FULL / 3840.0); return cv2.remap(self._frame(stream, k), f(u), f(v), cv2.INTER_CUBIC, borderMode=cv2.BORDER_CONSTANT)
        c = lens_choice(db[:, 1])
        if c == 'master': return cut(self.stab.master, 1)
        if c == 'slave': return cut(self.stab.slave, 0)
        w = np.clip(0.5 + db[:, 1] / SEAM, 0, 1).reshape(px, px, 1).astype(np.float32)
        return (cut(self.stab.master, 1) * w + cut(self.stab.slave, 0) * (1 - w)).astype(np.uint8)


# ---- views cut from the clip's proxy (one early render that the other stages share) ------------------------------------------------------------------------------------------
# The `proxy` stage renders the clip once as an upright, world-locked equirect (3840x1920, 25 fps, HEVC). Detectors, the scene model and thumbnails then cut their flat views from that
# file: no repeated decoding of the two huge lens streams. The equirect is world-locked, so a heading-relative view is just a rotation of the sampling rays (same heading track as StabViews).

def heading_track(osv):
    """(heading radians per source frame, source fps): the same smoothed heading StabViews uses, so results from the two paths agree."""
    from strata360.osv.calib import quat_to_R, imu_offsets
    from strata360.osv.telemetry import read_frames
    from strata360.render.camera import heading_series
    P, B = imu_offsets(); T = read_frames(osv); fps = (len(T['ts_us']) - 1) / max((T['ts_us'][-1] - T['ts_us'][0]) / 1e6, 1e-6)
    Ms = np.array([B.T @ quat_to_R(q).T @ P.T for q in T['quat']]); return heading_series(Ms, tau_s=2.0, fps=fps), fps


def proxy_available(proxy_path):
    return bool(proxy_path) and os.path.exists(proxy_path) and os.path.getsize(proxy_path) > 0 and os.path.exists(os.path.splitext(proxy_path)[0] + '.json')


def _equirect_view(eq, dE, w, h):
    """Sample an equirect frame (H, W, 3) along world rays dE (N, 3): returns an (h, w, 3) picture."""
    H, W = eq.shape[:2]; lon = np.arctan2(dE[:, 0], dE[:, 1]); lat = np.arcsin(np.clip(dE[:, 2], -1, 1))
    mx = ((lon / (2 * np.pi) + 0.5) * W - 0.5).astype(np.float32).reshape(h, w); my = ((0.5 - lat / np.pi) * H - 0.5).astype(np.float32).reshape(h, w)
    return cv2.remap(eq, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_WRAP)


def write_stab_views_proxy(proxy_path, osv, out_dir, every=25, yaws=STAB_YAWS, px=VIEW_PX, fov=VIEW_FOV, quality=93, times=None):
    """Like write_stab_views, but decoded from the clip's proxy (every `every` SOURCE frames; the proxy keeps every 2nd or 4th), or at the clip times `times` (seconds) when given. Files s{source_frame:05d}_v{yaw:03d}.jpg."""
    side = json.load(open(os.path.splitext(proxy_path)[0] + '.json')); frames = side['frames']; heading, _ = heading_track(osv); os.makedirs(out_dir, exist_ok=True)
    if times is not None: return _write_stab_views_at(proxy_path, side, heading, out_dir, times, yaws, px, fov, quality)
    step = max(int(round(every / side['every_n_source_frames'])), 1); W, H = side['size']
    cmd = ['ffmpeg', '-v', 'error', '-i', proxy_path, '-fps_mode', 'passthrough', '-vf', f"select='not(mod(n\\,{step}))'", '-pix_fmt', 'rgb24', '-f', 'rawvideo', '-']
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, bufsize=W * H * 3 * 2); n = W * H * 3; j = 0; ks = []
    while True:
        buf = p.stdout.read(n)
        if len(buf) < n: break
        eq = np.frombuffer(buf, np.uint8).reshape(H, W, 3); k = frames[min(j * step, len(frames) - 1)]['source_frame']; h = heading[min(k, len(heading) - 1)]
        for y in yaws:
            img = _equirect_view(eq, stab_view_rays(y, h, px, fov), px, px); cv2.imwrite(f'{out_dir}/s{k:05d}_v{y:03d}.jpg', img[:, :, ::-1], [cv2.IMWRITE_JPEG_QUALITY, quality])
        ks.append(int(k)); j += 1
    p.wait(); return ks


def _write_stab_views_at(proxy_path, side, heading, out_dir, times, yaws, px, fov, quality):
    """The views of write_stab_views_proxy at the proxy frames nearest the clip times `times` (one frame decoded at a time); returns the source frame of each."""
    W, H = side['size']; ft = np.array([f['t_s'] for f in side['frames']]); ks = []
    for t in times:
        j = int(np.argmin(np.abs(ft - t))); k = side['frames'][j]['source_frame']
        if k in ks: continue
        raw = subprocess.run(['ffmpeg', '-v', 'error', '-ss', f'{ft[j]:.3f}', '-i', proxy_path, '-frames:v', '1', '-pix_fmt', 'rgb24', '-f', 'rawvideo', '-'], stdout=subprocess.PIPE, check=True).stdout
        if len(raw) < W * H * 3: continue
        eq = np.frombuffer(raw, np.uint8).reshape(H, W, 3); h = heading[min(k, len(heading) - 1)]
        for y in yaws:
            img = _equirect_view(eq, stab_view_rays(y, h, px, fov), px, px); cv2.imwrite(f'{out_dir}/s{k:05d}_v{y:03d}.jpg', img[:, :, ::-1], [cv2.IMWRITE_JPEG_QUALITY, quality])
        ks.append(int(k))
    return ks


def render_thumb_proxy(proxy_path, osv, t, yaw=0.0, pitch=0.0, hfov=100.0, w=960, h=540, quality=90, heading=None):
    """A flat, upright 16:9 view at clip time `t` cut from the proxy; JPEG bytes. Same conventions as render_thumb (yaw from the runner's heading, 0 = ahead, 180 = behind)."""
    side = json.load(open(os.path.splitext(proxy_path)[0] + '.json')); W, H = side['size']; times = np.array([f['t_s'] for f in side['frames']]); j = int(np.argmin(np.abs(times - t)))
    raw = subprocess.run(['ffmpeg', '-v', 'error', '-ss', f'{times[j]:.3f}', '-i', proxy_path, '-frames:v', '1', '-pix_fmt', 'rgb24', '-f', 'rawvideo', '-'], stdout=subprocess.PIPE, check=True).stdout
    eq = np.frombuffer(raw, np.uint8).reshape(H, W, 3)
    if heading is None: heading, _ = heading_track(osv)
    k = side['frames'][j]['source_frame']; hd = heading[min(k, len(heading) - 1)]
    img = _equirect_view(eq, _rect_rays(yaw, hd, w, h, hfov, pitch), w, h); ok, buf = cv2.imencode('.jpg', img[:, :, ::-1], [cv2.IMWRITE_JPEG_QUALITY, quality]); return buf.tobytes()


def _sources_fresh(cache, clip_dir):
    src = [os.path.join(clip_dir, n) for n in ('identity.json', 'speakers.json')]
    return os.path.exists(cache) and all(not os.path.exists(p) or os.path.getmtime(p) <= os.path.getmtime(cache) for p in src)


def heading_fn(clip_dir, osv=None):
    """Function t (clip seconds) -> smoothed heading in degrees (upright world frame), from motion.json (5 Hz, cheap); the telemetry is read only when motion.json is missing."""
    mp = os.path.join(clip_dir, 'motion.json')
    try:
        s = json.load(open(mp))['series']; ts = np.array(s['t'], float); hd = np.degrees(np.unwrap(np.radians(s['heading_deg'])))
        return lambda t: float(np.interp(t, ts, hd))
    except (OSError, ValueError, KeyError):
        h, fps = heading_track(osv); return lambda t: float(np.degrees(h[min(int(round(t * fps)), len(h) - 1)]))


def _speaker_at(segs, t):
    for s in segs:
        if s['t0'] - 0.2 <= t <= s['t1'] + 0.2 and s.get('label'): return s['label']
    return None


_STAB = {}


def stab_fn(osv):
    """clip time (seconds from the first frame) -> the 3x3 matrix that turns a direction of the upright world frame into the camera's body frame at that frame (`d_body = M d_E`, as StabViews uses), from the camera's orientation of every frame (50 Hz). Cached per file; None when the file cannot be read."""
    if osv in _STAB: return _STAB[osv]
    try:
        from strata360.osv.calib import quat_to_R, imu_offsets
        from strata360.osv.telemetry import read_frames, video_pts
        P, B = imu_offsets(); T = read_frames(osv); Ms = np.array([B.T @ quat_to_R(q).T @ P.T for q in T['quat']]); pts = np.asarray(video_pts(osv, 0), float); pts = pts - pts[0]
        def M(t): return Ms[int(np.clip(np.searchsorted(pts, float(t) - 1e-4), 0, min(len(Ms), len(pts)) - 1))]
    except Exception: M = None
    _STAB[osv] = M; return M


def face_offsets(me):
    """(pitch above the person's box centre, yaw beside it), in degrees, of the CENTRE OF THE FACE (the middle of the detected head, between the eyes and the nose) for one identity sample; (None, None) when the face box or the person box is missing. The person box [x0, y0, x1, y1] is `height_deg` tall, which
    gives the degrees per pixel of the detector's view; the face box sits inside it."""
    box, fb, hgt = me.get('box'), me.get('face_box'), me.get('height_deg')
    if not box or not fb or not hgt or box[3] - box[1] <= 1: return None, None
    dpp = float(hgt) / (box[3] - box[1]); up = ((box[1] + box[3]) - (fb[1] + fb[3])) / 2.0 * dpp; side = ((fb[0] + fb[2]) - (box[0] + box[2])) / 2.0 * dpp
    return round(up, 2), round(side / max(math.cos(math.radians(float(me.get('pitch') or 0.0))), 0.3), 2)


def focus_samples(clip_dir, osv):
    """Where YOU (the wearer) are, once a second, for the player's "You" mode (cached in focus.json; derived from identity.json and speakers.json, nothing is recomputed).
    Each sample: t, world yaw and pitch in degrees (the direction in the upright world frame the preview is in), who ('you') and whether you are speaking. Only seconds where your face was found."""
    cache = os.path.join(clip_dir, 'focus.json')
    if _sources_fresh(cache, clip_dir):
        try:
            d = json.load(open(cache))
            if d.get('schema') == 6: return d['samples']
        except ValueError: pass
    idp = os.path.join(clip_dir, 'identity.json')
    if not os.path.exists(idp): return []
    idn = json.load(open(idp)); sp = os.path.join(clip_dir, 'speakers.json'); segs = json.load(open(sp))['segments'] if os.path.exists(sp) else []
    hdf = heading_fn(clip_dir, osv); out = []
    for r in idn['samples']:
        me = r.get('me')
        if not me: continue
        t = r['t_s']; hd = hdf(t); face, fdy = face_offsets(me)
        out.append(dict(t=t, yaw=round((hd + me['yaw']) % 360.0, 1), pitch=round(me['pitch'], 1), height=me.get('height_deg'), head=None if me.get('head_up') is None else round(me['pitch'] + me['head_up'], 1), face=None if face is None else round(me['pitch'] + face, 1), face_dyaw=fdy, who='you', speaking=_speaker_at(segs, t) == 'wearer'))
    tmp = cache + f'.{os.getpid()}.tmp'; json.dump(dict(schema=6, samples=out), open(tmp, 'w')); os.replace(tmp, cache); return out


def person_samples(clip_dir, osv):
    """Another person to show, once a second, for the player's "Person" mode (cached in person.json): never you, somebody whenever anybody is in view, the same person for as long as possible
    (analysis/follow.py). Each sample: t, world yaw, pitch, who ('other'), speaking (another voice is talking), person (a running number: it changes when the view has to jump to someone else)."""
    from strata360.analysis import follow
    cache = os.path.join(clip_dir, 'person.json')
    if _sources_fresh(cache, clip_dir):
        try:
            d = json.load(open(cache))
            if d.get('schema') == 4 and d.get('follow') == [follow.SWITCH, follow.TOL_DEG, follow.TOL_PER_S]: return d['samples']
        except ValueError: pass
    idp = os.path.join(clip_dir, 'identity.json')
    if not os.path.exists(idp): return []
    idn = json.load(open(idp)); sp = os.path.join(clip_dir, 'speakers.json'); segs = json.load(open(sp))['segments'] if os.path.exists(sp) else []
    hdf = heading_fn(clip_dir, osv); frames = []; last_me = None
    for r in idn['samples']:
        t = r['t_s']; hd = hdf(t); me = r.get('me')
        if me: last_me = (t, me['yaw'])
        c = []
        for o in r.get('others', []):
            if not o.get('height_deg'): continue
            near_me = (me and follow._dyaw(o['yaw'], me['yaw']) < 20 and abs(o['pitch'] - me['pitch']) < 25) or (not me and last_me and t - last_me[0] < 6 and follow._dyaw(o['yaw'], last_me[1]) < 20)   # the wearer seen as "someone else"
            if not near_me: c.append(dict(yaw=(hd + o['yaw']) % 360.0, pitch=o['pitch'], height_deg=o['height_deg'], head_up=o.get('head_up'), face=bool(o.get('face'))))
        frames.append(dict(t=t, cands=c))
    ch = follow.choose(frames); out = []
    for f, (j, pid) in zip(frames, ch):
        if j is None: continue
        c = f['cands'][j]; out.append(dict(t=f['t'], yaw=round(c['yaw'], 1), pitch=round(c['pitch'], 1), height=c.get('height_deg'), head=None if c.get('head_up') is None else round(c['pitch'] + c['head_up'], 1), who='other', speaking=_speaker_at(segs, f['t']) == 'other', person=pid))
    tmp = cache + f'.{os.getpid()}.tmp'; json.dump(dict(schema=4, follow=[follow.SWITCH, follow.TOL_DEG, follow.TOL_PER_S], samples=out), open(tmp, 'w')); os.replace(tmp, cache); return out
