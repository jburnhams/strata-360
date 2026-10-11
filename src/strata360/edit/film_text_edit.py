"""Editing the film's word-art cards by hand (the page under the film preview): list, save (edit or create), delete, and the pictures of a card.

The cards are the `cards` of <project>/strata360/film_text.json (edit/film_text.py makes them with the local models; the film's renders draw them, render/captions.py `Cards`). Each is
  {id, type, t (film second it starts), dur_s, lines [{role, text}], spec (render/titles.py: elements, timing), ...what the models noted (score, blocking, shot, why)}.
A card made here has an id that starts with `u`. A save keeps whatever the card already had and replaces its time, length and elements (each one made safe by title_design.normalize_element, so a bad value is a safe one, never a crash).
The pictures: `still` is the card drawn on the frame of the film at its moment (the preview's text-free `base.mp4` when the preview has one, else its stream, which already shows the saved cards), `text` is the card alone on a checkered grey; both are PNG and kept
beside the project (`film_text_stills/`, named by what they show, so a changed card makes a new picture and nothing is drawn twice)."""
import hashlib, json, os, subprocess, time
import numpy as np

from strata360.pipeline import config

FPS = 25.0                                   # the preview's rate: the cards are drawn by film frame
MIN_DUR, MAX_DUR, MAX_ELEMENTS = 0.8, 20.0, 8
SIZE = (960, 540)                            # what the frames are made at (the models see the same)


class Invalid(ValueError):
    """What is wrong with a card that was sent: shown to the person as it is."""


def _file(folder): return os.path.join(config.race_dir(folder), 'film_text.json')


def load(folder, plan=None):
    """The film_text.json document (an empty one when there is none, for the plan's key), every card with an id."""
    try: doc = json.load(open(_file(folder)))
    except (OSError, ValueError): doc = None
    if not isinstance(doc, dict) or not isinstance(doc.get('cards'), list):
        from strata360.render import preview as PVW
        doc = dict(schema=1, plan_key=PVW.plan_key(folder, plan) if plan else None, generated=time.strftime('%Y-%m-%dT%H:%M:%S'), seconds=0.0, preview=None, cards=[])
    used = {c['id'] for c in doc['cards'] if c.get('id')}
    for i, c in enumerate(doc['cards']):
        if not c.get('id'):
            n = i
            while f'c{n}' in used: n += 1
            c['id'] = f'c{n}'; used.add(c['id'])
    return doc


def _write(folder, doc):
    doc['edited'] = round(time.time(), 3); doc['cards'].sort(key=lambda c: c['t']); p = _file(folder); os.makedirs(os.path.dirname(p), exist_ok=True); tmp = f'{p}.{os.getpid()}.tmp'; json.dump(doc, open(tmp, 'w'), indent=1); os.replace(tmp, p)


def public(card):
    """A card as the page needs it."""
    spec = card.get('spec') or {}
    return dict(id=card['id'], type=card.get('type') or 'note', t=card['t'], dur_s=card['dur_s'], lines=card.get('lines') or [], elements=spec.get('elements') or [], start_s=(spec.get('timing') or {}).get('start_s', 0.0), user=str(card['id']).startswith('u'),
                score=card.get('score'), worth_why=card.get('worth_why') or '', blocking=card.get('blocking'), shot=card.get('shot'), why=spec.get('why') or '', changes=card.get('changes') or [])


def listing(folder, plan=None):
    """The state for the page: the cards in film order and the choices the editor offers."""
    from strata360.render import preview as PVW, titles as TT
    doc = load(folder, plan); key = PVW.plan_key(folder, plan) if plan else None
    return dict(cards=[public(c) for c in sorted(doc['cards'], key=lambda c: c['t'])], stale=bool(plan and doc.get('plan_key') not in (None, key)), edited=doc.get('edited') or 0.0, length_s=float((plan or {}).get('film', {}).get('length_s') or 0.0),
                fonts=[dict(id=k, note=v[1]) for k, v in TT.FONTS.items()], presets_in=list(TT.PRESETS_IN), presets_out=list(TT.PRESETS_OUT), has_preview=base_source(folder, plan) is not None)


def default_elements(texts):
    """The elements of a card made from plain words: the first line large and loud, the rest smaller beneath it."""
    from strata360.edit import title_design as TD
    out = []; ts = [str(t).strip() for t in texts if str(t).strip()]
    for i, t in enumerate(ts[:MAX_ELEMENTS]):
        big = i == 0; out.append(TD.normalize_element(dict(text=t, font='anton' if big else 'barlow_cond_bold', size=0.17 if big else 0.07, x=0.5, y=0.42 + 0.14 * i, fill=dict(type='solid', c1='#ffffff'), stroke=dict(w=0.006 if big else 0.004, color='#101010'),
                                                              shadow=dict(blur=0.012, opacity=0.6, dy=0.004), **{'in': 'rise' if big else 'fade', 'out': 'fade'}, delay=0.15 * i, in_s=0.5)))
    return out


def save(folder, plan, body):
    """Make (no `id`) or change (an `id` of a card) one card. `body`: {id?, t, dur_s, type?, start_s?, elements? [partial elements], texts? [words of a new card]}. Returns the card as `public` shows it."""
    doc = load(folder, plan); length = float((plan or {}).get('film', {}).get('length_s') or 0.0); old = None
    if body.get('id'):
        old = next((c for c in doc['cards'] if c['id'] == body['id']), None)
        if old is None: raise KeyError(f"no card {body['id']}")
    try: t = float(body.get('t', (old or {}).get('t')))
    except (TypeError, ValueError): raise Invalid('the start must be a number of seconds')
    if not 0.0 <= t <= max(length, 0.0): raise Invalid(f'the start must be inside the film (0 to {length:.1f} s)')
    try: dur = float(body.get('dur_s', (old or {}).get('dur_s', 3.0)))
    except (TypeError, ValueError): raise Invalid('the length must be a number of seconds')
    dur = float(np.clip(dur, MIN_DUR, MAX_DUR)); spec = dict((old or {}).get('spec') or {})
    from strata360.edit import title_design as TD
    if body.get('elements') is not None:
        if not isinstance(body['elements'], list): raise Invalid('elements must be a list')
        els = [TD.normalize_element(e) for e in body['elements'][:MAX_ELEMENTS] if isinstance(e, dict)]
    elif old is None: els = default_elements(body.get('texts') or [])
    else: els = spec.get('elements') or []
    els = [e for e in els if e['text']]
    if not els: raise Invalid('a card needs at least one word')
    try: start = float(body.get('start_s', (spec.get('timing') or {}).get('start_s', 0.15)))
    except (TypeError, ValueError): raise Invalid('the delay must be a number of seconds')
    start = float(np.clip(start, 0.0, max(dur - 0.3, 0.0))); spec['elements'] = els; spec['timing'] = dict(start_s=round(start, 2), end_s=round(dur, 2)); spec['lines'] = [dict(role='title' if i == 0 else 'meta', text=e['text']) for i, e in enumerate(els)]
    cid = old['id'] if old else 'u' + str(int(time.time() * 1000))
    card = dict(old or {}, id=cid, type=body.get('type') or (old or {}).get('type') or 'note', t=round(t, 2), dur_s=round(dur, 2), lines=spec['lines'], spec=spec); card.pop('blocking', None); card['by'] = 'hand'
    doc['cards'] = [c for c in doc['cards'] if c['id'] != cid] + [card]; doc.setdefault('plan_key', None)
    if doc['plan_key'] is None and plan:
        from strata360.render import preview as PVW
        doc['plan_key'] = PVW.plan_key(folder, plan)
    _write(folder, doc); return public(card)


def delete(folder, plan, cid):
    doc = load(folder, plan); n = len(doc['cards']); doc['cards'] = [c for c in doc['cards'] if c['id'] != cid]
    if len(doc['cards']) == n: raise KeyError(f'no card {cid}')
    _write(folder, doc)


def preview_dir(folder, plan=None):
    """The folder of the film preview of this plan (else the latest one) with its stream, or None."""
    from strata360.edit import film_text as FT
    from strata360.render import preview as PVW
    if plan:
        d = PVW.film_dir(folder, PVW.plan_key(folder, plan))
        if os.path.exists(os.path.join(d, 'index.m3u8')): return d
    return FT.latest_preview(folder)


def base_source(folder, plan=None):
    """What the frames are read from: the preview's text-free video when it has one, else its stream (which has the saved cards drawn on it), None when there is no preview."""
    d = preview_dir(folder, plan)
    if d is None: return None
    b = os.path.join(d, 'base.mp4'); return b if os.path.exists(b) else os.path.join(d, 'index.m3u8')


def frame_at(folder, plan, t):
    """The preview's frame at film second t as uint8 RGB (540, 960, 3)."""
    src = base_source(folder, plan)
    if src is None: raise FileNotFoundError('no film preview yet: render it first')
    W, H = SIZE; r = subprocess.run(['ffmpeg', '-v', 'error', '-ss', f'{max(t, 0.0):.2f}', '-i', src, '-frames:v', '1', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-vf', f'scale={W}:{H}', '-'], capture_output=True)
    if len(r.stdout) != W * H * 3: raise RuntimeError(f'could not read the preview at {t:.1f} s')
    return np.frombuffer(r.stdout, np.uint8).reshape(H, W, 3).copy()


def checker(W, H, cell=24):
    ys, xs = np.mgrid[0:H, 0:W]; g = np.where(((xs // cell) + (ys // cell)) % 2 == 0, 58, 84).astype(np.uint8); return np.stack([g, g, g], -1)


def picture(folder, plan, card, mode='still', w=640):
    """PNG bytes of a card (a `public` or stored dict with t, dur_s, spec): `still` on the film's frame at the moment it is most itself, `text` alone. Made once for the same card and frame."""
    import cv2
    from strata360.render import captions as CP
    spec = card.get('spec') or {'elements': card.get('elements') or [], 'timing': dict(start_s=card.get('start_s', 0.15), end_s=card['dur_s'])}; t0, dur = float(card['t']), float(card['dur_s']); at = t0 + dur * 0.62; W, H = SIZE
    src = base_source(folder, plan) if mode == 'still' else None
    if mode == 'still' and src is None: raise FileNotFoundError('no film preview yet: render it first')
    sig = hashlib.sha1(json.dumps([mode, t0, dur, spec, w, os.path.getmtime(src) if src and os.path.exists(src) else 0], sort_keys=True, default=str).encode()).hexdigest()[:16]
    d = os.path.join(config.race_dir(folder), 'film_text_stills'); os.makedirs(d, exist_ok=True); path = os.path.join(d, f'{mode}-{sig}.png')
    if os.path.exists(path): return open(path, 'rb').read()
    img = frame_at(folder, plan, at) if mode == 'still' else checker(W, H)
    out = CP.Cards([dict(t=t0, dur_s=dur, spec=spec)], W, H, FPS).apply(img, int(round(at * FPS)))
    if w and w != W: out = cv2.resize(out, (int(w), int(round(w * H / W))), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode('.png', np.ascontiguousarray(out[..., ::-1]));
    if not ok: raise RuntimeError('could not encode the picture')
    tmp = f'{path}.{os.getpid()}.part'; open(tmp, 'wb').write(buf.tobytes()); os.replace(tmp, path); return buf.tobytes()
