"""Generated clips (edit/synthetic.py) rendered at whatever frame rate and size the caller needs: the same renderers for the preview, a still and the final film, with different parameters.

  gap_clip(folder, doc, fps, size)      the animated 2D map or 3D flyover object (overlay/mapclip.py, overlay/flyover.py) for a gap clip's document, ready to `overlay.mapclip.render`
  render(folder, doc, out, fps, size)   write the clip `doc` to `out` at `fps` and `size` from its original sources (the track and map tiles, the photo, the 360 pictures); returns True when it could, False for a kind that is cut from footage
  for_film(folder, doc, fps, size)      the path of the clip at the film's own rate and size, made once and kept in <race dir>/synthetic/film/ (named by the clip's key, rate and size)"""
import os

from strata360.edit import synthetic as SY
from strata360.pipeline import config

FILM_DIR = 'film'


def _iso_epoch(x):
    import datetime as dt
    d = dt.datetime.fromisoformat(str(x).replace('Z', '+00:00')); return (d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)).timestamp()


def gap_clip(folder, clip, fps=None, size=None):
    """The map or flyover object for a gap clip document, at `fps` (default the document's) and `size` (default the document's, else 1920x1080). The caller closes it if it has `close`."""
    from strata360.gps import track
    from strata360.overlay import mapclip as MC
    from strata360.overlay.series import Series
    from strata360.overlay.tiles import Tiles
    cfg = config.load(folder); tp = config.track_path(folder, cfg)
    if not tp: raise ValueError('no race track: add the .fit or .gpx first')
    series = Series(track.load(tp)); tz = cfg.get('timezone', 'Europe/Brussels'); t0, t1 = _iso_epoch(clip['t0']), _iso_epoch(clip['t1'])
    w, h = size or tuple(int(x) for x in (clip.get('size') or '1920x1080').split('x')); st = clip.get('style') or {}; fps = float(fps or clip['fps'])
    try:
        from strata360.gps import tracks as TKS
        places = TKS.overlay_places(config.race_dir(folder))                                                                         # the start, finish and checkpoints, as on the overlay's maps
    except Exception as e:                                                                                                         # (the map then has none, said loudly)
        print(f'gap clip: no start, finish or checkpoints on the map: {type(e).__name__}: {e}'); places = None
    if clip['kind'] == 'flyover':
        from strata360.overlay import flyover as FO
        try: return FO.FlyoverClip(series, t0, t1, clip['seconds'], fps=fps, size=(w, h), imagery=st.get('imagery') or FO.DEFAULT_IMAGERY, tz=tz, sharp=st.get('sharp', True), mbgl=FO.find_mbgl(), places=places)
        except FO.FlyoverError as e: raise ValueError(str(e))
    return MC.MapClip(series, t0, t1, clip['seconds'], fps=fps, size=(w, h), tiles=Tiles(st.get('map') or MC.DEFAULT_STYLE), tz=tz, places=places)


def bitrate_for(w, h): return f'{max(12, round(12 * w * h / (1920 * 1080)))}M'          # (the clip is an intermediate the film re-encodes: generous)


def render(folder, doc, out, fps=None, size=None, log=print, crf=14):
    """Write the generated clip `doc` to `out` at `fps` and `size` (default: the clip's own), from its original sources. Returns True when it was made here; False for a kind the final renderer cuts from footage (a point camera on a clip). Raises ValueError/RuntimeError when it cannot be made."""
    kind = doc['kind']; fps = float(fps or doc['fps']); rd = config.race_dir(folder); last = [0]
    def show(done, total):
        if done - last[0] >= max(1, total // 20) or done == total: last[0] = done; log(f"  {doc['id']}: {done}/{total} frames")
    if kind in ('map', 'flyover'):
        from strata360.overlay import mapclip as MC
        mc = gap_clip(folder, doc, fps, size)
        try: MC.render(mc, out, show, bitrate=bitrate_for(mc.W * 1.5, mc.H * 1.5))
        finally:
            if hasattr(mc, 'close'): mc.close()
        return True
    if kind == 'photo':
        from strata360 import photos as PH
        from strata360.edit import photo_clip as PC
        e = next((p for p in PH.load(rd)['photos'] if p['id'] == str(doc['photo']).lower() or p['id'].upper() == doc['id']), None)
        if e is None: raise ValueError(f"the photo of {doc['id']} is not in the project any more")
        PC.render(folder, e, doc['seconds'], PH.motion_of(e), out, log, fps=fps, out_size=size, crf=crf); return True
    if kind == 'streetview':
        from strata360 import streetview as SV
        from strata360.edit import streetview_clip as SC
        sec = next((s for s in SV.chosen(rd, SC.docs_of(rd)) if s['label'] == doc['id'].upper()), None)
        if sec is None: raise ValueError(f"the street view section of {doc['id']} is not chosen any more")
        SC.render(folder, sec, doc['seconds'], out, log, fps=fps, size=size); return True
    if kind == 'pointcam':
        from strata360.edit import pointcam as PCM, pointcam_clip as PK
        cam = next((c for c in PCM.load(rd)['cams'] if c['id'] == doc['id']), None)
        if cam is None: raise ValueError(f"the point camera {doc['id']} is not there any more")
        if cam['source']['kind'] == 'clip': return False
        PK.render(folder, cam, doc['seconds'], out, log, fps=fps, size=size); return True
    raise ValueError(f'unknown kind {kind}')


def film_path(folder, doc, fps, size):
    return os.path.join(config.race_dir(folder), 'synthetic', FILM_DIR, f"{doc['id']}-{doc.get('key', '')}-{float(fps):g}fps-{size[0]}x{size[1]}.mp4")


def for_film(folder, doc, fps, size, log=print):
    """The clip at the film's own `fps` and `size`, rendered from its original sources the first time and kept. None when the kind is cut from footage instead."""
    path = film_path(folder, doc, fps, size)
    if os.path.exists(path): return path
    os.makedirs(os.path.dirname(path), exist_ok=True); tmp = path[:-4] + '.part.mp4'
    if not render(folder, doc, tmp, fps, size, log): return None
    os.replace(tmp, path); return path
