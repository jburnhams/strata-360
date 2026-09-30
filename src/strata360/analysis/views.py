"""Body-frame rectilinear analysis views for the detectors (people, faces, later scenes).

Six 100-degree views around the camera's horizon (body frame: +Y is the front lens, -Y the rear lens, +Z up along the stick), each cut straight from
the fisheye frames with maps computed once per clip, so a sample costs a decode plus six remaps. They are NOT stabilised: detectors do not need it, and
keeping them body-fixed means the wearer (on the selfie stick) is always in the same view. Views are numbered by the yaw of their centre from the front
lens: 0 front, 60, 120, 180 = straight at the wearer (rear lens), 240, 300."""
import os, subprocess, numpy as np, cv2
from strata360.osv.calib import read_slots, Lens

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
    cmd = ['ffmpeg', '-v', 'error', '-hwaccel', 'videotoolbox', '-i', osv, '-map', f'0:v:{stream}', '-fps_mode', 'passthrough',
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


def write_stab_views(osv, out_dir, every=25, first=None, quality=93, yaws=STAB_YAWS, px=VIEW_PX):
    """Like write_views but upright and heading-relative; files s{frame}_v{yaw}.jpg (yaw from the heading)."""
    os.makedirs(out_dir, exist_ok=True); V = StabViews(osv, yaws=yaws, px=px); ks = []
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
