"""An animated map clip for a stretch of the race with no footage (implementation plan N1): the map follows the runner along the route at a speed-up, 

  clip = MapClip(series, t0, t1, seconds, fps=30, size=(1920, 1080), tiles=Tiles(...), tz='Europe/Brussels')
  clip.frames -> number of frames;  clip.time(k) -> the race time (UTC seconds) frame k shows;  clip.frame(k) -> RGB uint8 picture;  render(clip, path) -> an MP4

Frame k shows the race at `t0 + k * speedup / fps`. There is NO overlay in the picture: the film puts its own overlay (clock, distance, pace, maps, the same as on every other shot) on this clip when it is played, at the race time each frame shows (render/final.py), so the overlay is the same all through the film. The camera is centred on the runner (smoothed a
little so a noisy track does not shake the picture) at a zoom that follows how fast the runner moves across the screen: close in when slow, wide when fast, so the marker covers about the same number of
pixels each frame whatever the speed-up (`PX_PER_FRAME`, a fraction of the frame width) within `zoom` limits. The whole route that is on the screen is drawn in ONE colour, as on the overview map, with the marker moving along it: the clip is a cut of the journey, so the stretch it covers is not marked (the before and after stay in view). The camera is centred on the runner (smoothed a
little so a noisy track does not shake the picture) at a zoom that follows how fast the runner moves across the screen: close in when slow, wide when fast, so the marker covers about the same number of
pixels each frame whatever the speed-up (`PX_PER_FRAME`, a fraction of the frame width) within `zoom` limits. The whole route that is on the screen is drawn thin and grey, so the clip reads as one part of the journey with its before and after in view; the stretch itself is drawn over it, in red behind the marker and in white ahead of it. Drawn by our own
overlay code (overlay/draw.py, tiles.py), no map engine."""
import os, subprocess

import numpy as np, cv2

from strata360 import hw
from strata360.overlay import draw as D
from strata360.overlay.layout import REF_W, REF_H
from strata360.overlay.series import _smooth
from strata360.overlay.tiles import Tiles, world

PX_PER_FRAME = 0.004          # how far the marker moves across the frame each frame, as a share of the frame width (~8 px at 1080p: it crosses the picture in about ten seconds)
CAMERA_S = 1.5                # the camera follows the runner smoothed over this much film time
ZOOM_S = 4.0                  # and its zoom over this much
ZOOM = (9.0, 16.0)            # the closest and widest the map goes


ROUTE = (230, 20, 20)         # the route, all of it, in one colour


DEFAULT_STYLE = 'tf-landscape'      # plain landscape map; needs THUNDERFOREST_API_KEY (a missing key is an error, never a quiet change of map; `--style osm` chooses the key-free map on purpose)


def frame_count(seconds, fps): return max(1, int(round(float(seconds) * float(fps))))


class MapClip:
    def __init__(self, series, t0, t1, seconds, fps=30.0, size=(1920, 1080), tiles=None, tz='Europe/Brussels', zoom=ZOOM):
        if not t1 > t0: raise ValueError('the stretch has no length')
        self.series, self.fps, self.size, self.zoom_limits = series, float(fps), tuple(size), zoom; self.W, self.H = size; self.s = min(self.W / REF_W, self.H / REF_H)
        self.frames = frame_count(seconds, fps); self.t0, self.t1 = float(t0), float(t1); self.speedup = (self.t1 - self.t0) / (self.frames / self.fps)
        self.tiles = tiles or Tiles(DEFAULT_STYLE); self.rw = world(series.route_lat, series.route_lon); self.rt = series._pt
        ts = self.times(); lat = np.interp(ts, series._pt, series.route_lat); lon = np.interp(ts, series._pt, series.route_lon); self.pos = world(lat, lon)
        n = max(3, int(round(CAMERA_S * self.fps)) | 1); self.cam = (_smooth(self.pos[0], n), _smooth(self.pos[1], n)); self.z = self._zoom_profile()

    def times(self): return self.t0 + np.arange(self.frames) * self.speedup / self.fps

    def time(self, k): return self.t0 + k * self.speedup / self.fps

    def _zoom_profile(self):
        """The zoom of every frame: the one at which the (smoothed) ground speed moves the marker PX_PER_FRAME of the frame width per frame."""
        step = np.hypot(np.diff(self.pos[0], prepend=self.pos[0][0]), np.diff(self.pos[1], prepend=self.pos[1][0])); step[0] = step[1] if len(step) > 1 else 0.0
        step = _smooth(step, max(3, int(round(ZOOM_S * self.fps)) | 1)); lo, hi = self.zoom_limits
        with np.errstate(divide='ignore'): z = np.log2(PX_PER_FRAME * self.W / np.maximum(step, 1e-12))
        return _smooth(np.clip(z, lo, hi), max(3, int(round(ZOOM_S * self.fps)) | 1))

    def frame(self, k):
        """The picture of frame k as RGB uint8."""
        W, H = self.W, self.H; z = float(self.z[k]); kk = 2.0 ** z; cx, cy = float(self.cam[0][k]), float(self.cam[1][k])
        img = np.array(self.tiles.picture(cx, cy, kk, W, H), np.uint8); u = (self.rw[0] - cx) * kk + W / 2; v = (self.rw[1] - cy) * kk + H / 2
        here = ((self.pos[0][k] - cx) * kk + W / 2, (self.pos[1][k] - cy) * kk + H / 2); w = max(1.0, 3 * self.s)
        D.route_line(img, u, v, colour=(0, 0, 0), width=w + 3 * self.s); D.route_line(img, u, v, colour=ROUTE, width=w + self.s)                  # the whole route that is on screen in ONE colour, as on the overview map: the clip is a cut of the journey, the stretch is not marked
        dot = D.marker(11 * self.s); r = dot.shape[0] / 2; D.composite(img, [(here[0] - r, here[1] - r, dot)])
        return img


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
