"""Where the snow and the water are: bounding boxes for the big things YOLOE cannot find (it fires on any white or wet picture), from the labelling model on wide views.

The scenes stage already says, per picture, whether snow lies on the ground (`ground_snow`) and whether a river, stream, lake, sea or waterfall is in view (`water`; a puddle does not count). The regions step asks the model for boxes ONLY for what the
scene labels of that moment say is there, and only about that: asked about both on every frame it invents snow on a wet road and water on a wet field (checked on 8 frames; the scene labels separated every false alarm). A moment's wide
views (100 degrees, six around the horizon and a little down, cut from the original lens frames) go to the model, its boxes are turned into directions in the world-locked frame (a polygon of the four corners, a centre and a size), and
the boxes of all moments are listed in `regions` of objects.json."""
import json
import math
import re

import numpy as np

from strata360.analysis import views as V

FOV, PX, PITCH = 100.0, 1024, -15.0
YAWS = tuple(range(0, 360, 60))
GAP_S = 20.0                              # at most one moment in this many seconds is looked at: the boxes are of big things that stay where they are
WATER = ('river', 'stream', 'lake', 'sea', 'waterfall')
ASK = dict(snow='snow lying on the ground', water='water: a river, stream, lake, sea or waterfall (not a puddle)')


def kinds_at(scenes_doc, t, near_s=6.0):
    """{'snow', 'water'} the scene labels give for the pictures within `near_s` seconds of clip time `t` (front and rear)."""
    out = set()
    for it in (scenes_doc or {}).get('items') or []:
        if not it.get('ok') or abs(it.get('t_s', 1e9) - t) > near_s: continue
        if it.get('ground_snow') is True: out.add('snow')
        if it.get('water') in WATER: out.add('water')
    return out


def plan(scenes_doc, times, gap_s=GAP_S):
    """[(t, kinds)]: the moments to look at for regions, at most one in `gap_s` seconds, each with what the scene labels there say is present."""
    out, last = [], None
    for t in times:
        k = kinds_at(scenes_doc, t)
        if k and (last is None or t - last >= gap_s): out.append((t, sorted(k))); last = t
    return out


def question(kinds):
    parts = ' and '.join(f'({i}) {ASK[k]}' for i, k in enumerate(kinds, 1)); labels = ' or '.join(f'"{k}"' for k in kinds)
    return (f'Find {parts} in this image. Output a JSON list with one entry for each separate area: {{"label": {labels}, "bbox_2d": [x1, y1, x2, y2]}} with the box around the whole area. Output [] if there is none. Output only the JSON.')


def parse(text, kinds):
    """[(label, [x1, y1, x2, y2] in 0..1)] from the model's answer; boxes of a kind that was not asked about, or that are not four numbers, are dropped."""
    m = re.search(r'\[.*\]', str(text), re.S)
    try: items = json.loads(m.group(0)) if m else []
    except ValueError: return []
    out = []
    for it in items if isinstance(items, list) else []:
        try: b = [min(max(float(z) / 1000.0, 0.0), 1.0) for z in it['bbox_2d']]; lab = it['label']
        except (KeyError, TypeError, ValueError): continue
        if lab in kinds and len(b) == 4 and b[2] > b[0] and b[3] > b[1]: out.append((lab, b))
    return out


def to_world(box, lon, lat, fov=FOV, px=PX):
    """A box (0..1 in the picture) of a view centred on (lon, lat) degrees as {lon, lat, w_deg, h_deg, polygon}: the centre and size in the world-locked frame and its four corners."""
    rays = V.crop_rays(math.radians(lon), math.radians(lat), fov, px)
    def at(x, y):
        d = rays[min(int(y * px), px - 1), min(int(x * px), px - 1)]; return math.degrees(math.atan2(d[0], d[1])), math.degrees(math.asin(float(np.clip(d[2], -1, 1))))
    cx, cy = at((box[0] + box[2]) / 2, (box[1] + box[3]) / 2); poly = [at(box[0], box[1]), at(box[2], box[1]), at(box[2], box[3]), at(box[0], box[3])]
    f = (px / 2) / math.tan(math.radians(fov / 2)); w = math.degrees((box[2] - box[0]) * px / f); h = math.degrees((box[3] - box[1]) * px / f)
    return dict(lon=round(cx, 1), lat=round(cy, 1), w_deg=round(w, 1), h_deg=round(h, 1), polygon=[[round(a, 1), round(b, 1)] for a, b in poly])
