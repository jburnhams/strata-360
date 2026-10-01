"""The overlay's numbers at any instant: position, distance so far, pace, slope, altitude and heart rate, from the race track (gps/track.py arrays).

Everything is smoothed once over the whole race on a one-second grid, then read at the exact time of each film frame (linear interpolation), so a window shows the values the race had at
that moment with no ramp-up at its edges, and the position marker moves every frame. Values are NaN where the track has no data (outside the race, a gap longer than `max_gap_s`, a pace
slower than `slow_ms`); the overlay shows a dash for those."""
import numpy as np

R_EARTH = 6371008.8


def _resample(T, v, grid, max_gap_s):
    """v (sampled at T, NaN where missing) on the grid: interpolated, NaN where the nearest sample is more than max_gap_s away."""
    ok = np.isfinite(v)
    if ok.sum() < 2: return np.full(len(grid), np.nan)
    Tk = T[ok]; out = np.interp(grid, Tk, v[ok], left=np.nan, right=np.nan)
    j = np.clip(np.searchsorted(Tk, grid), 1, len(Tk) - 1); near = np.minimum(np.abs(grid - Tk[j - 1]), np.abs(Tk[j] - grid))
    out[near > max_gap_s] = np.nan; return out


def _smooth(v, n):
    """Centred moving average over n samples, ignoring NaN (a sample stays NaN only if it was)."""
    if n <= 1: return v.copy()
    ok = np.isfinite(v); k = np.ones(int(n)); s = np.convolve(np.where(ok, v, 0.0), k, 'same'); c = np.convolve(ok.astype(float), k, 'same')
    with np.errstate(invalid='ignore', divide='ignore'): out = s / c
    out[~ok] = np.nan; return out


def path_length(lat, lon):
    """Cumulative distance (m) along points (haversine); NaN positions add nothing."""
    la, lo = np.radians(lat), np.radians(lon); dla, dlo = np.diff(la), np.diff(lo)
    a = np.sin(dla / 2) ** 2 + np.cos(la[:-1]) * np.cos(la[1:]) * np.sin(dlo / 2) ** 2
    d = 2 * R_EARTH * np.arcsin(np.sqrt(np.clip(a, 0, 1))); return np.concatenate([[0.0], np.cumsum(np.nan_to_num(d))])


class Series:
    def __init__(self, tr, pace_s=21, alt_s=9, slope_m=60.0, max_gap_s=10.0, slow_ms=0.5):
        T = np.asarray(tr['t'], float)
        if len(T) < 2: raise ValueError('the track has fewer than two points')
        self.t0, self.t1 = float(T[0]), float(T[-1]); g = np.arange(np.floor(self.t0), np.ceil(self.t1) + 1.0); self.grid = g
        pos = np.isfinite(tr['lat']) & np.isfinite(tr['lon'])
        if pos.sum() < 2: raise ValueError('the track has no positions')
        self.route_lat, self.route_lon, self._pt = tr['lat'][pos], tr['lon'][pos], T[pos]
        dist = np.asarray(tr.get('dist', np.full(len(T), np.nan)), float)
        if np.isfinite(dist).sum() < 0.5 * len(T):                                                           # GPX: no distance field, so measure the path
            dist = np.full(len(T), np.nan); dist[pos] = path_length(self.route_lat, self.route_lon)
        d = _resample(T, dist, g, max_gap_s); self.total_m = float(np.nanmax(dist))
        speed = np.asarray(tr.get('speed', np.full(len(T), np.nan)), float)
        sp = _resample(T, speed, g, max_gap_s) if np.isfinite(speed).sum() >= 0.5 * len(T) else np.gradient(d, g)
        sp = _smooth(sp, pace_s)
        with np.errstate(invalid='ignore', divide='ignore'): pace = np.where(sp > slow_ms, 1000.0 / sp, np.nan)
        alt = _smooth(_resample(T, np.asarray(tr['alt'], float), g, max_gap_s), alt_s)
        self.cols = dict(dist_m=d, pace_s_km=pace, alt_m=alt, slope_pct=self._slope(d, alt, slope_m), hr=_resample(T, np.asarray(tr.get('hr', np.full(len(T), np.nan)), float), g, max_gap_s))

    @staticmethod
    def _slope(d, alt, span):
        """Rise over run (%) across `span` metres of distance centred on each point (steadier than per second when walking or stopped); NaN until the track has covered that much."""
        ok = np.isfinite(d) & np.isfinite(alt)
        if ok.sum() < 2: return np.full(len(d), np.nan)
        dd, aa = d[ok], alt[ok]; dd, first = np.unique(dd, return_index=True); aa = aa[first]
        if len(dd) < 2: return np.full(len(d), np.nan)
        lo, hi = d - span / 2, d + span / 2; inside = (lo >= dd[0]) & (hi <= dd[-1])
        with np.errstate(invalid='ignore'): s = 100.0 * (np.interp(hi, dd, aa) - np.interp(lo, dd, aa)) / span
        s[~(ok & inside)] = np.nan; return np.clip(s, -60, 60)

    def at(self, t):
        """{dist_m, pace_s_km, alt_m, slope_pct, hr} at UTC seconds t (scalar -> floats, array -> arrays)."""
        out = {k: np.interp(t, self.grid, v, left=np.nan, right=np.nan) for k, v in self.cols.items()}
        return {k: float(v) for k, v in out.items()} if np.ndim(t) == 0 else out

    def position(self, t):
        """(lat, lon) at UTC seconds t; held at the ends of the track."""
        return float(np.interp(t, self._pt, self.route_lat)), float(np.interp(t, self._pt, self.route_lon))
