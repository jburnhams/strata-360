"""A point camera (edit/pointcam.py) as pictures: where its path is, its preview and its clip for the film.

  source_poly(folder, source)           the path the camera looks from: a clip's stretch of the race track, or the pictures of a street view section (with the race time the runner passed each)
  plan(folder, cam, seconds=None)       dict(window, samples, facts, calibration): the stretch the shot covers (held to `seconds` round the closest approach) and its camera path
  render_preview(folder, cam, out, log) a small video (clip: from the clip's proxy, 960 wide; street view: the section's pictures) to judge the shot by
  render(folder, cam, seconds, out, log) the film's clip (picture only, 2560x1440), like edit/streetview_clip.py and photo_clip.py
  sync(folder, specs, log)              makes synthetic.json and the videos match the plan's point camera clips (labels C1 ...)

A clip's shot is the clip's proxy seen through the real renderer's projection (render/preview.py) along the camera path, at the speed it was filmed: its length is the time the runner took over the stretch. A street view shot is the section's own pictures (360 only), blended
between neighbours as the street view clip is, played in the length asked for (the pictures are 5 to 15 m apart, so a real-time shot would be a slide show)."""
import datetime as dt, json, os

import numpy as np

from strata360 import streetview as SV
from strata360.edit import pointcam as PC, synthetic as SY
from strata360.pipeline import config

PREVIEW_SIZE = (960, 540)
CLIP_SIZE = (2560, 1440)
FPS = 25.0                    # the proxy preview renderer's rate (render/preview.py)
SV_PLAY_MS = 25.0             # a street view shot is played as if the car moved at this speed (m/s) unless a length is asked for: a fast, smooth fly-by (the clip probe's speed)


def _epoch(iso): return dt.datetime.fromisoformat(str(iso).replace('Z', '+00:00')).timestamp()


def _track(folder):
    from strata360.gps import track
    tp = config.track_path(folder, config.load(folder))
    if not tp: raise ValueError('there is no race track: add the .fit or .gpx first')
    return track.load(tp)


def clip_info(folder, clip):
    """(start epoch, duration s, osv path) of a clip, from its clip.json."""
    try: cj = json.load(open(os.path.join(config.race_dir(folder), 'clips', clip, 'clip.json')))
    except (OSError, ValueError): raise ValueError(f'no clip {clip}')
    return _epoch(cj['time']['start_utc']), float(cj['video']['source_frames']) / float(cj['video']['nominal_fps']), (cj.get('source_files') or {}).get('osv')


def section_of(rd, key):
    return next((s for s in SV.annotate(rd, {p: SV.load(rd, p) for p in SV.PROVIDERS}) if s['key'] == key), None)


def source_poly(folder, source, tr=None):
    """(poly, (t_lo, t_hi), extra) for a camera's source: a clip's part of the race track (the race track's fixes during the clip, with a few seconds each side to smooth from), or a street view section (a fix at each picture, the race time from where it is on the course).
    `extra` is the clip's (start, duration, osv) or the section."""
    rd = config.race_dir(folder); tr = tr if tr is not None else _track(folder)
    if source['kind'] == 'clip':
        t0, dur, osv = clip_info(folder, source['clip']); p = PC.poly(tr['lat'], tr['lon'], tr['t']); keep = (p['t'] >= t0 - 15) & (p['t'] <= t0 + dur + 15)
        if keep.sum() < 3: raise ValueError(f"the race track does not cover clip {source['clip']}")
        return dict(lat=p['lat'][keep], lon=p['lon'][keep], t=p['t'][keep]), (t0, t0 + dur), (t0, dur, osv)
    if source['kind'] == 'streetview':
        sec = section_of(rd, source['key'])
        if sec is None: raise ValueError('that street view section is not there any more')
        from strata360.edit import streetview_cam as CAM
        items = CAM.forward_items(sec); d, t = SV.track_dist(tr); ts = np.interp([it['km'] * 1000.0 for it in items], d, t)
        p = PC.poly([it['lat'] for it in items], [it['lon'] for it in items], ts)
        if len(p['t']) < 3: raise ValueError('the section has too few pictures')
        return p, (float(p['t'][0]), float(p['t'][-1])), sec
    raise ValueError(f"unknown source {source.get('kind')}")


def approach(p, lat, lon, bounds):
    """(t_pass, dist_m) of the closest approach of path `p` to (lat, lon) within the source's stretch `bounds`; ValueError when the click is too far from the path (`PC.MAX_OFF_PATH_M`)."""
    c = PC.closest(p, lat, lon, *bounds)
    if c is None: raise ValueError('the path has no stretch to aim from')
    if c['dist_m'] > PC.MAX_OFF_PATH_M: raise ValueError(f"that point is {c['dist_m']:.0f} m from the path: click nearer to it (within {PC.MAX_OFF_PATH_M:.0f} m)")
    return c['t'], c['dist_m']


def calibration(folder, source, p, bounds, extra):
    """For a clip: the offset of its frame's zero from the compass (PC.north_offset: the GPS course against the clip's own heading, once a second over the clip); 0 for a street view section (the pictures are aimed by compass)."""
    if source['kind'] != 'clip': return 0.0
    from strata360.analysis import views
    t0, dur, osv = extra; d = os.path.join(config.race_dir(folder), 'clips', source['clip'])
    try: hf = views.heading_fn(d, osv)
    except Exception: return 0.0
    ts = np.arange(0.0, dur, 1.0); pos = PC.positions(p, t0 + ts); ok = pos['speed'] > 1.0
    if not ok.any(): return 0.0
    return PC.north_offset(pos['course'][ok], [hf(float(t)) for t in ts[ok]])


def natural_s(cam, t0, t1, sec=None):
    """How long the shot plays when nothing says otherwise: a clip's, the time the runner took (real time); a street view section's, the road covered at SV_PLAY_MS (held to what the section can play)."""
    if cam['source']['kind'] == 'clip': return round(t1 - t0, 1)
    length = float(cam['before_m'] + cam['after_m']); hi = float(sec['max_s']) if sec else PC.MAX_S; return round(min(max(length / SV_PLAY_MS, PC.MIN_S), max(hi, PC.MIN_S)), 1)


def plan(folder, cam, seconds=None, tr=None):
    """The shot of camera `cam`: dict(t0, t1, seconds, source_seconds, samples, facts, north_offset, poly, extra). The window is `before_m` and `after_m` of path round the closest approach, held to the source; for a clip a `seconds` shorter than that trims it
    round the closest approach (the point stays in it), for a street view section `seconds` is the play length (the whole window is played in it)."""
    clip = cam['source']['kind'] == 'clip'; p, bounds, extra = source_poly(folder, cam['source'], tr); t0, t1 = PC.window(p, cam['t_pass'], cam['before_m'], cam['after_m'], *bounds)
    if clip and seconds: t0, t1 = PC.shrink(p, cam, t0, t1, float(seconds))
    sm = PC.samples(p, cam, t0, t1); play = round(t1 - t0, 1) if clip else (float(seconds) if seconds else natural_s(cam, t0, t1, extra))
    return dict(t0=t0, t1=t1, seconds=play, source_seconds=round(t1 - t0, 1), samples=sm, facts=PC.facts(sm), north_offset=calibration(folder, cam['source'], p, bounds, extra), poly=p, extra=extra)


def clip_path(sm, t0_clip, off):
    """The renderer's camera path for a clip shot (keyframes from the start of the window)."""
    return dict(ref='world', keyframes=PC.keyframes(sm, sm['t'][0], off))


def _writer(out, size, fps, crf, log):
    import subprocess
    from strata360.pipeline import guard
    W, H = size; cmd = ['ffmpeg', '-y', '-v', 'error', '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-s', f'{W}x{H}', '-r', str(fps), '-i', '-', '-c:v', 'libx264', '-crf', str(crf), '-pix_fmt', 'yuv420p', '-movflags', '+faststart', '-f', 'mp4', out + '.part.mp4']
    return guard.popen(cmd, stdin=subprocess.PIPE)


def _render_clip(folder, cam, pl, out, size, decode_w, crf, log):
    """The clip shot through the real renderer's projection (render/preview.py PreviewSource) from the clip's proxy."""
    from strata360.render import preview as PV
    clip = cam['source']['clip']; cs, _dur, _osv = pl['extra']
    if not PV.proxy_of(folder, clip): raise RuntimeError(f"clip {clip} has no proxy yet (the proxy stage makes the video the preview is cut from)")
    t0 = pl['t0'] - cs; T = pl['t1'] - pl['t0']; path = clip_path(pl['samples'], t0, pl['north_offset'])
    seg = dict(id='cam', clip=clip, clip_start_s=max(t0, 0.0), dur_s=T, synthetic=None, utc_start=PC._iso(pl['t0']))
    if t0 < 0: path['keyframes'] = [dict(k, t=round(k['t'] + t0, 3)) for k in path['keyframes']]                    # (before the clip starts the first frame is held)
    src = PV.PreviewSource(folder, [seg], {'cam': path}, size[0], size[1], decode_w); m = int(round(T * PV.FPS)); enc = _writer(out, size, PV.FPS, crf, log); n = 0
    try:
        for img in src.frames(0, 0, m):
            enc.stdin.write(np.ascontiguousarray(img).tobytes()); n += 1
            if n % 10 == 0 or n == m: log(f'rendering {n} of {m} frames')
        enc.stdin.close(); enc.wait()
    except BrokenPipeError: enc.wait()
    if enc.returncode: raise RuntimeError('ffmpeg failed to write the point camera video')
    os.replace(out + '.part.mp4', out); log(f"{cam['id']}: {n} frames of clip {clip} ({T:.1f} s) aimed at the point"); return dict(frames=n, fps=PV.FPS)


def _render_sv(folder, cam, pl, out, size, encode_size, crf, log, seconds, preview):
    """The street view shot: each output frame looks at the point from the interpolated camera position, blending the two pictures it falls between."""
    from strata360.edit import streetview_cam as CAM
    rd = config.race_dir(folder); sec = pl['extra']; hires = bool(sec.get('hires')) and sec['provider'] == 'google'
    if sec['provider'] == 'google': CAM.fetch_google_pano(rd, sec, road=SV.road_of(rd, sec), log=log, grid='hi' if hires else 'std')                 # (the 360 pictures, asked for only now)
    else: CAM.fetch(rd, sec, token=SV._key('MAPILLARY_TOKEN'), log=log, preview=preview)
    fps = 30; N = max(2, int(seconds * fps)); items = CAM.forward_items(sec); p = pl['poly']; ts = np.linspace(pl['t0'], pl['t1'], N); sm = PC.samples(p, cam, pl['t0'], pl['t1'], step=(pl['t1'] - pl['t0']) / (N - 1)); idx = np.interp(ts, p['t'], np.arange(len(items)))
    return CAM.render_point(rd, sec, idx, sm['bearing'], sm['pitch'], sm['fov'], out, road=SV.road_of(rd, sec), fps=fps, size=size, encode_size=encode_size, log=log, preview=preview, grid='hi' if hires else 'std')


def render_preview(folder, cam, out, log=print):
    """The small video to judge a shot by, written to `out`; returns its facts."""
    pl = plan(folder, cam); os.makedirs(os.path.dirname(out), exist_ok=True)
    if cam['source']['kind'] == 'clip': return _render_clip(folder, cam, pl, out, PREVIEW_SIZE, 1920, 23, log)
    return _render_sv(folder, cam, pl, out, (960, 540), None, 23, log, pl['seconds'], True)


def render(folder, cam, seconds, out, log=print):
    """The shot for the film: picture only, `seconds` long (a clip's shot is trimmed round the closest approach when shorter than its stretch)."""
    pl = plan(folder, cam, seconds); os.makedirs(os.path.dirname(out), exist_ok=True)
    if cam['source']['kind'] == 'clip': return _render_clip(folder, cam, pl, out, CLIP_SIZE, 3840, 17, log)
    return _render_sv(folder, cam, pl, out, (1920, 1080), tuple(int(x) for x in SY.STREETVIEW_SIZE.split('x')), 17, log, float(seconds), False)


def progress(lines, cam_source, google=False):
    """How far a preview being made has got, from the lines its job logged: {pct 0 to 100, phase, done, total}, or None before the first step. A street view shot fetches pictures first (SV.video_progress knows those steps); a clip's is all rendering."""
    if cam_source['kind'] == 'streetview': return SV.video_progress(lines, google)
    import re
    for l in reversed(lines):
        m = re.search(r'rendering (\d+) of (\d+)', l)
        if m: done, total = int(m.group(1)), max(int(m.group(2)), 1); return dict(pct=min(100, round(100 * done / total)), phase='rendering the video', done=done, total=total)
    return None


def preview_path(folder, cam):
    """Where a camera's preview video is kept: named by the camera's settings and source, so a changed camera gets a new one."""
    import hashlib
    h = hashlib.sha1(json.dumps([cam['source'], cam['lat'], cam['lon'], cam['height_m'], cam['before_m'], cam['after_m'], cam['fov_near'], cam['fov_far'], cam['smooth_s'], cam['t_pass'], PC.STEP_S, 1], sort_keys=True).encode()).hexdigest()[:12]
    return os.path.join(config.race_dir(folder), 'pointcams', f"{cam['id']}-{h}.mp4")


def cutins(folder, tr=None):
    """For the planner (edit/techniques.py `with_cams`): the point cameras on CLIPS that are offered as possible, each with its camera path over the whole stretch it covers in CLIP seconds (t, yaw in the clip's own frame, pitch, fov). A must camera is a shot of
    its own instead (`sync`), and a street view camera can only be a generated clip, so neither is here. A camera whose clip or track is not there is left out."""
    rd = config.race_dir(folder); out = []
    for cam in PC.load(rd)['cams']:
        if cam['source']['kind'] != 'clip' or cam.get('use') != 'possible': continue
        try: pl = plan(folder, cam, tr=tr)
        except (ValueError, RuntimeError, OSError): continue
        cs = pl['extra'][0]; sm = pl['samples']; yaw = np.degrees(np.unwrap(np.radians(sm['bearing'] - pl['north_offset'])))
        out.append(dict(id=cam['id'], clip=cam['source']['clip'], name=cam.get('name') or '', t0=float(sm['t'][0] - cs), t1=float(sm['t'][-1] - cs), t_pass=float(cam['t_pass'] - cs), t=[round(float(x), 3) for x in sm['t'] - cs], yaw=[round(float(x), 2) for x in yaw],
                        pitch=[round(float(x), 2) for x in sm['pitch']], fov=[round(float(x), 1) for x in sm['fov']], min_dist_m=pl['facts']['min_dist_m']))
    return out


def range_of(cam, pl):
    """(shortest, longest) seconds the planner may play the shot of plan `pl`: a clip's shot from MIN_S to the whole stretch (shorter trims round the point), a street view section's from MIN_S to what the section can play."""
    if cam['source']['kind'] == 'clip': return PC.MIN_S, max(PC.MIN_S, round(pl['source_seconds'], 1))
    return PC.MIN_S, max(PC.MIN_S, min(float(pl['extra']['max_s']), PC.MAX_S))


def range_s(folder, cam, tr=None): return range_of(cam, plan(folder, cam, tr=tr))


def geometry(pl, cam, sights=7):
    """What the map draws for a camera: `line` the camera's path over the shot ([lat, lon] about every second), `sights` the view from evenly spaced moments (where from, the compass bearing and the field of view, the distance to the point) and `pass` the place of the closest approach."""
    p, sm = pl['poly'], pl['samples']; n = max(int(round(pl['t1'] - pl['t0'])), 2) + 1; ts = np.linspace(pl['t0'], pl['t1'], n)
    line = [[round(float(la), 6), round(float(lo), 6)] for la, lo in zip(np.interp(ts, p['t'], p['lat']), np.interp(ts, p['t'], p['lon']))]; ks = np.unique(np.linspace(0, len(sm['t']) - 1, sights).round().astype(int))
    out = [dict(at=[round(float(np.interp(sm['t'][k], p['t'], p['lat'])), 6), round(float(np.interp(sm['t'][k], p['t'], p['lon'])), 6)], bearing=round(float(sm['bearing'][k]), 1), fov=round(float(sm['fov'][k]), 1), dist=round(float(sm['dist'][k]), 1), t=round(float(sm['t'][k]), 1)) for k in ks]
    return dict(line=line, sights=out, at=[round(float(np.interp(cam['t_pass'], p['t'], p['lat'])), 6), round(float(np.interp(cam['t_pass'], p['t'], p['lon'])), 6)])


def summary(folder, cam, tr=None):
    """Everything the page shows about a camera in one go: ok, then (when its source can give the shot) the facts, the lengths, the window and the geometry; else the reason."""
    try: pl = plan(folder, cam, tr=tr)
    except (ValueError, RuntimeError, OSError) as e: return dict(ok=False, error=str(e))
    lo, hi = range_of(cam, pl); return dict(ok=True, facts=pl['facts'], seconds=pl['seconds'], source_seconds=pl['source_seconds'], range=[lo, hi], window=[round(pl['t0'], 1), round(pl['t1'], 1)], north_offset=round(pl['north_offset'], 1), geometry=geometry(pl, cam))


def sync(folder, specs, log=print):
    """Make the clips for the plan's point camera entries (labels C1 ...); returns the clip documents made or kept. A camera that is gone, or whose source cannot give the shot, is reported and skipped (the plan then shows a card)."""
    rd = config.race_dir(folder); cams = {c['id']: c for c in PC.load(rd)['cams']}; docs = {c['id']: c for c in SY.load(folder)['clips']}; out = []
    for sp in specs:
        if not PC.is_camera_label(sp['clip']): continue
        cam = cams.get(str(sp['clip']).upper())
        if cam is None: log(f"{sp['clip']}: the point camera is not there any more"); continue
        try: lo, hi = range_s(folder, cam); pl = plan(folder, cam, float(sp['seconds']))
        except (ValueError, RuntimeError) as e: log(f"{sp['clip']}: {e}"); continue
        sec_s = round(min(max(float(sp['seconds']), lo), hi), 2); c = SY.make_pointcam(cam, sec_s, pl['t0'], pl['t1'], provider=pl['extra']['provider'] if cam['source']['kind'] == 'streetview' else None); old = docs.get(c['id']); path = os.path.join(rd, 'synthetic', c['id'] + '.mp4'); c['file'] = os.path.join('synthetic', c['id'] + '.mp4')
        if old and old.get('key') == c['key'] and os.path.exists(path): out.append(old); continue
        render(folder, cam, sec_s, path, log); c['status'] = 'ready'; out.append(SY.upsert(folder, c))
    return out
