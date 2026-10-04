"""What the race track says about a moment: speed/pace, gradient, altitude, heart rate, distance and share of the race completed, elapsed time, local time and daylight.

`context_at(track, t0, t1)` works on any UTC span (a whole clip, a candidate, a planned segment) and is what the voice-over script writer and the GUI show. Positions are
coordinates only (no place names offline); the user's notes fill that gap."""
import datetime as dt
import numpy as np
from strata360.gps.clock import sun_elevation_deg
from strata360.gps.sun import daylight                      # the label for a sun elevation is made in one place (gps/sun.py); kept importable from here


def _local(t, tz):
    from zoneinfo import ZoneInfo
    return dt.datetime.fromtimestamp(float(t), dt.timezone.utc).astimezone(ZoneInfo(tz))


def _window(tr, a, b):
    return np.flatnonzero((tr['t'] >= a) & (tr['t'] <= b))


def context_at(tr, t0, t1, tz='Europe/Brussels', grade_window_s=60.0):
    """Facts about the span [t0, t1] (UTC epoch seconds). Fields are None when the track lacks them; `covered` is False outside the race."""
    T = tr['t']; start, end = float(T[0]), float(T[-1]); mid = 0.5 * (t0 + t1)
    if t1 < start - 60 or t0 > end + 60: return dict(covered=False, note='outside the race track (before the start or after the finish)')
    ok = np.isfinite(tr['lat']); lat = float(np.interp(mid, T[ok], tr['lat'][ok])); lon = float(np.interp(mid, T[ok], tr['lon'][ok]))

    def col(name, a, b):
        idx = _window(tr, a, b); v = tr[name][idx] if len(idx) else np.array([]); return v[np.isfinite(v)]

    total = float(np.nanmax(tr['dist'])) if np.isfinite(tr['dist']).any() else None
    d_mid = float(np.interp(mid, T, np.nan_to_num(tr['dist'], nan=0.0))) if total else None
    sp = col('speed', t0, t1); moving = sp[sp > 0.5]; hr = col('hr', t0, t1); cad = col('cadence', t0, t1)
    idx = _window(tr, mid - grade_window_s / 2, mid + grade_window_s / 2); grade = None
    if len(idx) > 5 and total:
        alt = tr['alt'][idx]; dist = tr['dist'][idx]; g = np.isfinite(alt) & np.isfinite(dist)
        if g.sum() > 5 and dist[g][-1] - dist[g][0] > 8: grade = float(100.0 * (alt[g][-1] - alt[g][0]) / (dist[g][-1] - dist[g][0]))
    elev = float(sun_elevation_deg(lat, lon, mid)); lt = _local(mid, tz); day1 = _local(start, tz).date()
    pace = None if not len(moving) else 1000.0 / float(np.mean(moving))
    return dict(covered=True, lat=round(lat, 5), lon=round(lon, 5),
                altitude_m=None if not np.isfinite(tr['alt']).any() else round(float(np.interp(mid, T, np.nan_to_num(tr['alt'], nan=0.0))), 0),
                speed_kmh=None if not len(sp) else round(float(np.mean(sp)) * 3.6, 1), pace_min_per_km=None if pace is None else round(pace / 60.0, 2), moving=bool(len(moving) > 0.5 * max(len(sp), 1)),
                gradient_pct=None if grade is None else round(grade, 1), heart_rate=None if not len(hr) else round(float(np.mean(hr))), cadence_spm=None if not len(cad) else round(float(np.mean(cad)) * 2),
                distance_km=None if d_mid is None else round(d_mid / 1000.0, 1), race_total_km=None if total is None else round(total / 1000.0, 1),
                percent_of_distance=None if not total else round(100.0 * d_mid / total, 1), percent_of_time=round(100.0 * (mid - start) / max(end - start, 1.0), 1),
                elapsed_h=round((mid - start) / 3600.0, 2), race_day=(lt.date() - day1).days + 1, local_time=lt.strftime('%H:%M'), local_date=lt.strftime('%a %d %b'),
                sun_elevation_deg=round(elev, 1), daylight=daylight(elev))


def describe(c):
    """One line of plain words for a prompt or a caption."""
    if not c.get('covered'): return c.get('note', 'no track data')
    bits = [f"{c['local_date']} {c['local_time']} local ({c['daylight']}), race day {c['race_day']}, {c['elapsed_h']} h in"]
    if c.get('distance_km') is not None: bits.append(f"km {c['distance_km']} of {c['race_total_km']} ({c['percent_of_distance']:.0f}% of the distance)")
    if c.get('pace_min_per_km') and c['moving']: bits.append(f"pace {int(c['pace_min_per_km'])}:{int(round((c['pace_min_per_km'] % 1) * 60)):02d} min/km ({c['speed_kmh']} km/h)")
    elif c.get('moving') is False: bits.append('stopped or walking very slowly')
    if c.get('gradient_pct') is not None: bits.append(('climbing' if c['gradient_pct'] > 3 else 'descending' if c['gradient_pct'] < -3 else 'flat') + f" ({c['gradient_pct']:+.0f}%)")
    if c.get('altitude_m') is not None: bits.append(f"{c['altitude_m']:.0f} m altitude")
    if c.get('heart_rate'): bits.append(f"heart rate {c['heart_rate']}")
    return '; '.join(bits)
