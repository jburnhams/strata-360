"""How high the sun was: the one place the label for it is made, and the per-clip field (`sun.json`, the `sun` stage).

`daylight(elev)` turns an elevation in degrees into 'day' (above 6), 'golden hour' (above 0), 'twilight' (above -12) or 'night'; `daylight_at(lat, lon, t)` does it for a place and a moment (gaps with no footage, street-view
pictures); `analyse(clip_json, track)` works it out for a clip at its start, middle and end from the clip's UTC time and where the race track says it was. The stage stores that, and everything that needs the sun for a CLIP
(the clip card, the scene labels) reads the stored field instead of working it out again. The elevation itself comes from gps/clock.py (also used there to check the camera clock against the scene's brightness)."""
import datetime as dt
import json
import os

import numpy as np

from strata360.gps.clock import sun_elevation_deg

FILE = 'sun.json'


def daylight(elev):
    return 'day' if elev > 6 else 'golden hour' if elev > 0 else 'twilight' if elev > -12 else 'night'


def daylight_at(lat, lon, t):
    """The daylight label at a place and a UTC epoch time, or None when either is unknown."""
    if lat is None or lon is None or t is None: return None
    return daylight(float(sun_elevation_deg(lat, lon, t)))


def _local(t, tz):
    from zoneinfo import ZoneInfo
    return dt.datetime.fromtimestamp(float(t), dt.timezone.utc).astimezone(ZoneInfo(tz))


def _at(tr, key, t):
    ok = np.isfinite(tr[key])
    return float(np.interp(t, tr['t'][ok], tr[key][ok])) if ok.any() else None


def analyse(clip_json, tr, tz='Europe/Brussels'):
    """The sun for a clip: {covered, start, mid, end: {t_utc, local, lat, lon, elevation_deg, daylight}, elevation_deg and daylight at the middle, lowest and highest elevation, whether the label changes during the clip}.
    `covered` is False when the track does not reach the clip (before the start, after the finish)."""
    t0 = dt.datetime.fromisoformat(clip_json['time']['start_utc'].replace('Z', '+00:00')).timestamp(); dur = clip_json['video']['source_frames'] / clip_json['video']['nominal_fps']; T = tr['t']
    if t0 + dur < float(T[0]) - 60 or t0 > float(T[-1]) + 60: return dict(schema=1, covered=False, note='outside the race track (before the start or after the finish)', duration_s=round(dur, 1))
    out = dict(schema=1, covered=True, timezone=tz, duration_s=round(dur, 1)); elevs = []
    for name, t in (('start', t0), ('mid', t0 + dur / 2), ('end', t0 + dur)):
        lat, lon = _at(tr, 'lat', t), _at(tr, 'lon', t)
        if lat is None or lon is None: return dict(schema=1, covered=False, note='the track has no position here', duration_s=round(dur, 1))
        e = float(sun_elevation_deg(lat, lon, t)); elevs.append(e)
        out[name] = dict(t_utc=dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'), local=_local(t, tz).strftime('%a %d %b %H:%M'), lat=round(lat, 5), lon=round(lon, 5), elevation_deg=round(e, 1), daylight=daylight(e))
    out.update(elevation_deg=out['mid']['elevation_deg'], daylight=out['mid']['daylight'], lowest_deg=round(min(elevs), 1), highest_deg=round(max(elevs), 1), changes=out['start']['daylight'] != out['end']['daylight'])
    return out


def load(clip_dir):
    """The stored sun field of a clip folder, or None when the stage has not run for it."""
    try: return json.load(open(os.path.join(clip_dir, FILE)))
    except (OSError, ValueError): return None


def elevation_in_clip(sun, t_s):
    """The sun's elevation at `t_s` seconds into the clip, between the start, middle and end values; None when the clip is not covered."""
    if not sun or not sun.get('covered'): return None
    dur = float(sun.get('duration_s') or 0.0); xs = [0.0, dur / 2, dur]; ys = [sun[k]['elevation_deg'] for k in ('start', 'mid', 'end')]
    return float(np.interp(t_s, xs, ys)) if dur > 0 else float(ys[1])
