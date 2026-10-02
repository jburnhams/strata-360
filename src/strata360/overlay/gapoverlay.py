"""The race overlay for a generated gap clip (the 2D map, the 3D flyover), so they look like the rest of the film and say what they are showing.

The film's own overlay elements (overlay/layout.py): the clock, distance, pace, altitude, slope and heart rate, the whole-route map with the runner's marker and the map credit, with the bottom row lifted above an elevation profile of the stretch that runs along the bottom with a
cursor, and a caption on top: the stretch's local times, its kilometres and climb, and that it was not filmed. Frame k of a clip shows the race at `t0 + k * speedup / fps`, so every number is the real one at that moment."""
import cv2, numpy as np

from strata360.overlay import draw as D
from strata360.overlay.layout import Overlay, Credit, ELEMENTS as BASE, REF_W, REF_H, settings

PROFILE_H = 0.13                                  # the elevation profile's height as a share of the frame height
LIFT = round(PROFILE_H * REF_H + 10)              # reference pixels the film's bottom row moves up to clear it
ELEMENTS = ['clock', 'distance', 'pace', 'altitude', 'slope', 'heart_rate', 'route_map', 'credit']
LAYOUT = {'pace': dict(y=BASE['pace']['y'] - LIFT), 'altitude': dict(y=BASE['altitude']['y'] - LIFT), 'slope': dict(y=BASE['slope']['y'] - LIFT), 'heart_rate': dict(y=BASE['heart_rate']['y'] - LIFT),
          'credit': dict(x=1900, y=1064 - LIFT, v='bottom', h='right')}


def caption(info):
    """The context line: when, where and how much, and that there is no footage. `info` has local_start, local_end, km_start, km_end, ascent_m (any may be missing)."""
    parts = []
    if info.get('local_start') and info.get('local_end'): parts.append(f"{info['local_start']} → {info['local_end']}")
    if info.get('km_start') is not None and info.get('km_end') is not None: parts.append(f"km {info['km_start']:g}–{info['km_end']:g}")
    if info.get('ascent_m') is not None: parts.append(f"+{info['ascent_m']:g} m")
    parts.append('not filmed')
    return '  ·  '.join(parts)


def profile_strip(series, t0, t1, W, H, s):
    """(RGBA strip, (x, y) arrays of the profile line in strip pixels) for the elevation of [t0, t1] along the bottom, or (None, None) when there is no altitude."""
    h = int(round(H * PROFILE_H)); g = series.grid; ok = (g >= t0) & (g <= t1) & np.isfinite(series.cols['alt_m'])
    if ok.sum() < 2: return None, None
    a = series.cols['alt_m'][ok]; t = g[ok]; lo, hi = float(a.min()), float(a.max()); span = max(hi - lo, 20.0); pad = 0.12 * h
    x = (t - t0) / (t1 - t0) * (W - 1); y = h - pad - (a - lo) / span * (h - 2 * pad)
    img = np.zeros((h, W, 4), np.uint8); poly = np.concatenate([np.stack([x, y], 1), [[x[-1], h], [x[0], h]]]).round().astype(np.int32)
    cv2.fillPoly(img, [poly.reshape(-1, 1, 2)], (0, 0, 0, 130)); line = np.stack([x, y], 1).round().astype(np.int32).reshape(-1, 1, 2)
    cv2.polylines(img, [line], False, (255, 255, 255, 255), max(1, int(round(2 * s))), cv2.LINE_AA); return img, (x, y)


class GapOverlay:
    def __init__(self, series, size, t0, t1, tz='Europe/Brussels', tiles=None, st=None, credit=None, info=None):
        self.W, self.H = size; self.s = min(self.W / REF_W, self.H / REF_H); self.t0, self.t1 = float(t0), float(t1); self.h = int(round(self.H * PROFILE_H))
        base = dict(st or {}); style = ({'style': tiles.style} if tiles is not None else {})
        self.overlay = Overlay(series, size, settings({**base, **style, 'elements': ELEMENTS, 'layout': {**LAYOUT, **base.get('layout', {})}}), tz, tiles)
        if credit:
            for w in self.overlay.widgets:
                if isinstance(w, Credit): w.lines = list(credit)
        self.strip, self.xy = profile_strip(series, self.t0, self.t1, self.W, self.H, self.s); self.caption = None
        text = caption(info or {})
        if text:
            rgba, pad, width = D.text(text, 24 * self.s, D.VALUE_FONT, (255, 255, 255)); self.caption = ((self.W - width) / 2 - pad, 24 * self.s - pad, rgba)

    def apply(self, img, t):
        """Draw the profile with its cursor, the caption and the film's overlay for race time `t` onto the RGB picture, in place; returns it."""
        W, H = self.W, self.H
        if self.strip is not None:
            D.composite(img, [(0, H - self.h, self.strip)]); x = (t - self.t0) / (self.t1 - self.t0) * (W - 1); y = float(np.interp(x, *self.xy)) + H - self.h; xi, yi = int(round(x)), int(round(y)); r = max(3, int(round(6 * self.s)))
            cv2.line(img, (xi, H - self.h), (xi, H), (255, 255, 255), max(1, int(round(self.s))), cv2.LINE_AA); cv2.circle(img, (xi, yi), r, (230, 20, 20), -1, cv2.LINE_AA); cv2.circle(img, (xi, yi), r, (255, 255, 255), max(1, int(round(self.s))), cv2.LINE_AA)
        if self.caption: D.composite(img, [self.caption])
        return self.overlay.apply(img, t)
