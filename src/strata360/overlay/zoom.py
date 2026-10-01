"""Automatic zoom for the close-up map: closer where the map is busy (a town, a tangle of paths and contours), wider on a long straight stretch where a close-up would show
one line across an empty picture.

Worked out once for the whole race, so every window, the thumbnails and any re-render agree: the route is sampled every `step_m` of distance; at each sample
  - busyness: how much the map draws there (the share of edge pixels in the map picture around it, at a fixed probe zoom), as a rank within this race (0 = the quietest stretch,
    1 = the busiest), so it adapts to the map style and the kind of race;
  - straightness: the straight-line distance over the path distance across `straight_m` of route (1 = dead straight).
zoom = base + range * (2 * busy - 1) - range * straight_weight * straight, kept within base +/- range, then smoothed over `smooth_m` of distance and `smooth_s` of time, so
the map drifts between zooms and holds still when the runner does."""
import numpy as np, cv2
from strata360.overlay.series import _smooth, path_length
from strata360.overlay.tiles import world


def edge_share(rgb):
    """Share (0..1) of the picture that is drawn edges: lines, labels, contours."""
    return float(cv2.Canny(cv2.cvtColor(np.ascontiguousarray(rgb), cv2.COLOR_RGB2GRAY), 60, 160).mean() / 255.0)


def _rank(x):
    """Rank of each value in 0..1, ties sharing their mean rank; all equal -> 0.5."""
    if len(x) < 2: return np.full(len(x), 0.5)
    o = np.argsort(x, kind='stable'); r = np.empty(len(x)); r[o] = np.arange(len(x)); u, inv = np.unique(x, return_inverse=True)
    r = (np.bincount(inv, r) / np.bincount(inv))[inv]; return r / (len(x) - 1)


class Zoom:
    def __init__(self, series, tiles, base=14.0, range_=1.5, probe_zoom=13.0, probe_px=96, step_m=200.0, straight_m=800.0, straight_weight=0.6, smooth_m=1500.0, smooth_s=30.0):
        self.base, self.range = float(base), float(range_)
        g = series.grid; d = series.cols['dist_m']; ok = np.isfinite(d)
        if ok.sum() < 2 or np.nanmax(d) - np.nanmin(d) < step_m: self.t, self.z = g, np.full(len(g), self.base); return
        rt = series._pt; rd = np.interp(rt, g[ok], d[ok]); rd, first = np.unique(rd, return_index=True); lat, lon = series.route_lat[first], series.route_lon[first]
        s = np.arange(rd[0], rd[-1] + 1e-9, step_m); slat, slon = np.interp(s, rd, lat), np.interp(s, rd, lon)
        wx, wy = world(slat, slon); k = 2.0 ** probe_zoom
        busy = np.array([edge_share(np.asarray(tiles.picture(x, y, k, probe_px, probe_px))) for x, y in zip(wx, wy)])
        h = straight_m / 2; a, b = np.clip(s - h, rd[0], rd[-1]), np.clip(s + h, rd[0], rd[-1])
        chord = np.array([path_length(np.array([np.interp(p, rd, lat), np.interp(q, rd, lat)]), np.array([np.interp(p, rd, lon), np.interp(q, rd, lon)]))[-1] for p, q in zip(a, b)])
        straight = np.clip((chord / np.maximum(b - a, 1.0) - 0.8) / 0.18, 0.0, 1.0)
        z = self.base + self.range * (2 * _rank(busy) - 1) - self.range * straight_weight * straight
        z = _smooth(np.clip(z, self.base - self.range, self.base + self.range), max(1, int(round(smooth_m / step_m)) | 1))
        zt = np.interp(np.where(ok, d, np.nan), s, z); zt[~ok] = self.base                                   # by distance: holds while standing still
        self.t, self.z = g, _smooth(zt, max(1, int(round(smooth_s)) | 1)); self.samples = dict(dist_m=s, busy=busy, straight=straight, zoom=z)

    def at(self, t):
        """Zoom level (fractional) at UTC seconds t; the base zoom outside the track."""
        return float(np.interp(t, self.t, self.z, left=self.base, right=self.base))
