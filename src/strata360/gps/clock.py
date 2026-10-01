"""Check (and estimate) the camera clock offset against the race GPS track using running cadence.

The camera telemetry contains the wearer's step rhythm (accelerometer, dominant 1.2-3.5 Hz); the Garmin file has cadence at 1 Hz. For each clip a step-frequency series
is measured (4 s windows, only where one frequency clearly dominates), then a candidate clock offset is scored by how well it matches the watch cadence at the clip's
shifted time. Each clip constrains the offset only weakly, so the answer comes from many clips together; `estimate` returns the score curve and the best offsets."""
import numpy as np
from scipy.ndimage import gaussian_filter1d
from strata360.osv.telemetry import read_frames

WIN_S, HOP_S, MIN_STRENGTH = 4.0, 1.0, 0.25


def step_series(osv):
    T = read_frames(osv); t = (T['ts_us'] - T['ts_us'][0]) / 1e6; fps = (len(t) - 1) / max(t[-1], 1e-6)
    acc = np.linalg.norm(T['acc'], axis=1)
    return step_windows(acc, t, fps)


def step_windows(acc, t, fps):
    """(centre time, step frequency Hz, strength 0..1) per 4 s window at 1 s hops from the accelerometer magnitude."""
    acc = acc - gaussian_filter1d(acc, 1.0 * fps, mode='nearest')
    n = int(WIN_S * fps); out = []
    for s in np.arange(0, t[-1] - WIN_S, HOP_S):
        i = int(s * fps); x = acc[i:i + n]; x = (x - x.mean()) * np.hanning(len(x)); f = np.fft.rfftfreq(len(x), 1 / fps); p = np.abs(np.fft.rfft(x, 8 * len(x))) ** 2; f = np.fft.rfftfreq(8 * len(x), 1 / fps)
        b = (f >= 1.2) & (f <= 3.5); tot = p[(f >= 0.4) & (f <= 8)].sum()
        if b.any() and tot > 0:
            k = np.argmax(p * b); out.append((s + WIN_S / 2, float(f[k]), float(p[b & (abs(f - f[k]) < 0.25)].sum() / tot)))
    return np.array(out).reshape(-1, 3)


def estimate(series, track, offsets_s, min_strength=MIN_STRENGTH):
    """series: list of (clip_start_utc, array from step_series). Score(offset) = mean |camera step Hz - watch step Hz| (watch cadence x2 / 60), lower is better.
    Positive offset means the true UTC is later than the camera clock says."""
    T, C = track['t'], track['cadence'] * 2 / 60.0; ok = np.isfinite(C) & (track['speed'] > 0.3)
    Tg, Cg = T[ok], gaussian_filter1d(C[ok], 2.0)
    obs = [(c0 + s[:, 0], s[:, 1]) for c0, s in series if len(s) for s in [s[s[:, 2] >= min_strength]] if len(s)]
    if not obs: return np.full(len(offsets_s), np.nan), 0
    tt = np.concatenate([o[0] for o in obs]); hz = np.concatenate([o[1] for o in obs]); score = np.empty(len(offsets_s))
    for i, off in enumerate(offsets_s):
        g = np.interp(tt + off, Tg, Cg, left=np.nan, right=np.nan)
        d = np.abs(g - hz); m = np.isfinite(g) & (np.abs(np.interp(tt + off, T, track['t']) - (tt + off)) < 5)      # skip times not covered by a nearby sample
        score[i] = d[m].mean() if m.sum() > 30 else np.nan
    return score, len(tt)


# ---- daylight method: scene brightness (from the camera's own exposure) against the sun's elevation at the clip's GPS position -------------------------------------------

def sun_elevation_deg(lat, lon, t):
    """Solar elevation (degrees) for UTC epoch seconds `t` at lat/lon (degrees); NOAA low-precision formulas, good to about 0.3 degrees."""
    t = np.asarray(t, float); jd = t / 86400.0 + 2440587.5; n = jd - 2451545.0; L = np.radians((280.460 + 0.9856474 * n) % 360); g = np.radians((357.528 + 0.9856003 * n) % 360)
    lam = L + np.radians(1.915) * np.sin(g) + np.radians(0.020) * np.sin(2 * g); eps = np.radians(23.439 - 0.0000004 * n)
    dec = np.arcsin(np.sin(eps) * np.sin(lam)); ra = np.arctan2(np.cos(eps) * np.sin(lam), np.cos(lam))
    gmst = np.radians((280.46061837 + 360.98564736629 * n) % 360); ha = gmst + np.radians(lon) - ra; la = np.radians(lat)
    return np.degrees(np.arcsin(np.sin(la) * np.sin(dec) + np.cos(la) * np.cos(dec) * np.cos(ha)))


def scene_brightness(exposure_doc):
    """Per-frame scene brightness proxy in stops from the camera's own exposure: log2(shutter denominator / ISO) (auto-exposure keeps the picture mid-grey, so darker scenes need more ISO / longer shutter)."""
    b = []
    for f in exposure_doc['frames']:
        c = f['camera']; b.append(np.mean([np.log2(max(c['shutter_den'][i], 1)) - np.log2(max(c['iso'][i], 1)) for i in range(2)]))
    return np.array([f['t_s'] for f in exposure_doc['frames']]), np.array(b)
