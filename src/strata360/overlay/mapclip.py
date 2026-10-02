"""An animated map clip for a stretch of the race with no footage (implementation plan N1): the map follows the runner along the route at a speed-up, with the race overlay's numbers on top.

  clip = MapClip(series, t0, t1, seconds, fps=30, size=(1920, 1080), tiles=Tiles(...), tz='Europe/Brussels')
  clip.frames -> number of frames;  clip.time(k) -> the race time (UTC seconds) frame k shows;  clip.frame(k) -> RGB uint8 picture;  render(clip, path) -> an MP4

Frame k shows the race at `t0 + k * speedup / fps`, so the overlay's clock runs fast and its distance and pace are the real ones at that moment. The camera is centred on the runner (smoothed a
little so a noisy track does not shake the picture) at a zoom that follows how fast the runner moves across the screen: close in when slow, wide when fast, so the marker covers about the same number of
pixels each frame whatever the speed-up (`PX_PER_FRAME`, a fraction of the frame width) within `zoom` limits. The stretch's route behind the marker is drawn in red, ahead of it in white (the rest of the race is left off); the elevation
profile of the stretch runs along the bottom with a cursor. Everything is drawn by our own overlay code (overlay/draw.py, layout.py), no map engine."""
import os, subprocess

import numpy as np, cv2

from strata360 import hw
from strata360.overlay import draw as D
from strata360.overlay.layout import Overlay, REF_W, REF_H, settings
from strata360.overlay.series import _smooth
from strata360.overlay.tiles import Tiles, world

PX_PER_FRAME = 0.004          # how far the marker moves across the frame each frame, as a share of the frame width (~8 px at 1080p: it crosses the picture in about ten seconds)
CAMERA_S = 1.5                # the camera follows the runner smoothed over this much film time
ZOOM_S = 4.0                  # and its zoom over this much
ZOOM = (9.0, 16.0)            # the closest and widest the map goes
ELEMENTS = ['clock', 'distance', 'pace', 'route_map', 'credit']
PROFILE_H = 0.13              # the elevation profile's height as a share of the frame height


def default_style():
    """The map style for a gap clip: the plain landscape map when a Thunderforest key is set (secrets.env or the environment), else the OpenStreetMap one, which needs none."""
    from strata360.edit.llm_remote import secret
    return 'tf-landscape' if secret('THUNDERFOREST_API_KEY') else 'osm'


def frame_count(seconds, fps): return max(1, int(round(float(seconds) * float(fps))))


class MapClip:
    def __init__(self, series, t0, t1, seconds, fps=30.0, size=(1920, 1080), tiles=None, tz='Europe/Brussels', zoom=ZOOM, st=None):
        if not t1 > t0: raise ValueError('the stretch has no length')
        self.series, self.fps, self.size, self.zoom_limits = series, float(fps), tuple(size), zoom; self.W, self.H = size; self.s = min(self.W / REF_W, self.H / REF_H)
        self.frames = frame_count(seconds, fps); self.t0, self.t1 = float(t0), float(t1); self.speedup = (self.t1 - self.t0) / (self.frames / self.fps)
        self.tiles = tiles or Tiles(default_style()); self.rw = world(series.route_lat, series.route_lon); self.rt = series._pt
        ts = self.times(); lat = np.interp(ts, series._pt, series.route_lat); lon = np.interp(ts, series._pt, series.route_lon); self.pos = world(lat, lon)
        n = max(3, int(round(CAMERA_S * self.fps)) | 1); self.cam = (_smooth(self.pos[0], n), _smooth(self.pos[1], n)); self.z = self._zoom_profile()
        self.overlay = Overlay(series, size, settings({**(st or {}), 'elements': ELEMENTS, 'style': self.tiles.style}), tz, self.tiles); self._strip = self._profile_strip()

    def times(self): return self.t0 + np.arange(self.frames) * self.speedup / self.fps

    def time(self, k): return self.t0 + k * self.speedup / self.fps

    def _zoom_profile(self):
        """The zoom of every frame: the one at which the (smoothed) ground speed moves the marker PX_PER_FRAME of the frame width per frame."""
        step = np.hypot(np.diff(self.pos[0], prepend=self.pos[0][0]), np.diff(self.pos[1], prepend=self.pos[1][0])); step[0] = step[1] if len(step) > 1 else 0.0
        step = _smooth(step, max(3, int(round(ZOOM_S * self.fps)) | 1)); lo, hi = self.zoom_limits
        with np.errstate(divide='ignore'): z = np.log2(PX_PER_FRAME * self.W / np.maximum(step, 1e-12))
        return _smooth(np.clip(z, lo, hi), max(3, int(round(ZOOM_S * self.fps)) | 1))

    def _profile_strip(self):
        """The elevation profile of the stretch as an RGBA strip along the bottom (drawn once), and the pixel x/y of its line for the cursor."""
        h = int(round(self.H * PROFILE_H)); g = self.series.grid; ok = (g >= self.t0) & (g <= self.t1) & np.isfinite(self.series.cols['alt_m'])
        self.profile_h = h
        if ok.sum() < 2: self.profile_xy = None; return None
        a = self.series.cols['alt_m'][ok]; t = g[ok]; lo, hi = float(a.min()), float(a.max()); span = max(hi - lo, 20.0); pad = 0.12 * h
        x = (t - self.t0) / (self.t1 - self.t0) * (self.W - 1); y = h - pad - (a - lo) / span * (h - 2 * pad); self.profile_xy = (x, y)
        img = np.zeros((h, self.W, 4), np.uint8); poly = np.concatenate([np.stack([x, y], 1), [[x[-1], h], [x[0], h]]]).round().astype(np.int32)
        cv2.fillPoly(img, [poly.reshape(-1, 1, 2)], (0, 0, 0, 130)); line = np.stack([x, y], 1).round().astype(np.int32).reshape(-1, 1, 2)
        cv2.polylines(img, [line], False, (255, 255, 255, 255), max(1, int(round(2 * self.s))), cv2.LINE_AA); return img

    def frame(self, k):
        """The picture of frame k as RGB uint8."""
        t = self.time(k); W, H = self.W, self.H; z = float(self.z[k]); kk = 2.0 ** z; cx, cy = float(self.cam[0][k]), float(self.cam[1][k])
        img = np.array(self.tiles.picture(cx, cy, kk, W, H), np.uint8); u = (self.rw[0] - cx) * kk + W / 2; v = (self.rw[1] - cy) * kk + H / 2
        inside = (self.rt >= self.t0) & (self.rt <= self.t1); behind = inside & (self.rt <= t); ahead = inside & (self.rt > t); here = ((self.pos[0][k] - cx) * kk + W / 2, (self.pos[1][k] - cy) * kk + H / 2); w = max(1.0, 3 * self.s)
        ub, vb = np.append(u[behind], here[0]), np.append(v[behind], here[1]); ua, va = np.insert(u[ahead], 0, here[0]), np.insert(v[ahead], 0, here[1])
        D.route_line(img, np.where(inside, u, np.nan), np.where(inside, v, np.nan), colour=(0, 0, 0), width=w + 3 * self.s)
        D.route_line(img, ua, va, colour=(250, 250, 250), width=w); D.route_line(img, ub, vb, colour=(230, 20, 20), width=w + self.s)
        dot = D.marker(11 * self.s); r = dot.shape[0] / 2; patches = [(here[0] - r, here[1] - r, dot)]
        if self._strip is not None: patches.insert(0, (0, H - self.profile_h, self._strip))
        D.composite(img, patches)
        if self.profile_xy is not None:
            f = (t - self.t0) / (self.t1 - self.t0); x = f * (self.W - 1); y = float(np.interp(x, *self.profile_xy)) + H - self.profile_h; x, y = int(round(x)), int(round(y))
            cv2.line(img, (x, H - self.profile_h), (x, H), (255, 255, 255), max(1, int(round(self.s))), cv2.LINE_AA); cv2.circle(img, (x, y), max(3, int(round(6 * self.s))), (230, 20, 20), -1, cv2.LINE_AA)
            cv2.circle(img, (x, y), max(3, int(round(6 * self.s))), (255, 255, 255), max(1, int(round(self.s))), cv2.LINE_AA)
        return self.overlay.apply(img, t)


def render(clip, path, progress=None, bitrate='12M'):
    """Encode the clip to an H.264 MP4 at `path` (written beside it and renamed when finished); `progress(done, total)` is called as frames are made."""
    tmp = path + '.part.mp4'; os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    cmd = ['ffmpeg', '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{clip.W}x{clip.H}', '-r', f'{clip.fps:g}', '-i', '-', '-an'] + hw.h264_args(bitrate) + ['-pix_fmt', 'yuv420p', '-movflags', '+faststart', tmp]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    try:
        for k in range(clip.frames):
            p.stdin.write(np.ascontiguousarray(clip.frame(k)).tobytes())
            if progress: progress(k + 1, clip.frames)
        p.stdin.close()
    except BrokenPipeError: pass
    except BaseException: p.kill(); raise
    if p.wait() != 0 or not os.path.exists(tmp): raise RuntimeError('ffmpeg failed to encode the map clip')
    os.replace(tmp, path); return path
