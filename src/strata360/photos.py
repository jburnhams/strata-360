"""Photos taken during the race: uploaded into the project, placed in the race by their time stamp and on the map by where they were taken.

  <project>/photos.json        the photos: [{id, name, file, taken_utc, time_source, gps, width, height, added}]
  <project>/photos/<id>-<name> the files (a removed photo is moved to photos/removed/, never deleted)
  <project>/photos/thumbs/     small copies for the pages (made when first asked for)

When: the photo's EXIF. The GPS time stamp (UTC) is the most exact; else the camera's local time with its UTC offset (OffsetTimeOriginal) when it has one; else the local time taken to be in the race's own time zone.
Where: first the GPS position in the EXIF; second where the run was at that time (the race track at the time stamp). `located()` gives both, the one used (the photo's own GPS first), and how far apart they are: a gap of more than `FAR_M` is flagged, since it means the camera's clock is
wrong, the photo was taken away from the run, or the position is poor. A photo outside the time of the run has no position from the track."""
import datetime as dt, json, os, re, shutil, subprocess, sys, time
from zoneinfo import ZoneInfo

import numpy as np

EXTS = ('.jpg', '.jpeg', '.jpe', '.png', '.tif', '.tiff', '.webp', '.avif', '.bmp', '.gif', '.heic', '.heif')          # whatever Pillow reads, and HEIC / HEIF (converted); the pages always show JPEG copies
MAX_BYTES = 80 * 1024 * 1024
FAR_M = 500.0              # the photo's own position and the run's at that time further apart than this is flagged
SLACK_S = 120.0            # a photo this long before the run began or after it ended is still placed at its first or last point
FILE = 'photos.json'


def _path(rd): return os.path.join(rd, FILE)


def load(rd):
    try: d = json.load(open(_path(rd)))
    except (OSError, ValueError): d = {}
    d.setdefault('photos', []); d.setdefault('next', 1); return d


def _save(rd, doc):
    os.makedirs(rd, exist_ok=True); p = _path(rd); tmp = p + '.tmp'
    with open(tmp, 'w') as f: json.dump(doc, f, indent=1)
    os.replace(tmp, p)


def _rat(v):
    try: return float(v)
    except (TypeError, ValueError): return float(v[0]) / float(v[1]) if v[1] else 0.0


def _dms(vals, ref):
    d, m, s = (_rat(x) for x in vals); x = d + m / 60.0 + s / 3600.0
    return -x if str(ref).upper() in ('S', 'W') else x


def convert_heic(path):
    """A JPEG copy of a HEIC / HEIF photo (next to it, `.jpg`), made with pillow-heif when it is installed, else with macOS `sips`; None when neither can."""
    out = os.path.splitext(path)[0] + '.converted.jpg'
    try:
        import pillow_heif
        pillow_heif.register_heif_opener()
        from PIL import Image
        im = Image.open(path); im.save(out, 'JPEG', quality=92, exif=im.getexif()); return out
    except ImportError: pass
    if sys.platform == 'darwin' and shutil.which('sips'):
        r = subprocess.run(['sips', '-s', 'format', 'jpeg', path, '--out', out], capture_output=True)
        if r.returncode == 0 and os.path.exists(out): return out
    return None


def read_exif(path):
    """What the photo says about itself: {local: naive datetime or None, offset_s: seconds east of UTC or None, gps_utc: aware datetime or None, lat, lon (or None), width, height, make, model}. Raises ValueError for a file that is not an image."""
    from PIL import Image
    try: im = Image.open(path); im.load()
    except Exception as e: raise ValueError(f'not an image I can read ({type(e).__name__}: {e})')
    ex = im.getexif(); sub = ex.get_ifd(0x8769) if ex else {}; gps = ex.get_ifd(0x8825) if ex else {}
    raw = sub.get(0x9003) or sub.get(0x9004) or ex.get(0x0132); local = None
    if raw:
        try: local = dt.datetime.strptime(str(raw).strip()[:19], '%Y:%m:%d %H:%M:%S')
        except ValueError: local = None
    off = None; m = re.fullmatch(r'\s*([+-])(\d{2}):?(\d{2})\s*', str(sub.get(0x9011) or ''))
    if m: off = (1 if m.group(1) == '+' else -1) * (int(m.group(2)) * 3600 + int(m.group(3)) * 60)
    gps_utc = None
    if gps.get(29) and gps.get(7):
        try: h, mi, s = (_rat(x) for x in gps[7]); gps_utc = dt.datetime.strptime(str(gps[29]).strip()[:10], '%Y:%m:%d').replace(tzinfo=dt.timezone.utc) + dt.timedelta(hours=h, minutes=mi, seconds=s)
        except (ValueError, TypeError, ZeroDivisionError): gps_utc = None
    lat = lon = None
    if gps.get(2) and gps.get(4):
        try: lat, lon = _dms(gps[2], gps.get(1, 'N')), _dms(gps[4], gps.get(3, 'E'))
        except (ValueError, TypeError, ZeroDivisionError): lat = lon = None
        if lat is not None and (lat == 0.0 and lon == 0.0 or not (-90 <= lat <= 90 and -180 <= lon <= 180)): lat = lon = None          # (0, 0) is a camera with no fix
    return dict(local=local, offset_s=off, gps_utc=gps_utc, lat=lat, lon=lon, width=im.width, height=im.height, make=str(ex.get(0x010F) or '').strip(), model=str(ex.get(0x0110) or '').strip())


def when(info, tz):
    """(UTC seconds, how it was worked out) for a photo's EXIF: 'gps clock' (the GPS time stamp), 'camera clock + offset' or 'camera clock, assumed {tz}'. (None, None) when it has no time."""
    if info['gps_utc'] is not None: return info['gps_utc'].timestamp(), 'gps clock'
    if info['local'] is None: return None, None
    if info['offset_s'] is not None: return (info['local'] - dt.timedelta(seconds=info['offset_s'])).replace(tzinfo=dt.timezone.utc).timestamp(), 'camera clock + offset'
    return info['local'].replace(tzinfo=ZoneInfo(tz)).timestamp(), f'camera clock, assumed {tz}'


def _safe(name): return re.sub(r'[^A-Za-z0-9._-]+', '_', os.path.basename(name))[:80] or 'photo'


def add(rd, filename, data, tz='Europe/Brussels'):
    """Save an uploaded photo and read when and where it was taken. Raises ValueError (with a message to show) for a file that is not a photo, is too big or has no time stamp. Returns the entry."""
    ext = os.path.splitext(filename)[1].lower()
    if ext not in EXTS: raise ValueError(f'a photo, please ({", ".join(EXTS)})')
    if len(data) < 200 or len(data) > MAX_BYTES: raise ValueError('the file is empty or too large')
    doc = load(rd); pid = f"p{doc['next']}"; d = os.path.join(rd, 'photos'); os.makedirs(d, exist_ok=True); dest = os.path.join(d, f'{pid}-{_safe(filename)}')
    while os.path.exists(dest): dest = os.path.join(d, f'{pid}-{int(time.time() * 1000)}-{_safe(filename)}')                  # an upload never overwrites a file (the counter could be lost with photos.json)
    with open(dest, 'wb') as f: f.write(data)
    work = dest
    try:
        if ext in ('.heic', '.heif'):
            work = convert_heic(dest)
            if work is None: raise ValueError('HEIC photos need pillow-heif (pip install pillow-heif) or macOS; export the photo as JPEG and upload that')
        info = read_exif(work); t, how = when(info, tz)
        if t is None: raise ValueError('the photo has no time stamp (EXIF date): without it I cannot place it in the race')
    except ValueError:
        os.replace(dest, dest + '.bad'); raise
    ow, oh = oriented_size(work)
    entry = dict(id=pid, name=os.path.basename(filename), file=os.path.relpath(work, rd).replace(os.sep, '/'), original=os.path.relpath(dest, rd).replace(os.sep, '/'), taken_utc=round(t, 3), time_source=how, width=ow, height=oh, camera=(info['make'] + ' ' + info['model']).strip(),
                 gps=dict(lat=round(info['lat'], 6), lon=round(info['lon'], 6)) if info['lat'] is not None else None, added=dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'))
    doc['photos'].append(entry); doc['next'] += 1; _save(rd, doc); return entry


def oriented_size(path):
    """(width, height) of the photo as it is shown (turned the right way up by its EXIF orientation)."""
    from PIL import Image
    im = Image.open(path); w, h = im.size; o = im.getexif().get(0x0112); return (h, w) if o in (5, 6, 7, 8) else (w, h)


def label_of(entry_or_id):
    """The name the script and the plan call a photo: p3 -> P3."""
    return str(entry_or_id['id'] if isinstance(entry_or_id, dict) else entry_or_id).upper()


def is_used(e):
    """Whether the photo is an option for the film (ticked "Use in the film"): the script writer may show it, it sits among the clips in the sidebar and counts as footage when gaps are found. A photo marked `must` is used too."""
    return bool(e.get('use') or e.get('must'))


def set_use(rd, pid, use):
    """Make a photo an option for the film, or not (taking it out also clears `must`). Raises KeyError for an unknown photo."""
    doc = load(rd); e = next((p for p in doc['photos'] if p['id'] == pid), None)
    if e is None: raise KeyError(pid)
    if use: e['use'] = True
    else: e.pop('use', None); e.pop('must', None)
    _save(rd, doc); return bool(use)


def set_must(rd, pid, must):
    """Mark a photo MUST be used in the film (the plan adds it where its time falls if the script leaves it out; it is used too), or not. Raises KeyError for an unknown photo."""
    doc = load(rd); e = next((p for p in doc['photos'] if p['id'] == pid), None)
    if e is None: raise KeyError(pid)
    if must: e['must'] = True; e['use'] = True
    else: e.pop('must', None)
    _save(rd, doc); return bool(must)


MOTION_DEFAULT = dict(style='auto', seconds=None, seed=0)             # seconds None: the length follows how busy the photo is (analysis/photo_analysis.py `auto_seconds`, 2 to 3 s)


def motion_of(entry):
    """The pan and zoom chosen for a photo (edit/photo_motion.py): {style: 'auto' or one of its styles, seconds, seed}."""
    return {**MOTION_DEFAULT, **(entry.get('motion') or {})}


def set_motion(rd, pid, **fields):
    """Change some of a photo's pan and zoom settings (style, seconds, seed); returns all three. Raises ValueError for a value that is not allowed, KeyError for an unknown photo."""
    from strata360.edit import photo_motion as PM
    doc = load(rd); e = next((p for p in doc['photos'] if p['id'] == pid), None)
    if e is None: raise KeyError(pid)
    cur = motion_of(e)
    for k, v in fields.items():
        if k not in cur: raise ValueError(f'unknown setting {k}')
        cur[k] = v
    if cur['style'] != 'auto' and cur['style'] not in PM.STYLES: raise ValueError(f'style: auto or one of {", ".join(PM.STYLES)}')
    try:
        if cur['seconds'] is not None: cur['seconds'] = round(float(cur['seconds']), 2)
        cur['seed'] = int(cur['seed'])
    except (TypeError, ValueError): raise ValueError('seconds and seed must be numbers')
    if cur['seconds'] is not None and not 2.0 <= cur['seconds'] <= 8.0: raise ValueError('the length: 2 to 8 seconds, or leave it to the photo (2 to 3 s by how busy it is)')
    if cur == MOTION_DEFAULT: e.pop('motion', None)
    else: e['motion'] = cur
    _save(rd, doc); return cur


def remove(rd, pid):
    """Take a photo out of the project (its files are moved to photos/removed/, never deleted)."""
    doc = load(rd); e = next((p for p in doc['photos'] if p['id'] == pid), None)
    if e is None: raise KeyError(pid)
    gone = os.path.join(rd, 'photos', 'removed'); os.makedirs(gone, exist_ok=True)
    for rel in {e['file'], e.get('original')}:
        p = os.path.join(rd, rel) if rel else None
        if p and os.path.exists(p): os.replace(p, os.path.join(gone, os.path.basename(p)))
    doc['photos'] = [p for p in doc['photos'] if p['id'] != pid]; _save(rd, doc)


def thumb(rd, pid, width=480):
    """Path of a JPEG copy of the photo up to `width` px wide (turned the right way up; any format in, JPEG out), made when first asked for. None for an unknown photo."""
    from PIL import Image, ImageOps
    e = next((p for p in load(rd)['photos'] if p['id'] == pid), None)
    if e is None: return None
    width = max(64, min(int(width), 4000)); out = os.path.join(rd, 'photos', 'thumbs', f'{pid}-{width}.jpg'); src = os.path.join(rd, e['file'])
    if os.path.exists(out) and os.path.getmtime(out) >= os.path.getmtime(src): return out
    os.makedirs(os.path.dirname(out), exist_ok=True); im = ImageOps.exif_transpose(Image.open(src)); im.thumbnail((width, width * 3))
    if im.mode in ('RGBA', 'LA', 'P'): bg = Image.new('RGB', im.size, (255, 255, 255)); rgba = im.convert('RGBA'); bg.paste(rgba, mask=rgba.split()[3]); im = bg          # (transparency on white)
    elif im.mode in ('I;16', 'I', 'F'): im = im.point(lambda v: v / 256).convert('L')                                                                                       # (16-bit grey)
    im.convert('RGB').save(out, 'JPEG', quality=85 if width <= 1200 else 90); return out


def _haversine(la1, lo1, la2, lo2):
    p1, p2 = np.radians(la1), np.radians(la2); a = np.sin((p2 - p1) / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(np.radians(lo2 - lo1) / 2) ** 2; return float(2 * 6371000.0 * np.arcsin(np.sqrt(a)))


def run_position(run, t):
    """Where the run was at UTC seconds t: {lat, lon, elapsed_s, km} by interpolating the race track; None when t is more than SLACK_S outside the run. `run` is the track's arrays (gps/track.py)."""
    ok = np.isfinite(run['t']) & np.isfinite(run['lat']) & np.isfinite(run['lon']); tt, la, lo = run['t'][ok], run['lat'][ok], run['lon'][ok]
    if len(tt) < 2 or t < tt[0] - SLACK_S or t > tt[-1] + SLACK_S: return None
    from strata360.gps.tracks import _dist
    cum = _dist(la, lo); return dict(lat=round(float(np.interp(t, tt, la)), 6), lon=round(float(np.interp(t, tt, lo)), 6), elapsed_s=round(float(max(t, tt[0]) - tt[0])), km=round(float(np.interp(t, tt, cum)) / 1000.0, 2))


def located(entry, run):
    """The photo with where it was: `track` (the run's position at its time), `gps` (its own), `loc` {lat, lon, source: 'photo gps' | 'run track'} (its own first), `apart_m` between the two when both exist, `flag` when they are far apart or the time is outside the run."""
    out = dict(entry); tr = run_position(run, entry['taken_utc']) if run is not None else None; g = entry.get('gps'); out['track'] = tr
    out['loc'] = dict(lat=g['lat'], lon=g['lon'], source='photo gps') if g else dict(lat=tr['lat'], lon=tr['lon'], source='run track') if tr else None
    out['apart_m'] = round(_haversine(g['lat'], g['lon'], tr['lat'], tr['lon'])) if g and tr else None; out['flag'] = None
    if out['apart_m'] is not None and out['apart_m'] > FAR_M: out['flag'] = f"the photo's position and the run's at that time are {out['apart_m'] / 1000:.1f} km apart (the camera clock may be wrong)"
    elif tr is None and run is not None: out['flag'] = 'taken outside the time of the run'
    elif out['loc'] is None and run is None: out['flag'] = 'no race track to place it on'
    return out


def assign(t, clips, gaps):
    """Which clip or gap the time falls in: {kind: 'clip' | 'gap', id} or None. `clips` are [{id, start_utc (ISO), duration_s}], `gaps` [{id, t0, t1}] (epoch seconds)."""
    for c in clips:
        a = dt.datetime.fromisoformat(str(c['start_utc']).replace('Z', '+00:00')).timestamp()
        if a <= t <= a + float(c['duration_s']): return dict(kind='clip', id=c['id'])
    for g in gaps:
        if g['t0'] <= t <= g['t1']: return dict(kind='gap', id=g['id'])
    return None
