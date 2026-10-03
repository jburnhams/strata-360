"""A chosen street view section as a clip of the film (edit/synthetic.py kind `streetview`): the steady virtual camera (edit/streetview_cam.py) along the road, rendered to a 4K video of exactly the length the plan gives it, which the film plays like
any generated clip (picture only; the overlay goes on top, running through the race minutes the section covers).

`sync(folder, specs)` makes synthetic.json and the videos match the plan's street view clips (`specs` are the plan's `synthetic` entries for labels such as V2): a clip whose section, length and camera are unchanged is left as it is; the others are made again."""
import os

import numpy as np

from strata360 import streetview as SV
from strata360.edit import streetview_cam as CAM, synthetic as SY
from strata360.pipeline import config


def is_streetview_label(label): return str(label).upper().startswith('V') and str(label)[1:].isdigit()


def docs_of(rd): return {p: SV.load(rd, p) for p in SV.PROVIDERS}


def race_span(folder, sec):
    """(t0, t1) epoch seconds the runner took to cover the section, from the race track; None when there is no track."""
    from strata360.gps import track
    cfg = config.load(folder); tp = config.track_path(folder, cfg)
    if not tp: return None
    d, t = SV.track_dist(track.load(tp)); return float(np.interp(sec['km0'] * 1000, d, t)), float(np.interp(sec['km1'] * 1000, d, t))


def render(folder, sec, seconds, path, log=print):
    rd = config.race_dir(folder)
    CAM.fetch(rd, sec, token=SV._key('MAPILLARY_TOKEN'), log=log)
    os.makedirs(os.path.dirname(path), exist_ok=True); return CAM.render(rd, sec, seconds, path, road=SV.road_of(rd, sec), encode_size=tuple(int(x) for x in SY.STREETVIEW_SIZE.split('x')), log=log)


def sync(folder, specs, log=print):
    """Make the clips for the plan's street view entries; returns the clip documents made or kept. A section that is no longer chosen is reported and skipped (the plan then shows a card for it)."""
    rd = config.race_dir(folder); chosen = {s['label']: s for s in SV.chosen(rd, docs_of(rd))}; docs = {c['id']: c for c in SY.load(folder)['clips']}; out = []
    for sp in specs:
        if not is_streetview_label(sp['clip']): continue
        sec = chosen.get(str(sp['clip']).upper())
        if sec is None: log(f"{sp['clip']}: the section is not chosen (or not found) any more"); continue
        span = race_span(folder, sec)
        if span is None: log(f"{sp['clip']}: there is no race track to place it on"); continue
        sec_s = round(min(max(float(sp['seconds']), sec['min_s']), sec['max_s']), 2); c = SY.make_streetview(sec, sec_s, *span); old = docs.get(c['id']); path = os.path.join(rd, 'synthetic', c['id'] + '.mp4'); c['file'] = os.path.join('synthetic', c['id'] + '.mp4')
        if old and old.get('key') == c['key'] and os.path.exists(path): out.append(old); continue
        render(folder, sec, sec_s, path, log); c['status'] = 'ready'; out.append(SY.upsert(folder, c))
    return out
