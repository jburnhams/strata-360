"""`objects` stage: the things a runner passes (animals, signs, buildings, vehicles, structures ...) with a direction, found by a fast box detector and named by the local vision model.

Per moment (analysis/sampling.py: when the runner has moved or the scene changed), 26 flat tiles of 60 degrees are cut from the original lens frames (CropRenderer) and given to YOLOE (analysis/objects_det.py, in `.venv-vision`):
a text model with the clip's wordlist (analysis/vocab.py: `always` plus the categories the scene labels chose) and a prompt-free model whose boxes the text model did not name are the "other" candidates. People and
worn gear are named classes so they are never sent on; boxes in the wearer's own direction are dropped. Each object is kept once (it stays at the same direction in the world-locked frame; `Memory`), then routed by the
word statistics (vocab.StatsBook.route): a trusted word keeps the detector's name, anything else is cropped (re-rendered at lens resolution) and labelled by Qwen (analysis/objects_vlm.py). What the labelling model said is
recorded against the detector's word, so words earn trust (or lose their place) over time.

Not sent at all: a clip in the dark (sun below -12 degrees and a dim exposure), a moment whose exposure is black, boxes too small for any lens to resolve, ground/sky/body-part labels (the stop-list) and big scenery
words (tree, snow, river ...: counted per clip under `areas`, not labelled one by one). `detect` and `label` are arguments so the logic runs without a model in the tests."""
import json
import math
import os
import random
import shutil
import subprocess
import tempfile
import time

import numpy as np

from strata360.analysis import vocab as VOC, views as V

SCHEMA_VERSION = 1
TFOV, TPX = 60.0, 1024
PPD = TPX / (2 * math.degrees(math.tan(math.radians(TFOV / 2))))                      # pixels per degree in a tile, about 15
RINGS = [(-90, [0.0]), (-55, list(np.arange(0, 360, 60.0))), (-20, list(np.linspace(0, 360, 7, endpoint=False))), (15, list(np.linspace(0, 360, 7, endpoint=False))), (50, list(np.linspace(0, 360, 5, endpoint=False)))]
TILES = [(lat0, lon0) for lat0, lons in RINGS for lon0 in lons]                       # (latitude, longitude) of each tile's centre in degrees: 26 tiles cover the sphere
WORN = ('person', 'backpack', 'helmet', 'hat', 'glove', 'jacket')
PERSONISH = ('person', 'hat', 'helmet', 'backpack', 'glove', 'glass', 'jacket', 'hand', 'face', 'man', 'woman', 'runner', 'head', 'hair')
AREAS = ('tree', 'bush', 'grass', 'rock', 'path', 'road', 'field', 'forest', 'snow', 'river', 'water', 'mountain', 'hill')       # real but big or everywhere: counted per clip, not labelled one by one
NAMED_CONF, LOW_CONF = 0.25, 0.10         # the detector's confidence to keep a named box; animals (small, easily missed) are kept from LOW_CONF
PF_CONF = 0.30                            # ... and a prompt-free box
MIN_SIDE_PX, MAX_AREA = 8, 0.25           # a box shorter than this on its short side, or filling more than this share of a tile, is not an object
CROP_MARGIN, CROP_FOV = 1.8, (10.0, 60.0)
TINY_DEG = V.CROP_WANT_PX / 3 / V.NATIVE_PPD       # below this even the lens frame gives the box fewer than a third of the pixels the labelling model wants
DARK_SUN, DARK_EXPOSURE, BLACK_FRAME = -12.0, 0.2, 0.02
WEARER_NEAR_S = 1.5
SAME_OBJECT_DEG = 2.0                     # two boxes closer than this (or 0.6 of their size) in the world frame are the same object
BATCH = 8                                 # moments per detector call (their tile pictures are on disk meanwhile)


def angdist(a, b):
    """The angle in degrees between two (lon, lat) directions in degrees."""
    la, lb, pa, pb = math.radians(a[0]), math.radians(b[0]), math.radians(a[1]), math.radians(b[1])
    return math.degrees(math.acos(float(np.clip(math.sin(pa) * math.sin(pb) + math.cos(pa) * math.cos(pb) * math.cos(la - lb), -1, 1))))


def inside(a, b):
    """The share of box a that lies inside box b."""
    return max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1])) / max(1, (a[2] - a[0]) * (a[3] - a[1]))


_rays = {}


def tile_rays(lat0, lon0, px=TPX):
    k = (lat0, lon0, px)
    if k not in _rays: _rays[k] = V.crop_rays(math.radians(lon0), math.radians(lat0), TFOV, px)
    return _rays[k]


def direction(tile, box, px=TPX):
    """(lon, lat) in degrees of the middle of a box in a tile picture."""
    rays = tile_rays(*TILES[tile], px); d = rays[min(int((box[1] + box[3]) / 2), px - 1), min(int((box[0] + box[2]) / 2), px - 1)]
    return math.degrees(math.atan2(d[0], d[1])), math.degrees(math.asin(float(np.clip(d[2], -1, 1))))


# ---- gates: what is not worth looking at ---------------------------------------------------------------------------------------------------------------------------------------
def clip_is_dark(sun, exposure):
    """Why a whole clip is skipped (a reason), or None: the sun below -12 degrees at its middle and a dim exposure (a lit indoor aid station at night passes: its exposure is high)."""
    if not sun or not sun.get('covered') or sun.get('elevation_deg') is None or sun['elevation_deg'] >= DARK_SUN: return None
    m = [f['sphere']['mean_lin'] for f in (exposure or {}).get('frames') or [] if f.get('sphere', {}).get('mean_lin') is not None]
    return f"night: the sun is {sun['elevation_deg']:.0f} degrees and the exposure is dim" if m and float(np.median(m)) < DARK_EXPOSURE else None


def black_at(exposure, t):
    """Whether the picture at clip time `t` is black (the lens covered, the camera just started), from exposure.json."""
    fr = [f for f in (exposure or {}).get('frames') or [] if f.get('sphere', {}).get('mean_lin') is not None]
    if not fr: return False
    f = min(fr, key=lambda f: abs(f['t_s'] - t)); return abs(f['t_s'] - t) <= 2.0 and f['sphere']['mean_lin'] < BLACK_FRAME


def wearer_dirs(focus, t):
    """[(lon, lat, size_deg)] of where the wearer is around clip time `t`, from focus.json's samples."""
    out = []
    for s in focus or []:
        if abs(s['t'] - t) <= WEARER_NEAR_S: out.append((s['yaw'] if s['yaw'] <= 180 else s['yaw'] - 360, s['pitch'], float(s.get('height') or 40)))
    return out


# ---- candidates from one tile ------------------------------------------------------------------------------------------------------------------------------------------------------
def tile_candidates(tile, named, pf, low_words=()):
    """(candidates, people) from the detector's output for one tile. `named` and `pf` are [(label, conf, [x0, y0, x1, y1])]. A candidate is {kind: 'named'|'other', yoloe, conf, lon, lat, deg} for a text-model box of a
    thing (not worn gear, not a big scenery word) or a prompt-free box nothing named; `people` are the worn-gear/person boxes {lon, lat, deg}."""
    def ok(b): w, h = b[2] - b[0], b[3] - b[1]; return min(w, h) >= MIN_SIDE_PX and w * h <= MAX_AREA * TPX * TPX
    cover = [n for n in named if n[1] >= NAMED_CONF and ok(n[2])]; people = []; out = []                # a box filling the tile (a house, a hillside) does not hide the small things in front of it
    for lab, cf, b in named:
        if lab in WORN and cf >= NAMED_CONF and ok(b): lo, la = direction(tile, b); people.append(dict(lon=lo, lat=la, deg=max(b[2] - b[0], b[3] - b[1]) / PPD))
    for lab, cf, b in named:
        if lab in WORN or lab in AREAS or not ok(b) or cf < (LOW_CONF if lab in low_words else NAMED_CONF): continue
        lo, la = direction(tile, b); out.append(dict(kind='named', yoloe=lab, conf=cf, lon=lo, lat=la, deg=max(b[2] - b[0], b[3] - b[1]) / PPD))
    for lab, cf, b in pf:
        if cf < PF_CONF or any(k in lab.lower() for k in PERSONISH) or not ok(b) or any(inside(b, n[2]) >= 0.5 for n in cover): continue
        lo, la = direction(tile, b); out.append(dict(kind='other', yoloe=lab, conf=cf, lon=lo, lat=la, deg=max(b[2] - b[0], b[3] - b[1]) / PPD))
    return out, people


def areas_of(named):
    """{word: highest confidence} of the big scenery words the text model found in a tile."""
    out = {}
    for lab, cf, b in named:
        if lab in AREAS and cf >= NAMED_CONF: out[lab] = max(out.get(lab, 0.0), cf)
    return out


def merge_moment(cands, people, wearer):
    """One moment's candidates from all its tiles: the same thing seen in neighbouring tiles once (the most confident), and those in the wearer's direction (or on a person) marked `wearer`."""
    kept = []
    for c in sorted(cands, key=lambda c: -c['conf']):
        if any(angdist((c['lon'], c['lat']), (k['lon'], k['lat'])) < max(1.5, 0.4 * max(c['deg'], k['deg'])) for k in kept): continue
        kept.append(c)
    for c in kept:
        c['wearer'] = any(angdist((c['lon'], c['lat']), (lo, la)) < max(h / 2, 12) + 8 for lo, la, h in wearer) or any(angdist((c['lon'], c['lat']), (p['lon'], p['lat'])) < p['deg'] * 0.6 for p in people)
    return kept


class Memory:
    """The objects found so far in a clip. The picture is world-locked, so a static thing stays at the same direction: a candidate near a known object of a similar size is that object, seen again."""
    def __init__(self): self.objects = []

    def match(self, c):
        best = None
        for o in self.objects:
            d = angdist((c['lon'], c['lat']), (o['lon'], o['lat']))
            if d < max(SAME_OBJECT_DEG, 0.6 * max(c['deg'], o['deg'])) and 1 / 3 <= c['deg'] / max(o['deg'], 1e-6) <= 3 and (best is None or d < best[0]): best = (d, o)
        return best[1] if best else None

    def see(self, c, t):
        """Add a candidate seen at clip time `t`: (object, is_new)."""
        o = self.match(c)
        if o:
            o['seen'].append(round(t, 2))
            if c['conf'] > o['conf'] and c['kind'] == o['kind']: o.update(conf=c['conf'], lon=c['lon'], lat=c['lat'], deg=c['deg'], yoloe=c['yoloe'], best_t=round(t, 2))
            return o, False
        o = dict(id=len(self.objects), kind=c['kind'], yoloe=c['yoloe'], conf=round(c['conf'], 3), lon=c['lon'], lat=c['lat'], deg=c['deg'], seen=[round(t, 2)], best_t=round(t, 2)); self.objects.append(o); return o, True


def crop_fov(deg):
    return float(np.clip(deg * CROP_MARGIN, *CROP_FOV))


# ---- the models (subprocesses in .venv-vision) -----------------------------------------------------------------------------------------------------------------------------------
def _env():
    src = os.path.join(os.path.dirname(__file__), '..', '..'); extra = os.environ.get('STRATA_VISION_EXTRA', '')
    return {**os.environ, 'PYTHONPATH': os.pathsep.join(p for p in (src, extra) if p), 'PYTHONWARNINGS': 'ignore'}


def _py():
    return os.environ.get('STRATA_VISION_PYTHON') or os.path.join(os.path.dirname(__file__), '..', '..', '..', '.venv-vision', 'bin', 'python')


def run_detector(images, words, out, models=None):
    """YOLOE over every tile picture in `images`: {file: {named: [[label, conf, box]], pf: [...]}}."""
    wf = os.path.join(images, 'words.json'); json.dump(words, open(wf, 'w'))
    subprocess.run([_py(), '-m', 'strata360.analysis.objects_det', images, out, '--words', wf] + (['--weights', models] if models else []), check=True, env=_env(), stdout=subprocess.PIPE)
    return json.load(open(out))


def run_labeller(images, out, models=None):
    """The labelling model over every crop in `images`: {'model': ..., 'labels': {file: text}}."""
    subprocess.run([_py(), '-m', 'strata360.analysis.objects_vlm', images, out] + (['--model', models] if models else []), check=True, env=_env(), stdout=subprocess.PIPE)
    return json.load(open(out))


# ---- the stage ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def categories_of(scenes_doc, vocab):
    """The wordlist categories of a clip: both directions' scene labels through the plain rules (the stage does not call a model for this; `vocab categorise` does with one)."""
    out = []
    for blk in VOC.blocks_of(scenes_doc).values():
        for c in VOC.rule_categories(blk, vocab):
            if c not in out: out.append(c)
    return out


def analyse(osv, work_dir, times, words, *, stats, vocab, categories=(), sun=None, exposure=None, focus=None, clip='', detect=run_detector, label=run_labeller, renderer=None, crops_to=None, rng=None, batch=BATCH, log=print):
    """The objects of a clip at the moments `times` (clip seconds): the document written as objects.json. `stats` is the StatsBook the routing reads; the numbers of this clip's own outcomes are in the document's `stats`
    (the project's book is rebuilt from the clips, vocab.collect, so parallel clips never write the same file). `crops_to` is a folder to keep a small picture of each object that was labelled."""
    t0 = time.time(); doc = dict(schema=SCHEMA_VERSION, clip=clip, words=list(words), categories=list(categories), moments=len(times), seconds=0.0)
    why = clip_is_dark(sun, exposure)
    if why: return dict(doc, skipped=why, objects=[], areas={}, counts={}, stats=VOC.StatsBook().to_json())
    import cv2
    cr = renderer or V.CropRenderer(osv); mem = Memory(); areas = {}; counts = dict(black=0, tiles=0, wearer=0, tiny=0); tmp = tempfile.mkdtemp(prefix='s360obj_', dir=work_dir); crops = os.path.join(tmp, 'crops'); os.makedirs(crops)
    low = {w for c in ('wildlife', 'farm_rural') for w in vocab['categories'].get(c, {}).get('words', [])}; rng = rng or random.Random(0); todo = []
    try:
        use = [t for t in times if not black_at(exposure, t)]; counts['black'] = len(times) - len(use)
        for i in range(0, len(use), batch):
            part = use[i:i + batch]; d = os.path.join(tmp, f'tiles{i}'); os.makedirs(d)
            for m, t in enumerate(part):
                for k, (lat0, lon0) in enumerate(TILES): cv2.imwrite(os.path.join(d, f'm{m:03d}_t{k:02d}.jpg'), cr.crop(t, math.radians(lon0), math.radians(lat0), TFOV, TPX)[:, :, ::-1], [cv2.IMWRITE_JPEG_QUALITY, 92])
            det = detect(d, list(words), os.path.join(d, 'det.json')); files = det['files'] if 'files' in det else det
            for m, t in enumerate(part):
                cands, people = [], []
                for k in range(len(TILES)):
                    r = files.get(f'm{m:03d}_t{k:02d}.jpg') or {}; named = [tuple(x) for x in r.get('named', [])]; pf = [tuple(x) for x in r.get('pf', [])]; counts['tiles'] += 1
                    c, p = tile_candidates(k, named, pf, low); cands += c; people += p
                    for w, cf in areas_of(named).items(): a = areas.setdefault(w, dict(boxes=0, max_conf=0.0)); a['boxes'] += 1; a['max_conf'] = max(a['max_conf'], round(cf, 3))
                for c in merge_moment(cands, people, wearer_dirs(focus, t)):
                    if c['wearer']: counts['wearer'] += 1; continue
                    if c['deg'] < TINY_DEG: counts['tiny'] += 1; continue
                    o, new = mem.see(c, t)
                    if not new: continue
                    route = stats.route(o['yoloe'], o['conf'], vocab, rng) if o['kind'] == 'named' else 'label'; o['route'] = route
                    if route != 'accept':
                        name = f"o{o['id']:03d}.jpg"; cv2.imwrite(os.path.join(crops, name), cr.crop(t, math.radians(o['lon']), math.radians(o['lat']), crop_fov(o['deg']), V.CROP_PX)[:, :, ::-1], [cv2.IMWRITE_JPEG_QUALITY, 92]); todo.append(o['id'])
            shutil.rmtree(d, ignore_errors=True)
            log(f'objects: moments {min(i + batch, len(use))}/{len(use)}, {len(mem.objects)} objects so far')
        secs = 0.0; model = None; labels = {}
        if todo:
            r = label(crops, os.path.join(tmp, 'labels.json')); labels = r['labels']; model = r.get('model'); secs = r.get('seconds', 0.0)
        book = VOC.StatsBook()
        for o in mem.objects:
            lab = labels.get(f"o{o['id']:03d}.jpg"); o['lon'], o['lat'], o['deg'] = round(o['lon'], 1), round(o['lat'], 1), round(o['deg'], 1)
            if o['route'] == 'accept': o.update(label=o['yoloe'], source='detector'); continue
            o.update(label=lab, source='vlm'); kind = VOC.kind_of_label(lab, vocab) if lab else 'stop'; word = VOC.normalise_label(lab, vocab) if lab else ''
            if o['kind'] == 'named': book.record_named(o['yoloe'], lab or 'unclear', vocab, categories)
            elif kind == 'feature' and word: book.record_leftover(lab, clip, vocab)
            o['word'] = word if kind != 'stop' else None; o['stop'] = kind == 'stop'
            if crops_to and kind != 'stop': os.makedirs(crops_to, exist_ok=True); shutil.copy(os.path.join(crops, f"o{o['id']:03d}.jpg"), os.path.join(crops_to, f"o{o['id']:03d}.jpg"))
        for c in categories: book.use_category(c)
        for o in mem.objects: o['word'] = o.get('word') or (o['yoloe'] if o['source'] == 'detector' else None)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return dict(doc, model=model, seconds=round(time.time() - t0, 1), seconds_model=secs, objects=[o for o in mem.objects if not o.get('stop')], dropped_by_stoplist=sum(1 for o in mem.objects if o.get('stop')), areas=areas, counts=counts, stats=book.to_json())
