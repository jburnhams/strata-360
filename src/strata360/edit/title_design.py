"""Design the word art of a shot with the local vision model. The model looks at frames of the shot and is told what was measured in them (how light and how busy each part of the frame is, where the faces are, the dominant colours); it answers with a
composition: each word with its own font, size, fill, outline, extrusion, glow, place, rotation, curve and entrance (render/titles.py). The code then checks it against the pictures and corrects it, and the model gets a look at the result.

  design(frames, lines, kind, duration, server)  ->  spec, report

What the code guarantees whatever the model says (`normalize`, `enforce`): only the user's words appear, each once; fonts, presets and numbers are inside the allowed set and range; no word covers a face in any frame while it is on screen (it is moved to the nearest free
place); every word has a contrast of at least 3 against what is behind it (an outline in the opposite tone is added if not, and a stronger shadow below 4.5); the whole thing is on screen for a readable time inside the shot."""
import json, os, re
import numpy as np
from strata360.render import titles as TT

COLOR_RE = re.compile(r'^#[0-9a-fA-F]{6}$')
SAMPLES = (0.08, 0.3, 0.55, 0.8, 0.96)                       # where in the shot the frames are taken, as fractions of its length
MAX_ELEMENTS = 8
SCALES = (1.0, 0.88, 0.76, 0.66, 0.56, 0.48, 0.4, 0.33, 0.27)                      # the sizes a word is tried at, largest first
GRID = 0.02                                                  # the step of the search for a place, as a fraction of the frame
CLEAR = 0.0002                                               # the cost (about a 2 percent of a word's own area on a face, ten times that on other text) below which a place counts as clear
W_FACE, W_BODY, W_TEXT, W_WORDS, W_SIZE, W_MOVE = 10.0, 1.2, 8.0, 12.0, 0.8, 0.5               # the weights of the placement objective: covering a face, the main person, other text or another word; shrinking; moving away from where the model put it
SMALL_FACE = 0.004                                           # a face box this share of the frame (6 percent of each side) is counted
COVER_OK = 0.002                                             # the share of the frame's area of faces a word may cover without being moved


SMALL_EM = 0.10                                              # a word at most this tall (as a fraction of the frame height) is small text: lettering to read, not word art
SMALL_STROKE = 0.045                                         # the outline of small text, as a share of its size: a fixed outline eats the letters of a small word
SMALL_MARGIN = 0.6                                           # a tinted tone may have this share of the best contrast, as long as it reaches SMALL_AA: colour for small text costs legibility only above the target
SMALL_AA = 7.0                                               # the contrast small text aims for (WCAG AAA): thin letters have no colour to fall back on
STRONGER = {'barlow_cond_light': 'barlow_cond_bold'}         # thin weights fall apart small: the sturdier one of the same face


def style_from_palette(el, sw, px, used, ei, n):
    """Dress one element from the clip's palette (`sw`: its swatches) for the area it sits on (`px`: the pixels behind it, (n, 3) floats). Returns a note saying what was done.
    Display words (size over SMALL_EM) take a saturated hue at a modest contrast, because a heavy opposite-tone outline and a drop shadow carry the legibility. Small words get what thin letters need: a pale or deep tint of the base hue (or a tinted neutral) chosen for
    contrast of SMALL_AA (the complement's tint first), an outline that scales with their size, a sturdier weight and more tracking, and the accent colour as a soft glow, so the complement is still in the card without asking thin letters to carry it."""
    from strata360.analysis import palette as PAL
    neutrals = [x for x in sw if x['role'] == 'neutral']; was = el['fill']['c1']
    if el['size'] < SMALL_EM:
        pool = neutrals + [x for x in sw if x['role'] in ('base', 'accent') and x['tone'] in ('light', 'dark')]; c1, ct, sel = PAL.choose(pool, px, ('accent', 'base', 'neutral'), aa=SMALL_AA, margin=SMALL_MARGIN)       # the complement first, then the base hue, a tinted neutral only when neither reaches the contrast
        accent = next((x['hex'] for x in sw if x['role'] == 'accent' and x['tone'] == 'mid_light'), None); kind = 'small'
        el['stroke'] = dict(w=round(float(np.clip(SMALL_STROKE * el['size'], 0.0015, 0.005)), 4), color=PAL.choose(neutrals, px, against=c1)[0]); el['shadow'] = dict(el['shadow'], opacity=max(el['shadow']['opacity'], 0.75), blur=max(el['shadow']['blur'], 0.01), dy=max(el['shadow']['dy'], 0.004))
        if accent: el['glow'] = dict(r=0.012, color=accent, opacity=max(el['glow']['opacity'], 0.4))
        el['font'] = STRONGER.get(el['font'], el['font']); el['tracking'] = max(el['tracking'], 0.1)
    else:
        prefer = ('base', 'accent', 'support') if ei == 0 else ('accent', 'support', 'base'); c1, ct, sel = PAL.choose_coloured(sw, px, prefer, exclude=used[-1:] if n > 1 else ()); kind = 'display'
        if c1: el['stroke'] = dict(w=float(np.clip(0.03 * el['size'], 0.004, 0.012)), color=PAL.choose(neutrals, px, against=c1)[0]); el['shadow'] = dict(el['shadow'], opacity=max(el['shadow']['opacity'], 0.7), blur=max(el['shadow']['blur'], 0.016), dy=max(el['shadow']['dy'], 0.007))
    if not c1: return f"'{el['text']}': no palette colour fits"
    el['fill'] = dict(el['fill'], type='solid', c1=c1, c2=c1)
    return f"'{el['text']}' ({kind} text): {c1} ({sel['role']} {sel['tone']}) from the palette, contrast {ct:.1f} against the area it is on (the model had {was})"


def _luma(rgb): return 0.2126 * rgb[..., 0] + 0.7152 * rgb[..., 1] + 0.0722 * rgb[..., 2]


def frame_stats(frames):
    """For each frame (uint8 RGB): a 3 x 3 grid of lightness (0 to 9) and detail (0 to 9, edge strength), and the 4 dominant colours of the frame (hex, share)."""
    import cv2
    out = []
    for f in frames:
        small = cv2.resize(f, (192, 108), interpolation=cv2.INTER_AREA).astype(np.float32) / 255.0; L = _luma(small); g = cv2.cvtColor((small * 255).astype(np.uint8), cv2.COLOR_RGB2GRAY).astype(np.float32); e = np.hypot(cv2.Sobel(g, cv2.CV_32F, 1, 0), cv2.Sobel(g, cv2.CV_32F, 0, 1))
        light = [[int(round(float(L[r * 36:(r + 1) * 36, c * 64:(c + 1) * 64].mean()) * 9)) for c in range(3)] for r in range(3)]; detail = [[int(min(round(float(e[r * 36:(r + 1) * 36, c * 64:(c + 1) * 64].mean()) / 18.0), 9)) for c in range(3)] for r in range(3)]
        pts = small.reshape(-1, 3); _, lab, cen = cv2.kmeans(pts, 4, None, (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 12, 1.0), 2, cv2.KMEANS_PP_CENTERS); share = np.bincount(lab.ravel(), minlength=4) / len(lab)
        cols = [('#%02x%02x%02x' % tuple(int(round(v * 255)) for v in cen[i]), round(float(share[i]), 2)) for i in np.argsort(-share)]; out.append(dict(light=light, detail=detail, colours=cols))
    return out


def face_boxes(frames, models='models'):
    """[(x0, y0, x1, y1) as fractions of the frame] for each frame: the faces found (insightface's detector, the one the people stage uses)."""
    try:
        from insightface.app import FaceAnalysis
        fa = FaceAnalysis(name='buffalo_l', root=os.path.join(models, 'insightface'), allowed_modules=['detection'], providers=['CUDAExecutionProvider', 'CPUExecutionProvider']); fa.prepare(ctx_id=0, det_size=(640, 640))
    except Exception: return [[] for _ in frames]
    out = []
    for f in frames:
        H, W = f.shape[:2]; found = []
        for fc in fa.get(f[..., ::-1].copy()):
            x0, y0, x1, y1 = (float(v) for v in fc.bbox); found.append((max(x0 / W, 0.0), max(y0 / H, 0.0), min(x1 / W, 1.0), min(y1 / H, 1.0)))
        out.append(found)
    return out


def person_boxes(frames, models='models'):
    """[(x0, y0, x1, y1)] per frame: the people found (YOLO11 pose, the detector of the people stage), as fractions of the frame; the main subject of a shot is usually one of them."""
    try:
        from ultralytics import YOLO
        m = YOLO(os.path.join(models, 'yolo11s-pose.pt')); res = m.predict([f[..., ::-1].copy() for f in frames], imgsz=960, conf=0.25, classes=[0], verbose=False)
    except Exception: return [[] for _ in frames]
    return [[(float(b[0]) / r.orig_shape[1], float(b[1]) / r.orig_shape[0], float(b[2]) / r.orig_shape[1], float(b[3]) / r.orig_shape[0]) for b in r.boxes.xyxy.cpu().numpy()] for r in res]


def overlap(a, b, grow=0.03):
    return not (a[2] < b[0] - grow or b[2] < a[0] - grow or a[3] < b[1] - grow or b[3] < a[1] - grow)


def _num(v, default):
    try: return float(v)
    except (TypeError, ValueError): return default


def _col(v, default): return v if isinstance(v, str) and COLOR_RE.match(v) else default


def words_of(text): return re.findall(r"[\w'’-]+", str(text).lower())


def normalize_element(e):
    """One element made safe: known font, presets and eases, numbers in range, colours as #rrggbb; everything else from TT.ELEMENT."""
    e = dict(e) if isinstance(e, dict) else {}
    for k, key in (('fill', 'c1'), ('stroke', 'color'), ('glow', 'color'), ('extrude', 'color')):                      # a model sometimes writes a colour where an object belongs
        if isinstance(e.get(k), str): e[k] = {key: e[k]}
        elif k in e and not isinstance(e[k], dict): e.pop(k)
    if 'shadow' in e and not isinstance(e['shadow'], dict): e.pop('shadow')
    el = TT._deep(TT.ELEMENT, e); el['text'] = str(el['text']).strip()
    if el['font'] not in TT.FONTS: el['font'] = 'anton'
    el['size'] = float(np.clip(_num(el['size'], 0.14), 0.03, 0.42)); el['x'] = float(np.clip(_num(el['x'], 0.5), 0.06, 0.94)); el['y'] = float(np.clip(_num(el['y'], 0.5), 0.08, 0.92)); el['rot'] = float(np.clip(_num(el['rot'], 0.0), -25, 25)); el['curve'] = float(np.clip(_num(el['curve'], 0.0), -0.8, 0.8))
    el['tracking'] = float(np.clip(_num(el['tracking'], 0.02), -0.03, 0.4)); el['anchor'] = el['anchor'] if el['anchor'] in ('c', 'l', 'r') else 'c'; el['case'] = el['case'] if el['case'] in ('upper', 'lower', 'title', 'none') else 'upper'
    f = el['fill'] = dict(el['fill']); f['type'] = f['type'] if f.get('type') in ('solid', 'gradient') else 'solid'; f['c1'] = _col(f.get('c1'), '#ffffff'); f['c2'] = _col(f.get('c2'), f['c1']); f['angle'] = float(np.clip(_num(f.get('angle'), 90.0), -360, 360))
    s = el['stroke'] = dict(el['stroke']); s['w'] = float(np.clip(_num(s.get('w'), 0.0), 0.0, 0.012)); s['color'] = _col(s.get('color'), '#101010')
    x = el['extrude'] = dict(el['extrude']); x['depth'] = float(np.clip(_num(x.get('depth'), 0.0), 0.0, 0.03)); x['color'] = _col(x.get('color'), '#202020'); x['angle'] = float(np.clip(_num(x.get('angle'), 45.0), -360, 360))
    g = el['glow'] = dict(el['glow']); g['r'] = float(np.clip(_num(g.get('r'), 0.0), 0.0, 0.06)); g['color'] = _col(g.get('color'), '#ffffff'); g['opacity'] = float(np.clip(_num(g.get('opacity'), 0.0), 0.0, 1.0))
    h = el['shadow'] = dict(el['shadow']); h['blur'] = float(np.clip(_num(h.get('blur'), 0.012), 0.0, 0.04)); h['opacity'] = float(np.clip(_num(h.get('opacity'), 0.45), 0.0, 0.9)); h['dy'] = float(np.clip(_num(h.get('dy'), 0.004), 0.0, 0.015))
    if el['in'] not in TT.PRESETS_IN: el['in'] = 'rise'
    if el['out'] not in TT.PRESETS_OUT: el['out'] = 'fade'
    if el['ease'] not in TT.EASES: el['ease'] = 'out_cubic'
    el['per'] = el['per'] if el['per'] in ('word', 'char') else 'word'; el['delay'] = float(np.clip(_num(el['delay'], 0.0), 0.0, 2.5)); el['in_s'] = float(np.clip(_num(el['in_s'], 0.9), 0.3, 2.0))
    if el['in'] in ('type', 'track_in') and el['per'] != 'char': el['per'] = 'char'                                  # these act on the letters
    return el


def normalize(spec, lines):
    """The model's answer as a complete, safe spec: elements (at most MAX_ELEMENTS) that use exactly the words of `lines`, once each. Words the model dropped are added back as a small line along the bottom; words it invented are removed. With no usable
    elements the plain stacked title (`lines` and the default design) is used."""
    s = TT.merge(dict(spec if isinstance(spec, dict) else {}, lines=lines)); want = [w for l in lines for w in words_of(l.get('text', ''))]; els = []
    for e in (spec.get('elements') if isinstance(spec, dict) else None) or []:
        if isinstance(e, dict) and str(e.get('text', '')).strip(): els.append(normalize_element(e))
    els = els[:MAX_ELEMENTS]; left = list(want); kept = []
    for el in els:                                                                                                 # keep only elements made of the user's words, each word at most as many times as it was given
        ws = words_of(el['text']); tmp = list(left)
        try:
            for w in ws: tmp.remove(w)
        except ValueError: continue
        left = tmp; kept.append(el)
    if kept and left: kept.append(normalize_element(dict(text=' '.join(left), font='barlow', size=0.04, x=0.5, y=0.92, tracking=0.15, **{'in': 'fade'}, delay=0.8)))
    s['elements'] = kept or None
    a = s['animation']; t = s['timing']; t['start_s'] = float(_num(t.get('start_s'), 0.6)); t['end_s'] = _num(t.get('end_s'), None) if t.get('end_s') is not None else None
    sc = s['scrim'] = dict(s.get('scrim') or {}); sc['opacity'] = float(np.clip(_num(sc.get('opacity'), 0.0), 0.0, 0.7)); sc['extent'] = float(np.clip(_num(sc.get('extent'), 0.5), 0.2, 0.9)); sc['side'] = sc.get('side') if sc.get('side') in ('top', 'bottom', 'left', 'right', 'none') else 'none'
    a['out_s'] = float(np.clip(_num(a.get('out_s'), 0.6), 0.2, 1.5)); return s


def fit_timing(spec, duration, clear=None):
    """The words are on screen inside the shot: they start at least 0.2 s in, the last one is in with 0.8 s to read, and all are gone before the end."""
    t = spec['timing']; a = spec['animation']; els = spec['elements'] or []; last = max([e['delay'] + e['in_s'] for e in els] or [a.get('in_s', 1.0) + 0.5]); need = last + 0.8
    start = float(np.clip(_num(t.get('start_s'), 0.6), 0.2, max(duration - need - a['out_s'], 0.2))); end = float(np.clip(_num(t.get('end_s'), duration - 0.4) if t.get('end_s') is not None else duration - 0.4, start + need, duration - 0.1))
    if clear:                                                                                                       # the stretch of the shot that is about something else (your face): the words are off screen then
        a_, b_ = clear
        if a_ >= duration / 2: end = min(end, a_ - 0.05); start = max(min(start, end - need), 0.2)                         # the clear stretch is late: the words come before it
        else: start = max(start, b_ + 0.05); end = max(end, min(start + need, duration - 0.1))                              # it is early: after it
    t['start_s'], t['end_s'] = round(start, 2), round(min(end, duration - 0.1), 2); return spec


def _fill_colour(el): return TT.hex_rgb(el['fill']['c1']), TT.hex_rgb(el['fill']['c2'])


def enforce(spec, lines, frames, times, boxes, duration, W=960, H=540, clear=None, bottom_clear=0.0, keep_in=None, avoid=(), persons=None, palette=None):
    """Check a spec against the frames (uint8 RGB at `times`, with the faces `boxes` found in each) and correct it. Returns (spec, notes): what was changed and why."""
    spec = fit_timing(normalize(spec, lines), duration, clear); notes = []; notes_orig = {}; els = spec['elements']; vis = [i for i, t in enumerate(times) if spec['timing']['start_s'] <= t <= spec['timing']['end_s']] or list(range(len(times)))
    if not els: return spec, notes
    bodies = [pb for i in vis for pb in (persons[i] if persons else []) if (pb[2] - pb[0]) * (pb[3] - pb[1]) >= 0.05]
    faces = [fb for i in vis for fb in boxes[i] if (fb[2] - fb[0]) * (fb[3] - fb[1]) >= SMALL_FACE]                  # every face big enough to read; the camera moves, so a place is judged over all the frames the words are on
    def boxes_of(es):
        t = TT.Title(dict(spec, elements=es), W, H, duration); out = {}
        for ei, b in TT.piece_boxes(t):
            o = out.get(ei); out[ei] = b if o is None else (min(o[0], b[0]), min(o[1], b[1]), max(o[2], b[2]), max(o[3], b[3]))
        return out
    def inter(a, b): return max(0.0, min(a[2], b[2]) - max(a[0], b[0])) * max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    def covered(nb): return 40.0 * sum(inter(nb, fb) for fb in faces) + 3.0 * sum(inter(nb, pb) for pb in bodies) + 30.0 * sum(max(0.0, min(nb[2], ab[2]) - max(nb[0], ab[0])) * max(0.0, min(nb[3], ab[3]) - max(nb[1], ab[1])) for ab in avoid)          # other text counts much more than a face
    zx0, zy0, zx1, zy1 = keep_in or (0.02, 0.02, 0.98, 0.98)
    if bottom_clear: zy1 = min(zy1, 1 - bottom_clear)                                                                 # a strip along the bottom belongs to the subtitles
    vf = [[fb for fb in boxes[i] if (fb[2] - fb[0]) * (fb[3] - fb[1]) >= SMALL_FACE] for i in vis]; vp = [[pb for pb in (persons[i] if persons else []) if (pb[2] - pb[0]) * (pb[3] - pb[1]) >= 0.05] for i in vis]
    def frac(nb, tg, cap=False):
        a_ = (tg[2] - tg[0]) * (tg[3] - tg[1]); a2 = (nb[2] - nb[0]) * (nb[3] - nb[1])
        return inter(nb, tg) / max(min(a_, a2) if cap else a_, 1e-9)
    def cost(nb, mine, cx0, cy0, s_, others):
        """The objective of one placement: what the word covers (faces, the main person, other text, the words already placed), as shares of the thing covered and averaged over the frames it is on, plus what the placement costs the design (a smaller word, a move)."""
        face = sum(sum(frac(nb, fb) for fb in fs) for fs in vf) / max(len(vf), 1); body = sum(sum(frac(nb, pb) for pb in ps) for ps in vp) / max(len(vp), 1)
        text = sum(frac(nb, ab, True) for ab in avoid); words = sum(frac(nb, o, True) for o in others if o)
        return W_FACE * face + W_BODY * body + W_TEXT * text + W_WORDS * words + W_SIZE * (1 - s_) + W_MOVE * (((nb[0] + nb[2]) / 2 - cx0) ** 2 + ((nb[1] + nb[3]) / 2 - cy0) ** 2) ** 0.5
    def ink(el): return boxes_of([el]).get(0)
    done = [ink(el) for el in els]                                                                                    # every word's box; each pass moves one with the others held
    for rnd in range(2):                                                                                              # coordinate descent: a word placed early is placed again once the later ones have settled
        for ei, el in enumerate(els):
            b0 = done[ei]
            if b0 is None: continue
            orig = notes_orig.setdefault(ei, (el['x'], el['y'], el['size'])); cur = (el['x'], el['y'], el['size']); w0, h0 = b0[2] - b0[0], b0[3] - b0[1]; ox, oy = (b0[0] + b0[2]) / 2 - el['x'], (b0[1] + b0[3]) / 2 - el['y']; k0 = cur[2] / orig[2]
            cx0, cy0 = orig[0] + ox / k0, orig[1] + oy / k0; others = [d for j, d in enumerate(done) if j != ei]; best = None
            for s_ in SCALES:                                                                                         # every size, every place: the minimum of the objective, not the first that is good enough
                w, h = w0 * s_ / k0, h0 * s_ / k0
                if w > zx1 - zx0 or h > zy1 - zy0: continue
                for gx in np.arange(zx0 + w / 2, zx1 - w / 2 + 1e-9, GRID):
                    for gy in np.arange(zy0 + h / 2, zy1 - h / 2 + 1e-9, GRID):
                        c = cost((gx - w / 2, gy - h / 2, gx + w / 2, gy + h / 2), None, cx0, cy0, s_, others)
                        if best is None or c < best[0]: best = (c, s_, gx, gy, w, h)
            if best is None: continue
            c, s_, gx, gy, w, h = best; el['size'] = float(max(orig[2] * s_, 0.03)); el['x'] = float(gx - ox / k0 * s_); el['y'] = float(gy - oy / k0 * s_); done[ei] = ink(el)
    for ei, el in enumerate(els):
        o = notes_orig.get(ei)
        if o and (abs(o[0] - el['x']) > 1e-3 or abs(o[1] - el['y']) > 1e-3 or abs(o[2] - el['size']) > 1e-4): notes.append(f"'{el['text']}': placed at ({el['x']:.2f}, {el['y']:.2f}) at {int(100 * el['size'] / o[2])}% of the size the model chose (the placement that costs least)")
    placed = boxes_of(els)
    for ei, el in enumerate(els):
        b = placed.get(ei)
        if b is None: continue
        bg = [];
        for i in vis:
            f = frames[i].astype(np.float32) / 255.0; Hh, Ww = f.shape[:2]; bg.append(f[int(b[1] * Hh):max(int(b[3] * Hh), int(b[1] * Hh) + 1), int(b[0] * Ww):max(int(b[2] * Ww), int(b[0] * Ww) + 1)].reshape(-1, 3))
        if palette: notes.append(style_from_palette(el, palette['scheme']['swatches'], np.concatenate(bg), [o['fill']['c1'] for o in els[:ei]], ei, len(els)))                 # the colours come from the clip's palette
        bgc = np.concatenate(bg).mean(0); worst = min(TT.contrast(c, tuple(bgc)) for c in _fill_colour(el))
        if worst < 3.0:
            dark = TT.luminance(_fill_colour(el)[0]) > 0.4; el['stroke'] = dict(w=max(el['stroke']['w'], 0.006), color='#101010' if dark else '#f5f5f5'); el['shadow']['opacity'] = max(el['shadow']['opacity'], 0.55); notes.append(f"'{el['text']}' had contrast {worst:.1f} against the picture: an outline of the opposite tone added")
        elif worst < 4.5 and el['shadow']['opacity'] < 0.6: el['shadow']['opacity'] = 0.65; notes.append(f"'{el['text']}' had contrast {worst:.1f}: a stronger shadow")
    return spec, notes


def blocking(spec, times, boxes, persons, avoid, duration, W=960, H=540):
    """How much the placed words get in the way, measured after the best placement, so the planner can decide whether to use the card. Over the frames the words are on screen:
      face     the largest share of any face (area >= 0.4 percent of the frame) covered by a word, in any frame, 0 to 1
      subject  the mean share of the main person's box (the biggest one) covered by the words' letters, 0 to 1
      text     the largest share of any other text's box (overlay, subtitles, other cards) covered, 0 to 1
      score    0 (nothing in the way) to 10 (a face is hidden), mostly the worst of the three; `what` says in words which, when it matters."""
    els = spec['elements'] or []
    if not els: return dict(face=0.0, subject=0.0, text=0.0, score=0.0, what='')
    t = TT.Title(spec, W, H, duration); bx = [b for _, b in TT.piece_boxes(t)]; vis = [i for i, tt in enumerate(times) if spec['timing']['start_s'] <= tt <= spec['timing']['end_s']] or list(range(len(times)))
    def inter(a, b): return max(0.0, min(a[2], b[2]) - max(a[0], b[0])) * max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    def share(target): a = (target[2] - target[0]) * (target[3] - target[1]); return min(sum(inter(b, target) for b in bx) / a, 1.0) if a > 0 else 0.0
    face = max([share(fb) for i in vis for fb in boxes[i] if (fb[2] - fb[0]) * (fb[3] - fb[1]) >= SMALL_FACE] or [0.0]); text = max([share(ab) for ab in avoid] or [0.0])
    subj = []
    for i in vis:
        ps = sorted(persons[i], key=lambda p: -(p[2] - p[0]) * (p[3] - p[1])) if persons else []
        if ps: subj.append(share(ps[0]))
    subject = float(np.mean(subj)) if subj else 0.0; score = round(10.0 * min(1.0, max(face * 1.0, text * 1.0, subject * 0.7)), 1); what = []
    if face > 0.05: what.append(f'covers {int(face * 100)}% of a face')
    if text > 0.05: what.append(f'covers {int(text * 100)}% of other text')
    if subject > 0.15: what.append(f'covers {int(subject * 100)}% of the main person')
    return dict(face=round(float(face), 3), subject=round(subject, 3), text=round(float(text), 3), score=score, what='; '.join(what))


PROMPT = """You are a typographic artist making the title WORD ART for a film about an ultramarathon, shot on a 360 camera worn by the runner. Design the animated lettering that goes over the {kind} shot ({secs:.1f} seconds). You are given 3 of its frames, taken at {times} seconds.

The words, which you must use exactly once each and may split into separate elements: {words}

Measured in the frames (a 3 x 3 grid, rows top to bottom, columns left to right; lightness 0 dark to 9 bright, detail 0 smooth to 9 busy), faces as boxes (x0, y0, x1, y1 as fractions of the frame), and the dominant colours (hex, share):
{stats}

Scene: {scene}
{clear}
The frames you see already have the film's other text on them (the race overlay, subtitles, other cards): add yours LAST and keep it clear of all of it, so everything underneath stays readable.

Make it word art, not a caption: contrast of scale between the words, a few of them rotated or on a curve, fills that borrow colours from the picture (gradients work well), outlines or an extruded edge or a glow where they help the letters stand out, entrances that suit the words and the energy of the shot (letters dropping in, a word spinning in, a line typed out along a curve ...). For example (only to show the range, do not copy it): a big word with a warm gradient, an extruded edge and a slight tilt that drops in letter by letter; a second word half its size in a contrasting font that spins in beside it; a short line along a gentle curve that types itself out underneath.
Compose it like a poster: leave the faces and the main subject clear, put the words where the picture is calm, and keep it readable.
Use 1 to 3 fonts. Fonts: {fonts}
Animations in: {pin}. Out: {pout}. Eases: {eases}. `per` is word (the element moves as one) or char (the letters come one after the other; `type` and `track_in` need char).
Answer with ONE JSON object and nothing else:
{{"elements": [{{"text": "...", "font": id, "size": em as a fraction of the frame height, 0.03 to 0.42, "x": centre 0 to 1, "y": centre 0 to 1, "anchor": "c", "rot": degrees -25 to 25, "curve": -0.8 to 0.8, "tracking": em, "case": "upper|lower|title|none",
"fill": {{"type": "solid|gradient", "c1": "#rrggbb", "c2": "#rrggbb", "angle": degrees}}, "stroke": {{"w": 0 to 0.012, "color": "#rrggbb"}}, "extrude": {{"depth": 0 to 0.03, "color": "#rrggbb", "angle": degrees}}, "glow": {{"r": 0 to 0.06, "color": "#rrggbb", "opacity": 0 to 1}},
"shadow": {{"blur": 0 to 0.04, "opacity": 0 to 0.9, "dy": 0 to 0.015}}, "in": preset, "out": preset, "delay": seconds after the start, "in_s": seconds, "per": "word|char", "ease": ease}}, ...],
"timing": {{"start_s": number, "end_s": number}}, "scrim": {{"opacity": 0 to 0.7, "side": "top|bottom|left|right|none", "extent": 0.2 to 0.9}}, "why": "one or two sentences on the choices"}}"""

CRITIQUE = """This is a frame of a film shot with its word art added. The words are: {words}. Is it well designed for this picture? Check: every word legible against the picture; no word covering a face or the main subject; the colours, fonts and sizes suit the picture and each other; nothing cut off at the edges; it looks like deliberate word art, not a caption.
Answer with ONE JSON object and nothing else: {{"ok": true or false, "problems": ["..."], "elements": null or the complete corrected list of elements in the same format as before}}."""


def parse(text):
    m = re.search(r'\{.*\}', text, re.S)
    if not m: return None
    for cand in (m.group(0), re.sub(r',\s*([}\]])', r'\1', m.group(0))):
        try: return json.loads(cand)
        except ValueError: pass
    return None


def design(frames, lines, kind, duration, server, scene='', models='models', tmp_dir=None, rounds=2, log=print, clear=None, bottom_clear=0.0, keep_in=None, avoid=(), palette=None):
    """frames: uint8 RGB pictures of the shot at the fractions `SAMPLES` of `duration`. `palette`: the clip's palette document (analysis/palette.py), told to the model as the colours to use. Returns (spec, report): the final spec and what happened (the model's own answer, what the code changed, the critique)."""
    import cv2
    from strata360.analysis import palette as PAL
    if palette: scene = (scene + ' ' + PAL.for_prompt(palette)).strip()
    tmp_dir = tmp_dir or os.path.join(os.path.dirname(__file__), '..', '..', '..', 'models'); os.makedirs(tmp_dir, exist_ok=True); times = [round(f * duration, 2) for f in SAMPLES]; stats = frame_stats(frames); boxes = face_boxes(frames, models); persons = person_boxes(frames, models)
    info = [dict(t=times[i], light=stats[i]['light'], detail=stats[i]['detail'], faces=[[round(v, 2) for v in b] for b in boxes[i]], colours=stats[i]['colours']) for i in range(len(frames))]; paths = []
    for k in (0, 2, 4):
        p = os.path.join(tmp_dir, f'_title_frame{k}.jpg'); cv2.imwrite(p, cv2.resize(frames[k], (960, 540), interpolation=cv2.INTER_AREA)[..., ::-1], [cv2.IMWRITE_JPEG_QUALITY, 90]); paths.append(p)
    words = ' / '.join(l['text'] for l in lines)
    prompt = PROMPT.format(kind=kind, secs=duration, times=f'{times[0]}, {times[2]} and {times[4]}', words=json.dumps(words), stats=json.dumps(info), scene=scene or 'not known', clear=("The shot is about the runner's face between %.1f and %.1f seconds: the words must be off the screen by then (or come after), so put their timing in the other part." % tuple(clear)) if clear else '', fonts='; '.join(f'{k} ({v[1]})' for k, v in TT.FONTS.items()),
                           pin=', '.join(TT.PRESETS_IN), pout=', '.join(TT.PRESETS_OUT), eases=', '.join(TT.EASES))
    raw = server.ask(prompt, paths, 1800, temperature=0.8); ans = parse(raw) or {}; report = dict(model_answer=ans, rounds=[])
    if not ans or not ans.get('elements'): log('the model gave no usable composition: the plain stacked title is used')
    spec, notes = enforce(ans, lines, frames, times, boxes, duration, clear=clear, bottom_clear=bottom_clear, keep_in=keep_in, avoid=avoid, persons=persons, palette=palette); report['changes'] = notes
    for r in range(rounds):
        mid = int(round(0.6 * (len(frames) - 1))); title = TT.Title(spec, frames[mid].shape[1], frames[mid].shape[0], duration); t_show = float(np.clip(times[mid], spec['timing']['start_s'] + 2.0, spec['timing']['end_s'] - 0.7))
        shown = title.apply(frames[mid], t_show); p = os.path.join(tmp_dir, '_title_check.jpg'); cv2.imwrite(p, cv2.resize(shown, (960, 540), interpolation=cv2.INTER_AREA)[..., ::-1], [cv2.IMWRITE_JPEG_QUALITY, 90])
        crit = parse(server.ask(CRITIQUE.format(words=json.dumps(words)), [p], 1800)) or {}; report['rounds'].append(crit)
        if crit.get('ok', True) or not crit.get('elements'): break
        spec, notes2 = enforce(dict(ans, elements=crit['elements']), lines, frames, times, boxes, duration, clear=clear, bottom_clear=bottom_clear, keep_in=keep_in, avoid=avoid, persons=persons, palette=palette); report['changes'] += notes2
    spec['why'] = ans.get('why', ''); report['blocking'] = blocking(spec, times, boxes, persons, list(avoid), duration, frames[0].shape[1], frames[0].shape[0]); return spec, report
