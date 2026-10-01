"""Direct dual-fisheye -> flat 4K renderer (spike).

One resample per output pixel: build the view ray for every output pixel, rotate it into the camera body
frame (stabilisation from the telemetry quaternion), project through the two factory-calibrated KB5 lenses,
sample, and blend across the seam. No equirect intermediate.

Maps are evaluated on a coarse grid (1/8 resolution) and upsampled, which is accurate because the mapping is smooth.

Camera: static (--mode world|heading|body with --yaw/--pitch/--roll/--fov) or a keyframed path (--path file.json, spike/camera.py).
  world    fixed in the upright stabilised world frame
  heading  world frame + the runner's smoothed heading (heading-follow stabilisation: level horizon, gentle yaw)
  body     fixed in the camera body frame (yaw 180 = the user on a selfie stick), horizon still levelled
Segments: --start S --end E (clip-relative seconds). Audio is muxed from the OSV (--audio copy|aac|none).

Usage:
  python render4k.py CAM.OSV out.mp4 --mode heading --fov 90 [--path path.json] [--start 1.0 --end 3.0] [--frames N] [--interp cubic|linear|lanczos]
"""
import argparse, os, subprocess, sys, time
import numpy as np, cv2
from strata360.pipeline import guard
from strata360.osv.calib import read_slots, Lens, quat_to_R, imu_offsets
from strata360.osv.telemetry import read_frames, video_pts
from strata360.render import photo as ph
from strata360.render import camera as cam
from strata360 import hw as hwmod

LS = 3840  # lens frame size
BYTES = 6  # rgb48le: 16-bit code values (10-bit source, range-expanded)


def unit(v):
    return v / np.linalg.norm(v, axis=-1, keepdims=True)


def view_basis(fwd_b, up_b, roll=0.0):
    """Right-handed X right, Y forward, Z up basis, in the body frame; roll levelled to the given up, then rolled by `roll`
    radians (positive = clockwise as seen from the camera: the up vector tilts to the right)."""
    f = fwd_b / np.linalg.norm(fwd_b)
    r = np.cross(f, up_b)
    if np.linalg.norm(r) < 1e-6:  # looking straight up/down: pick any right vector
        r = np.cross(f, np.array([1.0, 0, 0]) if abs(f[0]) < 0.9 else np.array([0, 1.0, 0]))
    r /= np.linalg.norm(r)
    u = np.cross(r, f)
    if roll:
        c, sn = np.cos(roll), np.sin(roll); r, u = r * c - u * sn, u * c + r * sn
    return r, f, u


def projection(xn, yn, hfov, dist=0.0, disc=None):
    """Angle from the view axis (theta) and the direction in the image plane (cos/sin phi) for every pixel of a normalised grid (xn: -1..1 across the width, yn the same scale, up positive).
    Shared by the real renderer and the film preview, so both project exactly the same way. `disc` (radius in half-widths) selects the globe: azimuthal equidistant, the whole sphere in a disc;
    otherwise rectilinear to stereographic by `dist` (see Renderer.set_fov)."""
    rn = np.hypot(xn, yn)
    with np.errstate(invalid='ignore', divide='ignore'):
        cphi = np.where(rn > 0, xn / np.maximum(rn, 1e-12), 1.0); sphi = np.where(rn > 0, yn / np.maximum(rn, 1e-12), 0.0)
    if disc is not None: return np.pi * np.minimum(rn / disc, 1.0), cphi, sphi
    d = float(np.clip(dist, 0.0, 1.0))
    hmax = 2 * np.degrees(np.arccos(-d)) - 1.0 if d > 0 else 179.0
    half = np.radians(min(hfov, hmax)) / 2
    k_edge = np.sin(half) / (d + np.cos(half))                       # k = r / (f (1+d)) at the horizontal edge of the frame
    k = rn * k_edge
    return np.arctan(k) + np.arcsin(np.clip(k * d / np.sqrt(1 + k * k), -1, 1)), cphi, sphi


def view_rays(theta, cphi, sphi, fwd, up, roll=0.0):
    """Unit view rays (N, 3) for projection() output and a view direction `fwd` with its `up` (any frame), rolled by `roll`."""
    r, f, u = view_basis(fwd, up, roll)
    ct, st = np.cos(theta)[..., None], np.sin(theta)[..., None]
    return unit(ct * f + st * (cphi[..., None] * r + sphi[..., None] * u)).reshape(-1, 3)


class Globe:
    """The globe look shared by every renderer that has a `disc`: the sphere inside a disc, and what fills the rest of the frame (a blurred copy of the little planet, a solid colour, or colours
    taken from the globe's own rim). Needs W, H, disc, and `_small_planet(src, fwd, up, roll)` (a small 260-degree planet picture, uint16 code values) from the subclass. Pictures are uint16."""
    def init_globe(self):
        self.bg_spread = 1.5; self.bg_pick = 'vivid'; self.bg_inset = 6.0; self.bg_band = 40.0; self.bg_smooth = 8.0; self.disc = None; self.bg = [0.03, 0.03, 0.05]; self._rr = None; self._bgR = None; self._bgcol = None

    def set_background(self, bg, band=None, spread=None, smooth=None, pick=None, inset=None):
        """Globe background: [r, g, b] in 0..1 (BT.709 code values) or 'blur' (a blurred, darkened copy of the fill planet)."""
        self.bg = bg
        if band is not None: self.bg_band = float(band)
        if spread is not None: self.bg_spread = float(spread)
        if smooth is not None: self.bg_smooth = float(smooth)
        if pick is not None: self.bg_pick = str(pick)
        if inset is not None: self.bg_inset = float(inset)

    def _radius_grid(self):
        if self._rr is None or self._rr.shape != (self.H, self.W):
            x = ((np.arange(self.W) + 0.5) - self.W / 2) / (self.W / 2); y = (self.H / 2 - (np.arange(self.H) + 0.5)) / (self.W / 2)
            self._rr = np.hypot(x[None, :], y[:, None]).astype(np.float32)
        return self._rr

    def _background(self, src, fwd_b, up_b, roll):
        H, W = self.H, self.W
        if isinstance(self.bg, str) and self.bg == 'blur':
            small = self._small_planet(src, fwd_b, up_b, roll)
            small = cv2.GaussianBlur(small, (0, 0), 5.0)
            big = cv2.resize(small, (W, H), interpolation=cv2.INTER_LINEAR)
            return (big.astype(np.float32) * 0.55).astype(np.uint16)
        col = tuple(self.bg)
        if self._bgcol is None or self._bgcol[0] != (col, W, H):
            self._bgcol = ((col, W, H), np.broadcast_to((np.array(col) * 65535).astype(np.uint16), (H, W, 3)).copy())
        return self._bgcol[1]

    def _rim_background(self, out, rr):
        """Background from the globe's own rim: 'rim' = the average rim colour (solid); 'gradient' = each rim colour is spread outwards along its own direction
        and merges into the average with distance, so blue below / green above blend smoothly from the ball."""
        H, W = self.H, self.W; n = int(np.clip(2 * np.pi * self.disc * W / 2, 720, 4096))              # about one sample per rim pixel
        a = np.linspace(0, 2 * np.pi, n, endpoint=False); rim = self.disc * (W / 2)
        band = max(self.bg_band, 1.0); radii = rim - self.bg_inset - np.linspace(0, band - 1.0, max(int(round(band)), 1))     # `bg_band` pixels starting `bg_inset` inside the rim (skips the dark lens-edge hairline)
        acc = np.zeros((n, 3)); wsum = np.zeros((n, 1))
        for r0 in radii:
            xs = np.clip(W / 2 + r0 * np.cos(a), 0, W - 1).astype(int); ys = np.clip(H / 2 - r0 * np.sin(a), 0, H - 1).astype(int); c = out[ys, xs].astype(np.float64) / 65535.0
            if self.bg_pick == 'vivid':                                                     # favour the strongest colour: saturated and bright samples count more (a red-orange edge beats grey-brown)
                w = ((c.max(1) - c.min(1)) * (0.25 + c.max(1)))[:, None] ** 2 + 1e-4
            else: w = np.ones((n, 1))
            acc += c * w * 65535.0; wsum += w
        ring = acc / wsum
        mean = ring.mean(0) if self.bg_pick != 'vivid' else (ring * (((ring.max(1) - ring.min(1)) * (0.25 + ring.max(1) / 65535.0) / 65535.0)[:, None] ** 2 + 1e-4)).sum(0) / (((ring.max(1) - ring.min(1)) * (0.25 + ring.max(1) / 65535.0) / 65535.0) ** 2 + 1e-4).sum()
        if self.bg == 'rim': return np.broadcast_to(mean.astype(np.uint16), (H, W, 3)).copy()
        def smooth(r, deg):
            k = max(int(round(n * deg / 360.0)), 1)
            if k <= 1: return r
            ext = np.concatenate([r[-k:], r, r[:k]]); return np.stack([np.convolve(ext[:, c], np.ones(k) / k, 'same')[k:-k] for c in range(3)], 1)
        sharp, soft = smooth(ring, self.bg_smooth), smooth(ring, max(self.bg_smooth * 6, 12.0))          # the rim colours as they are, and a much softer version of them
        x = ((np.arange(W) + 0.5) - W / 2); y = (H / 2 - (np.arange(H) + 0.5))
        ang = (np.arctan2(y[:, None], x[None, :]) % (2 * np.pi)) / (2 * np.pi) * n; i0 = ang.astype(int) % n; f = (ang - np.floor(ang))[..., None]
        lerp = lambda r: r[i0] * (1 - f) + r[(i0 + 1) % n] * f
        t = np.clip((rr - self.disc) / max(self.bg_spread, 1e-3), 0, 1)[..., None]; t = t * t * (3 - 2 * t)
        t2 = np.clip(t * 2.0, 0, 1)                                                                     # by halfway the streaks are already softened; then it merges into the average
        col = lerp(sharp) * (1 - t2) + lerp(soft) * t2
        return (col * (1 - t) + mean * t).astype(np.uint16)

    def _apply_globe(self, out, src, fwd_b, up_b, roll):
        rr = self._radius_grid()
        alpha = np.clip((self.disc - rr) * (self.W / 2) + 0.5, 0.0, 1.0)         # distance to the rim in pixels, anti-aliased over one pixel
        if alpha.min() >= 1.0: return out
        bg = self._rim_background(out, rr) if isinstance(self.bg, str) and self.bg in ('rim', 'gradient') else self._background(src, fwd_b, up_b, roll)
        out = out.copy(); cv2.copyTo(bg, (alpha <= 0).view(np.uint8), out)          # fully outside: the background
        idx = np.flatnonzero((alpha > 0) & (alpha < 1))                              # the one-pixel rim: blend
        if idx.size:
            a = alpha.reshape(-1)[idx][:, None]; o = out.reshape(-1, 3)[idx].astype(np.float32); b = bg.reshape(-1, 3)[idx].astype(np.float32)
            out.reshape(-1, 3)[idx] = (a * o + (1 - a) * b).astype(np.uint16)
        return out



class Renderer(Globe):
    def __init__(self, osv, W=3840, H=2160, hfov=90.0, interp='cubic', grid=8):
        self.W, self.H, self.grid = W, H, grid
        sl = read_slots(osv)
        self.master, self.slave = Lens(sl[2]), Lens(sl[1])  # stream 1 = master (front), stream 0 = slave (rear)
        self.occl_m = ph.occlusion_map(sl[2]['poly_x'], sl[2]['poly_y'], centre=(self.master.cx, self.master.cy), rim=self.master.rim_radius(ph.THETA_MAX_DEG)); self.occl_s = ph.occlusion_map(sl[1]['poly_x'], sl[1]['poly_y'], centre=(self.slave.cx, self.slave.cy), rim=self.slave.rim_radius(ph.THETA_MAX_DEG))
        self.rtm = ph.THETA_MAX_DEG - ph.RENDER_INSET_DEG          # render-only blend inset (PhotoSeam.h), 94.99 deg
        self.gain_m = np.ones(3); self.gain_s = np.ones(3); self._lut = None
        self.osv = osv; self.init_globe(); self.seam = None; self.warp = None; self._carver = None; self.carve_seam = False; self.parallax = False                  # carve_seam: measure a seam from the lens frames before each render (update_seam)
        P, B = imu_offsets()
        self.P, self.B = P, B
        self.interp = {'cubic': cv2.INTER_CUBIC, 'linear': cv2.INTER_LINEAR, 'lanczos': cv2.INTER_LANCZOS4}[interp]
        # coarse pixel grid (output pixel centres), with the last row/col reaching the image edge
        gw, gh = W // grid + 1, H // grid + 1
        xs = np.linspace(0, W, gw); ys = np.linspace(0, H, gh)
        X, Y = np.meshgrid(xs, ys)
        self.xn = ((X - W / 2) / (W / 2)).astype(np.float64)    # normalised: -1..1 across the width
        self.yn = ((H / 2 - Y) / (W / 2)).astype(np.float64)    # same scale, so pixels stay square
        self.gw, self.gh = gw, gh
        self.set_fov(hfov)

    def set_fov(self, hfov, dist=0.0, disc=None):
        """Horizontal field of view in degrees and projection `dist` (0 to 1); both can change every frame.

        dist = 0 is the ordinary rectilinear (pinhole) view. Larger values bend the projection toward stereographic (dist = 1), the
        'eye-offset' family used by OpenOSV: r/f = (1+d) sin(theta) / (d + cos(theta)). With dist = 1 the field of view can reach 360 degrees;
        pointed straight down with about 250-300 degrees it is the 'little planet', pointed straight up the 'tunnel'. The field of view is
        limited to just under 2*acos(-d) so the mapping stays invertible. Animating (fov, dist) from (250, 1) to (90, 0) is the classic
        little-planet zoom-in."""
        self.disc = None if disc is None else float(disc)
        self.theta, self.cphi, self.sphi = projection(self.xn, self.yn, hfov, dist, self.disc)

    def stab_matrix(self, q):
        """body <- upright-world direction matrix: d_body = M d_E (stored quaternion fields = w,x,y,z)."""
        return self.B.T @ quat_to_R(np.asarray(q)).T @ self.P.T

    def maps(self, fwd_b, up_b, roll=0.0):
        d = view_rays(self.theta, self.cphi, self.sphi, fwd_b, up_b, roll); self._dirs = d                  # body-frame rays (the seam is read per ray)
        out = []
        for L, sign in ((self.master, 1), (self.slave, -1)):
            uu, vv, th = L.project(d if self.warp is None else self.warp.apply(d, sign))            # a parallax warp moves each lens's sampling direction by half the disparity, in opposite ways
            out.append((uu.reshape(self.gh, self.gw), vv.reshape(self.gh, self.gw), np.degrees(th).reshape(self.gh, self.gw)))
        return out

    def update_seam(self, L_master, L_slave, reset=False):
        """Carve the seam for this frame (the previous one steadies it: `reset` forgets it, after a jump in time). A no-op unless carve_seam is on."""
        if not (self.carve_seam or self.parallax): return
        from strata360.render import seam as SM, parallax as PX
        if self._carver is None: self._carver = SM.SeamCarver(self.master, self.slave, self.occl_m, self.occl_s)
        if self.parallax:                                                                                    # 1. measure how far the lenses disagree and move them toward each other where that helps
            (A, cA), (B, cB) = self._carver.band(L_master, L_slave); self.warp = PX.measure(A, B, cA, cB, None if (reset or self.warp is None) else self.warp)
        else: self.warp = None
        if self.carve_seam: self.seam = self._carver.carve(L_master, L_slave, None if (reset or self.seam is None) else self.seam, self.warp)     # 2. the seam is carved through the corrected bands

    def set_gains(self, g_master, g_slave):
        self.gain_m, self.gain_s = np.asarray(g_master, float), np.asarray(g_slave, float)
        self._lut = None if (np.allclose(self.gain_m, 1) and np.allclose(self.gain_s, 1)) else (ph.gain_lut(self.gain_m), ph.gain_lut(self.gain_s))

    def render(self, L_master, L_slave, fwd_b, up_b, roll=0.0):
        """Scene render; when a globe is active (`disc`), the area outside the disc is filled with the background (solid colour or blurred fill planet)."""
        out = self._render_scene(L_master, L_slave, fwd_b, up_b, roll)
        return out if self.disc is None else self._apply_globe(out, (L_master, L_slave), fwd_b, up_b, roll)

    def _small_planet(self, src, fwd_b, up_b, roll):
        if self._bgR is None or self._bgR.W != self.W // 8:
            self._bgR = Renderer(self.osv, self.W // 8, self.H // 8, 260.0, 'linear', grid=4); self._bgR.set_fov(260.0, 1.0)
        return self._bgR._render_scene(src[0], src[1], fwd_b, up_b, roll)

    def _render_scene(self, L_master, L_slave, fwd_b, up_b, roll=0.0):
        """L_* are (3840,3840,3) uint16 code values. Blend in linear light with OpenOSV's lens weights (FOV feather x occlusion)."""
        (um, vm, tm), (us, vs, ts) = self.maps(fwd_b, up_b, roll)
        W, H = self.W, self.H
        up = lambda a: cv2.resize(np.ascontiguousarray(a, dtype=np.float32), (W, H), interpolation=cv2.INTER_LINEAR)
        oc_m = ph.sample_occl(self.occl_m, um, vm); oc_s = ph.sample_occl(self.occl_s, us, vs)
        wm = ph.lens_weight(tm, oc_m, self.rtm, ph.RENDER_FEATHER_DEG); ws = ph.lens_weight(ts, oc_s, self.rtm, ph.RENDER_FEATHER_DEG)
        if self.seam is not None:                                                                         # a carved seam decides the mix: one lens on each side, a narrow feather between them
            from strata360.render import seam as SM
            t = self.seam.master_share(self._dirs).reshape(tm.shape); vis_m = ph.lens_weight(tm, oc_m, self.rtm, SM.EDGE_RAMP_DEG); vis_s = ph.lens_weight(ts, oc_s, self.rtm, SM.EDGE_RAMP_DEG)
            wm, ws = t * vis_m, (1.0 - t) * vis_s; dead = (wm + ws) < 1e-3; wm = np.where(dead, vis_m, wm); ws = np.where(dead, vis_s, ws)          # where the chosen lens cannot see, the other fills in
        wm, ws = ph.rescue(wm, ws, tm, ts, oc_m, oc_s, ph.THETA_MAX_DEG)   # as OpenOSV: the rescue works inside the full lens limit, not the render inset
        wsum = wm + ws
        cover = wsum > 1e-4
        wn = np.where(cover, wm / np.maximum(wsum, 1e-9), 0.0).astype(np.float32)
        lutm, luts = self._lut if self._lut else (None, None)
        def single(img, um_, vm_, lut):
            out = cv2.remap(img, up(um_), up(vm_), self.interp, borderMode=cv2.BORDER_CONSTANT)
            return out if lut is None else np.stack([lut[c][out[..., c]] for c in range(3)], -1)
        if cover.all() and wn.min() > 0.9995:
            return single(L_master, um, vm, lutm)
        if cover.all() and wn.max() < 0.0005:
            return single(L_slave, us, vs, luts)
        a = cv2.remap(L_master, up(um), up(vm), self.interp, borderMode=cv2.BORDER_CONSTANT)
        b = cv2.remap(L_slave, up(us), up(vs), self.interp, borderMode=cv2.BORDER_CONSTANT)
        wnf = up(wn); covf = up(cover.astype(np.float32)) > 0.5
        m_only = (wnf >= 0.9995) & covf; s_only = (wnf <= 0.0005) & covf; band = (wnf > 0.0005) & (wnf < 0.9995) & covf
        if lutm is not None:   # exposure-match gain on single-lens pixels: a code -> code table per channel
            a = np.stack([lutm[c][a[..., c]] for c in range(3)], -1); b = np.stack([luts[c][b[..., c]] for c in range(3)], -1)
        out = a.copy()                                            # master everywhere ...
        cv2.copyTo(b, s_only.view(np.uint8), out)                 # ... slave where only the slave sees (fast masked copy)
        cv2.copyTo(np.zeros_like(a), (~covf).view(np.uint8), out) # uncovered: black
        idx = np.flatnonzero(band)                                # seam band: blend in linear light (integer-index gathers)
        if idx.size:
            af = a.reshape(-1, 3)[idx]; bf = b.reshape(-1, 3)[idx]; w = wnf.reshape(-1)[idx][:, None]
            gm = 1.0 if lutm is not None else self.gain_m       # gains already folded into a, b when LUTs are active
            gs = 1.0 if lutm is not None else self.gain_s
            lin = w * (gm * ph.EOTF_LUT[af]) + (1 - w) * (gs * ph.EOTF_LUT[bf])
            out.reshape(-1, 3)[idx] = ph.linear_to_code16(lin)
        return out


def decoder(osv, stream, hw=True, ss=0.0):
    cmd = ['ffmpeg', '-v', 'error'] + (hwmod.hwaccel_args() if hw else []) + (['-ss', f'{ss:.4f}'] if ss > 0 else []) + \
          ['-i', osv, '-map', f'0:v:{stream}', '-fps_mode', 'passthrough', '-pix_fmt', 'rgb48le', '-f', 'rawvideo', '-']
    return guard.popen(cmd, stdout=subprocess.PIPE, bufsize=LS * LS * BYTES * 2)


def read_frame(p):
    n = LS * LS * BYTES; buf = p.stdout.read(n)
    if len(buf) < n: return None
    return np.frombuffer(buf, np.uint16).reshape(LS, LS, 3)


def mux_audio(video, osv, out, start, dur, mode, whole_clip, meta=()):
    """Add the OSV's audio to the rendered video. `start`/`dur` are clip-relative seconds of the rendered range."""
    if mode == 'none':
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', video, '-c', 'copy', *meta, out], check=True); return
    if mode == 'copy' and whole_clip:      # bit-exact audio when the whole clip is rendered
        cmd = ['ffmpeg', '-v', 'error', '-y', '-i', video, '-i', osv, '-map', '0:v', '-map', '1:a:0', '-c', 'copy', '-shortest', *meta, out]
    else:                                  # a sub-range needs an accurate cut, which means re-encoding (AAC, high rate)
        cmd = ['ffmpeg', '-v', 'error', '-y', '-i', video, '-ss', f'{start:.4f}', '-t', f'{dur:.4f}', '-i', osv, '-map', '0:v', '-map', '1:a:0',
               '-c:v', 'copy', '-c:a', 'aac', '-b:a', '256k', '-shortest', *meta, out]
    subprocess.run(cmd, check=True)


def utc_metadata(start_utc, t_first, duration, a):
    """creation_time for the overlay tool plus the exact value. MP4 creation_time has whole-second resolution, so it is rounded to the nearest second and the exact UTC
    of the first frame is also stored in the `comment` tag (`strata360 start_utc=...`) and in `<out>.utc.json` (the authoritative record)."""
    import datetime as dt, json
    t0 = dt.datetime.fromisoformat(start_utc.replace('Z', '+00:00')).astimezone(dt.timezone.utc) + dt.timedelta(seconds=float(t_first))
    exact = t0.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'; rounded = (t0 + dt.timedelta(seconds=0.5)).strftime('%Y-%m-%dT%H:%M:%SZ')
    json.dump(dict(source=os.path.basename(a.osv), start_utc=exact, duration_s=round(float(duration), 4), fps=a.fps, clip_start_utc=start_utc, src_in_s=round(float(t_first), 4)),
              open(a.out + '.utc.json', 'w'), indent=1)
    return ['-map_metadata', '-1', '-metadata', f'creation_time={rounded}', '-metadata', f'comment=strata360 start_utc={exact}']


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('osv'); ap.add_argument('out')
    ap.add_argument('--mode', choices=['body', 'world', 'heading'], default='body')
    ap.add_argument('--fov', type=float, default=90); ap.add_argument('--pitch', type=float, default=0); ap.add_argument('--yaw', type=float, default=None)
    ap.add_argument('--roll', type=float, default=0.0)
    ap.add_argument('--target', choices=['user', 'front'], default='user', help='body mode default yaw: user = 180 (rear lens), front = 0')
    ap.add_argument('--path', help='keyframed camera path (JSON, see spike/camera.py); overrides --mode/--yaw/--pitch/--roll/--fov')
    ap.add_argument('--heading-tau', type=float, default=2.0, help='heading smoothing (seconds, Gaussian sigma)')
    ap.add_argument('--heading-axis', default='0,1,0', help='body axis whose horizontal direction defines the heading (default the front lens)')
    ap.add_argument('--start', type=float, default=None); ap.add_argument('--end', type=float, default=None)
    ap.add_argument('--audio', choices=['copy', 'aac', 'none'], default='copy')
    ap.add_argument('--frames', type=int, default=0); ap.add_argument('--interp', default='cubic')
    ap.add_argument('--parallax', choices=['on', 'off'], default='on', help='move each lens toward the other by half the measured disparity where that makes them agree (far-field only: near objects are left to the seam)')
    ap.add_argument('--seam', choices=['on', 'off'], default='on', help='carve the seam between the lenses where they agree (hands and other near objects no longer ghost); off = the plain feathered blend')
    ap.add_argument('--gain', choices=['off', 'auto'], default='off', help='OpenOSV exposure match between lenses (unreliable on wet-lens / near-object clips, so off by default)')
    ap.add_argument('--size', default='3840x2160')
    ap.add_argument('--bitrate', default='200M', help='quality first: the overlay tool re-encodes this (README 8.10); 350M for archive')
    ap.add_argument('--fps', type=float, default=50.0)
    ap.add_argument('--start-utc', help='definitive UTC of the START of the source clip (clip.json time.start_utc, ISO 8601): the output gets creation_time and a sidecar with the true UTC of its first frame (README 8, GPX handoff)')
    a = ap.parse_args()
    W, H = map(int, a.size.split('x'))
    T = read_frames(a.osv); pts = video_pts(a.osv, 0); n_src = len(pts); t_rel = pts - pts[0]
    # --- range of source frames to render
    k0 = 0 if a.start is None else int(np.searchsorted(t_rel, a.start - 1e-6))
    k1 = n_src - 1 if a.end is None else int(np.searchsorted(t_rel, a.end + 1e-6, side='right') - 1)
    dt = 1.0 / a.fps
    n_out = int(round((pts[k1] - pts[k0]) / dt)) + 1
    if a.frames: n_out = min(n_out, a.frames)
    whole = (k0 == 0 and k1 == n_src - 1 and not a.frames)
    slot_t = pts[k0] + np.arange(n_out) * dt                                    # absolute pts of every output slot
    slot_k = np.array([max(int(np.searchsorted(pts, t + dt * 0.5, side='right') - 1), k0) for t in slot_t])   # newest source frame at or before the slot
    R = Renderer(a.osv, W, H, a.fov, a.interp); R.carve_seam = a.seam == 'on'; R.parallax = a.parallax == 'on'
    # --- camera path over all slots (heading-follow needs the whole sequence to smooth)
    Ms = [R.stab_matrix(T['quat'][k]) for k in slot_k]
    if a.path:
        path = cam.CameraPath.from_json(a.path)
    else:
        yaw = a.yaw if a.yaw is not None else (180.0 if (a.mode == 'body' and a.target == 'user') else 0.0)
        path = cam.CameraPath.static(a.mode, yaw, a.pitch, a.roll, a.fov, heading=dict(axis_body=[float(v) for v in a.heading_axis.split(',')], tau_s=a.heading_tau))
    P = path.evaluate(slot_t - pts[0], Ms, a.fps); R.set_background(path.bg, **path.bg_opts)
    rep = cam.limits_report(P, a.fps)
    print('camera:', path.ref, ' path limits', {k: round(v, 1) for k, v in rep.items()}, flush=True)
    for w in cam.path_warnings(rep): print('WARNING:', w, flush=True)
    video_tmp = a.out + '.video.mp4'
    dm, ds = decoder(a.osv, 1, ss=max(pts[k0] - 0.002, 0)), decoder(a.osv, 0, ss=max(pts[k0] - 0.002, 0))   # master = stream 1, slave = stream 0
    enc = guard.popen(['ffmpeg', '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgb48le', '-s', f'{W}x{H}', '-r', str(a.fps), '-i', '-',
                            '-vf', 'scale=in_range=full:out_range=tv:out_color_matrix=bt709:flags=accurate_rnd+full_chroma_int',   # RGB code values -> BT.709 limited-range YCbCr
                            *hwmod.hevc_args(a.bitrate, main10=True),
                            '-bsf:v', 'hevc_metadata=colour_primaries=1:transfer_characteristics=1:matrix_coefficients=1:video_full_range_flag=0',   # write BT.709 into the VUI
                            '-colorspace', 'bt709', '-color_primaries', 'bt709', '-color_trc', 'bt709', '-color_range', 'tv', video_tmp],
                           stdin=subprocess.PIPE)
    tm = dict(read=0, remap=0, write=0)
    t_all = time.time(); k_dec = k0 - 1; last = None; last_k = -1
    for i in range(n_out):
        k = slot_k[i]
        if k != last_k or last is None:
            while k_dec < k:                                                     # decode forward (frames the slots skip are discarded)
                t0 = time.time(); cur_m = read_frame(dm); cur_s = read_frame(ds); tm['read'] += time.time() - t0
                if cur_m is None or cur_s is None: break
                k_dec += 1
            if cur_m is None or cur_s is None: break
            if a.gain == 'auto' and k % ph.GAIN_BUCKET == 0:
                gm, gs, n = ph.estimate_gain(cur_m, cur_s, R.master, R.slave, R.occl_m, R.occl_s); R.set_gains(gm, gs)
            M = Ms[i]; ez = np.array([0, 0, 1.0]); R.update_seam(cur_m, cur_s, reset=(last is None))
            R.set_fov(P['fov'][i], P['dist'][i], P['disc'][i] if P['use_disc'] else None); d = cam.direction(P['yaw'][i], P['pitch'][i])
            fwd_b = d if P['ref'] == 'body' else M @ d                           # body-frame view direction
            t0 = time.time(); last = R.render(cur_m, cur_s, fwd_b, M @ ez, P['roll'][i]); tm['remap'] += time.time() - t0
            last_k = k
        t0 = time.time(); enc.stdin.write(np.ascontiguousarray(last).tobytes()); tm['write'] += time.time() - t0
        if i % 25 == 0: print(f'  frame {i}/{n_out}  {(i + 1) / (time.time() - t_all):.2f} fps', flush=True)
    enc.stdin.close(); enc.wait(); dm.kill(); ds.kill()
    meta = utc_metadata(a.start_utc, t_rel[k0], n_out * dt, a) if a.start_utc else ()
    mux_audio(video_tmp, a.osv, a.out, t_rel[k0], n_out * dt, a.audio, whole, meta); os.remove(video_tmp)
    el = time.time() - t_all
    print(f'done: {n_out} frames ({n_out * dt:.2f} s) in {el:.1f} s = {n_out / el:.2f} fps output.  stage seconds: ' + ', '.join(f'{k}={v:.1f}' for k, v in tm.items()))


if __name__ == '__main__':
    main()
