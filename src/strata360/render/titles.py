"""Word art over a shot: a composition of lettered words, each with its own font, size, fill, outline, extrusion, glow, rotation, curve and entrance, composited on the picture frame by frame.

A title is a spec dict. The part that matters is `elements`, a list of words (or short phrases) placed on the frame like a poster; edit/title_design.py makes one for a shot with the local model:

  element   text, font (a key of FONTS), size (the font's em as a fraction of the frame height), x, y (the centre, fractions of the frame), anchor (c, l or r about x), rot (degrees), curve (-1 to 1, along an arc), tracking (em), case,
            fill {type solid|gradient, c1, c2, angle}, stroke {w, color} (fractions of the height), extrude {depth, color, angle}, glow {r, color, opacity}, shadow {blur, opacity, dy},
            in / out (presets), delay, in_s, per (word | char: the letters come one after the other), ease
  timing    start_s and end_s inside the shot
  scrim     a soft dark gradient behind the words: {opacity, side top|bottom|left|right|none, extent}

Without `elements`, `lines` (role title, subtitle, meta) and `design` give a plain stacked title (`from_block`), which is also what the design falls back to. Presets in: fade, rise, drop (falls and settles), pop (overshoots), zoom (grows from small),
spin (turns in), blur_in, track_in (the letters close up from wide spacing), type, wipe, slide. Out: fade, rise, blur, shrink, none. All sizes are fractions of the frame, so one spec serves a preview and 4K."""
import os
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__)); FONT_DIR = os.path.join(HERE, 'title_fonts')
FONTS = {'bebas': ('BebasNeue-Regular.ttf', 'tall condensed capitals, athletic and clean'), 'anton': ('Anton-Regular.ttf', 'heavy condensed poster capitals, loud'), 'archivo_black': ('ArchivoBlack-Regular.ttf', 'wide heavy sans, bold and modern'),
         'barlow_cond_light': ('BarlowCondensed-Light.ttf', 'light condensed sans, elegant and technical'), 'barlow_cond_bold': ('BarlowCondensed-Bold.ttf', 'bold condensed sans, sporty and legible'), 'barlow': ('Barlow-Medium.ttf', 'plain medium sans for small lines'),
         'dm_serif': ('DMSerifDisplay-Regular.ttf', 'high-contrast display serif, editorial and warm'), 'dm_serif_italic': ('DMSerifDisplay-Italic.ttf', 'italic display serif, personal and soft'),
         'inter': (os.path.join('..', 'overlay', 'fonts', 'Inter-SemiBold.ttf'), 'neutral semibold sans')}
PRESETS_IN = ('fade', 'rise', 'drop', 'pop', 'zoom', 'spin', 'blur_in', 'track_in', 'type', 'wipe', 'slide')
PRESETS_OUT = ('fade', 'rise', 'blur', 'shrink', 'none')
EASES = ('linear', 'out_cubic', 'in_out', 'out_expo', 'out_back')
ANCHORS = ('tl', 'tc', 'tr', 'ml', 'mc', 'mr', 'bl', 'bc', 'br')
ELEMENT = dict(text='', font='anton', size=0.14, x=0.5, y=0.5, anchor='c', rot=0.0, curve=0.0, tracking=0.02, case='upper', fill=dict(type='solid', c1='#ffffff', c2='#ffffff', angle=90.0), stroke=dict(w=0.0, color='#101010'),
               extrude=dict(depth=0.0, color='#202020', angle=45.0), glow=dict(r=0.0, color='#ffffff', opacity=0.0), shadow=dict(blur=0.012, opacity=0.45, dy=0.004), **{'in': 'rise', 'out': 'fade'}, delay=0.0, in_s=0.9, per='word', ease='out_cubic')
DEFAULT = dict(lines=[dict(role='title', text='TITLE')], elements=None, design=dict(fonts=dict(title='bebas', subtitle='barlow_cond_light', meta='barlow'), sizes=dict(title=0.14, subtitle=0.05, meta=0.028), tracking=dict(title=0.02, subtitle=0.12, meta=0.2),
               case=dict(title='upper', subtitle='upper', meta='upper'), color='#ffffff', accent='#ffb347', accent_use='rule', layout=dict(anchor='bl', align='left', margin=0.07, gap=0.018, rule=True, rule_len=0.16)),
               timing=dict(start_s=0.6, end_s=None), scrim=dict(opacity=0.0, side='none', extent=0.5), animation=dict({'in': 'rise', 'out': 'fade'}, in_s=1.0, out_s=0.6, stagger_s=0.25, per='word', ease='out_cubic'))
_fonts = {}


def hex_rgb(h):
    h = h.lstrip('#'); return tuple(int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))


def luminance(rgb):
    f = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (f(c) for c in rgb); return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    """WCAG contrast ratio of two colours given as (r, g, b) in 0..1."""
    la, lb = luminance(a), luminance(b); hi, lo = max(la, lb), min(la, lb); return (hi + 0.05) / (lo + 0.05)


def font(fid, px):
    from PIL import ImageFont
    key = (fid, int(round(px)))
    if key not in _fonts: _fonts[key] = ImageFont.truetype(os.path.normpath(os.path.join(FONT_DIR, FONTS.get(fid, FONTS['inter'])[0])), max(int(round(px)), 4))
    return _fonts[key]


def ease(name, u):
    u = float(np.clip(u, 0.0, 1.0))
    if name == 'linear': return u
    if name == 'in_out': return u * u * (3 - 2 * u)
    if name == 'out_expo': return 1.0 if u >= 1 else 1 - 2 ** (-10 * u)
    if name == 'out_back': c = 1.70158; return 1 + (c + 1) * (u - 1) ** 3 + c * (u - 1) ** 2
    if name == 'bounce':
        n, d = 7.5625, 2.75
        if u < 1 / d: return n * u * u
        if u < 2 / d: u -= 1.5 / d; return n * u * u + 0.75
        if u < 2.5 / d: u -= 2.25 / d; return n * u * u + 0.9375
        u -= 2.625 / d; return n * u * u + 0.984375
    return 1 - (1 - u) ** 3


def _deep(a, b):
    out = dict(a)
    for k, v in (b or {}).items(): out[k] = _deep(a[k], v) if isinstance(v, dict) and isinstance(a.get(k), dict) else v
    return out


def merge(spec):
    """The spec with everything missing taken from DEFAULT; each element with everything missing taken from ELEMENT."""
    s = _deep(DEFAULT, {k: v for k, v in spec.items() if k not in ('lines', 'elements')}); s['lines'] = spec.get('lines') or DEFAULT['lines']
    s['elements'] = [_deep(ELEMENT, e) for e in spec['elements']] if spec.get('elements') else None; return s


def from_block(spec, W, H, duration):
    """The plain stacked title of `lines` and `design` as elements (what the block layout puts where): used when no composition was made."""
    s = merge(spec); d = s['design']; lay = d['layout']; a = s['animation']; items = []; mx, my = lay['margin'] * W, lay['margin'] * H
    for ln in s['lines']:
        role = ln.get('role', 'title'); text = str(ln.get('text', ''))
        if text.strip(): items.append((role, text))
    metrics = []
    for role, text in items:
        px = d['sizes'].get(role, 0.05) * H; tr = d['tracking'].get(role, 0.0); fid = d['fonts'].get(role, 'inter'); cs = d['case'].get(role, 'upper'); t = {'upper': text.upper(), 'lower': text.lower(), 'title': text.title()}.get(cs, text); f = font(fid, px)
        w = f.getlength(t) + tr * px * max(len(t) - 1, 0)
        if w > W - 2 * mx: px *= (W - 2 * mx) / w; w = W - 2 * mx
        metrics.append((role, t, fid, px, w, px * 1.15))
    gap = lay['gap'] * H; bw = max([m[4] for m in metrics] or [1.0]); bh = sum(m[5] for m in metrics) + gap * max(len(metrics) - 1, 0)
    ax, ay = lay['anchor'][1], lay['anchor'][0]; x0 = {'l': mx, 'c': (W - bw) / 2, 'r': W - mx - bw}[ax]; y0 = {'t': my, 'm': (H - bh) / 2, 'b': H - my - bh}[ay]; y = y0; els = []
    for k, (role, t, fid, px, w, h) in enumerate(metrics):
        xl = {'left': x0, 'center': x0 + (bw - w) / 2, 'right': x0 + bw - w}[lay['align']]; col = d['accent'] if (d.get('accent_use') == 'subtitle' and role == 'subtitle') else d['color']
        els.append(_deep(ELEMENT, dict(text=t, case='none', font=fid, size=px / H, x=(xl + w / 2) / W, y=(y + h / 2) / H, tracking=d['tracking'].get(role, 0.0), fill=dict(type='solid', c1=col, c2=col), delay=k * a.get('stagger_s', 0.25),
                                       in_s=a.get('in_s', 1.0), ease=a.get('ease', 'out_cubic'), per=a.get('per', 'word'), **{'in': a['in'], 'out': a['out']}))); y += h + gap
    return els


class Piece:
    """One sprite (a word, or a letter of one) with its resting place."""
    def __init__(self, rgb, a, cx, cy, rot, order, count, el):
        self.rgb, self.a, self.cx, self.cy, self.rot, self.order, self.count, self.el = rgb, a, cx, cy, rot, order, count, el; self.h, self.w = a.shape
        ys, xs = np.where(a > 0.15); self.ink = (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1) if len(xs) else (0, 0, self.w, self.h)       # where the letters are (the sprite has room round them for the glow and shadow)

    def corners(self, scale=1.0, rot=None):
        r = np.radians(self.rot if rot is None else rot); c, s = np.cos(r), np.sin(r); pts = np.array([[-self.w / 2, -self.h / 2], [self.w / 2, -self.h / 2], [self.w / 2, self.h / 2], [-self.w / 2, self.h / 2]]) * scale
        return np.stack([self.cx + pts[:, 0] * c - pts[:, 1] * s, self.cy + pts[:, 0] * s + pts[:, 1] * c], 1)


    def ink_corners(self):
        """The corners of the letters' own rectangle (not the sprite's padding), turned and placed like the sprite."""
        x0, y0, x1, y1 = self.ink; r = np.radians(self.rot); c, s = np.cos(r), np.sin(r)
        pts = np.array([[x0 - self.w / 2, y0 - self.h / 2], [x1 - self.w / 2, y0 - self.h / 2], [x1 - self.w / 2, y1 - self.h / 2], [x0 - self.w / 2, y1 - self.h / 2]])
        return np.stack([self.cx + pts[:, 0] * c - pts[:, 1] * s, self.cy + pts[:, 0] * s + pts[:, 1] * c], 1)


def _sprite(text, el, H):
    """RGBA (as rgb premultiplied by alpha, and alpha) of `text` styled by `el`, with room round it for the stroke, extrusion, glow and shadow."""
    import cv2
    from PIL import Image, ImageDraw
    px = el['size'] * H; f = font(el['font'], px); asc, desc = f.getmetrics(); tr = el['tracking'] * px; ext = el['extrude']; st = el['stroke']; gl = el['glow']; sh = el['shadow']
    sw = int(round(st['w'] * H)); depth = int(round(ext['depth'] * H)); gr = int(round(gl['r'] * H)); blur = int(round(sh['blur'] * H)); pad = int(px * 0.25) + sw + depth + gr * 2 + blur * 2 + 4
    width = f.getlength(text) + tr * max(len(text) - 1, 0); w = int(width) + 2 * pad; h = asc + desc + 2 * pad
    im = Image.new('L', (w, h), 0); dr = ImageDraw.Draw(im)
    if tr == 0: dr.text((pad, pad), text, font=f, fill=255)
    else:
        for i, ch in enumerate(text): dr.text((pad + f.getlength(text[:i]) + tr * i, pad), ch, font=f, fill=255)
    m = np.asarray(im, np.float32) / 255.0; full = m
    if sw > 0: k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * sw + 1, 2 * sw + 1)); full = np.maximum(m, cv2.dilate(m, k))
    layers = []                                                                                                    # (colour, alpha) bottom to top
    if gl['opacity'] > 0 and gr > 0: k = gr * 2 + 1; layers.append((hex_rgb(gl['color']), np.clip(cv2.GaussianBlur(full, (k, k), 0) * 2.0, 0, 1) * gl['opacity']))
    if sh['opacity'] > 0:
        dy = int(round(sh['dy'] * H)); M = np.float32([[1, 0, 0], [0, 1, dy]]); s = cv2.warpAffine(full, M, (w, h)); k = max(blur * 2 + 1, 1); s = cv2.GaussianBlur(s, (k, k), 0) if k > 1 else s; layers.append(((0.0, 0.0, 0.0), s * sh['opacity']))
    if depth > 0:
        ang = np.radians(ext['angle']); acc = np.zeros_like(full)
        for k_ in range(1, depth + 1): acc = np.maximum(acc, cv2.warpAffine(full, np.float32([[1, 0, np.cos(ang) * k_], [0, 1, np.sin(ang) * k_]]), (w, h)))
        layers.append((hex_rgb(ext['color']), acc))
    if sw > 0: layers.append((hex_rgb(st['color']), full))
    fl = el['fill']; c1, c2 = np.array(hex_rgb(fl['c1']), np.float32), np.array(hex_rgb(fl['c2']), np.float32)
    if fl['type'] == 'gradient':
        ang = np.radians(fl['angle']); yy, xx = np.mgrid[0:h, 0:w].astype(np.float32); t = (xx - w / 2) * np.cos(ang) + (yy - h / 2) * np.sin(ang); span = (abs(np.cos(ang)) * w + abs(np.sin(ang)) * h) / 2; t = np.clip(t / max(span, 1) * 0.5 + 0.5, 0, 1)[..., None]; col = c1 * (1 - t) + c2 * t
    else: col = np.broadcast_to(c1, (h, w, 3))
    layers.append((col, m))
    rgb = np.zeros((h, w, 3), np.float32); a = np.zeros((h, w), np.float32)
    for c, al in layers:
        c = np.asarray(c, np.float32); c = c if c.ndim == 3 else np.broadcast_to(c, (h, w, 3)); rgb = rgb * (1 - al[..., None]) + c * al[..., None] * 1.0; a = a + al * (1 - a)
        rgb = rgb  # premultiplied by construction below
    return rgb, np.clip(a, 0, 1), pad, width, (asc, desc)


class Title:
    """The laid-out word art for a frame size: `apply(img, t)` composites it at shot time `t` seconds."""
    def __init__(self, spec, W, H, duration):
        self.spec = s = merge(spec); self.W, self.H, self.T = W, H, float(duration); end = s['timing'].get('end_s'); self.end = float(end) if end else self.T - 0.4; self.start = float(s['timing'].get('start_s', 0.6))
        self.elements = s['elements'] if s['elements'] else from_block(spec, W, H, duration); self.pieces = []; self.out_s = float(s['animation'].get('out_s', 0.6))
        for ei, el in enumerate(self.elements): self._build(ei, el)
        pts = np.concatenate([p.corners(1.6) for p in self.pieces]) if self.pieces else np.array([[0, 0], [W, H]], float); self.box = (max(float(pts[:, 0].min()), 0), max(float(pts[:, 1].min()), 0), min(float(pts[:, 0].max()), W), min(float(pts[:, 1].max()), H))

    def _build(self, ei, el):
        H, W = self.H, self.W; text = el['text']; text = {'upper': text.upper(), 'lower': text.lower(), 'title': text.title()}.get(el['case'], text)
        if not text.strip(): return
        px = el['size'] * H; f = font(el['font'], px); tr = el['tracking'] * px; width = f.getlength(text) + tr * max(len(text) - 1, 0)
        if width > W * 0.94: el = dict(el, size=el['size'] * W * 0.94 / width); px = el['size'] * H; f = font(el['font'], px); tr = el['tracking'] * px; width = f.getlength(text) + tr * max(len(text) - 1, 0)
        self.elements[ei] = el; cx = el['x'] * W + {'c': 0.0, 'l': width / 2, 'r': -width / 2}.get(el['anchor'], 0.0); cy = el['y'] * H; rot = np.radians(el['rot']); cr, sr = np.cos(rot), np.sin(rot)
        asc, desc = f.getmetrics()
        if el['per'] == 'char' or abs(el['curve']) > 0.02:
            n = len(text); theta = el['curve'] * 1.4; R = width / theta if abs(theta) > 1e-3 else None
            for i, ch in enumerate(text):
                if not ch.strip(): continue
                rgb, a, pad, cw, _ = _sprite(ch, dict(el, tracking=0.0), H); off = f.getlength(text[:i]) + tr * i + f.getlength(ch) / 2 - width / 2
                if R: phi = off / R; lx = R * np.sin(phi); ly = R * (1 - np.cos(phi)) * (1 if theta > 0 else 1); cang = np.degrees(phi)
                else: lx, ly, cang = off, 0.0, 0.0
                wx = cx + lx * cr - ly * sr; wy = cy + lx * sr + ly * cr
                self.pieces.append(Piece(rgb, a, wx, wy, el['rot'] + cang, i, n, dict(el, _ei=ei)))
        else:
            rgb, a, pad, cw, _ = _sprite(text, el, H); self.pieces.append(Piece(rgb, a, cx, cy, el['rot'], 0, 1, dict(el, _ei=ei)))

    def visible(self, t): return self.start <= t <= self.end + 0.3

    def _state(self, p, t):
        el = p.el; kin, kout = el['in'], el['out']; in_s = max(float(el['in_s']), 0.05); per = el['per']
        delay = self.start + el['delay'] + (p.order * min(0.08, in_s * 0.7 / max(p.count, 1)) if per == 'char' else 0.0)
        uin = float(np.clip((t - delay) / in_s, 0, 1)); uout = float(np.clip((t - (self.end - self.out_s + el['delay'] * 0.2)) / self.out_s, 0, 1)); e = ease(el['ease'], uin)
        if kin == 'drop': e = ease('bounce', uin)
        elif kin in ('pop', 'zoom'): e = ease('out_back', uin)
        al, dx, dy, sc, rot, blur, track, clip = (min(uin * 2.5, 1.0) if kin in ('pop', 'zoom', 'spin', 'drop') else e), 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0; px = el['size'] * self.H
        if kin == 'rise': dy = (1 - e) * 0.5 * px
        elif kin == 'drop': dy = -(1 - e) * 0.9 * self.H * el['size'] * 3
        elif kin == 'pop': sc = 1.5 - 0.5 * e
        elif kin == 'zoom': sc = 0.25 + 0.75 * e
        elif kin == 'spin': rot = (1 - e) * 35; sc = 0.7 + 0.3 * e
        elif kin == 'blur_in': blur = (1 - e) * 0.16 * px
        elif kin == 'track_in': track = (1 - e) * 0.5
        elif kin == 'type': al = 1.0 if uin > 0 else 0.0
        elif kin == 'wipe': al = 1.0 if uin > 0 else 0.0; clip = e
        elif kin == 'slide': dx = (1 - e) * -0.6 * p.w
        uo = ease('in_out', uout)
        if kout == 'fade': al *= 1 - uo
        elif kout == 'rise': dy -= uo * 0.4 * px; al *= 1 - uo
        elif kout == 'blur': blur += uo * 0.16 * px; al *= 1 - uo
        elif kout == 'shrink': sc *= 1 - 0.5 * uo; al *= 1 - uo
        return dict(alpha=al, dx=dx, dy=dy, scale=sc, rot=rot, blur=blur, track=track, clip=clip)

    def apply(self, img, t):
        """img: (H, W, 3) uint8 or uint16 RGB; returns a copy with the words at time t (unchanged outside the rectangle they can reach)."""
        if not self.visible(t) or not self.pieces: return img
        import cv2
        H, W = img.shape[:2]; top = 255.0 if img.dtype == np.uint8 else 65535.0; x0, y0, x1, y1 = (int(self.box[0]), int(self.box[1]), int(np.ceil(self.box[2])), int(np.ceil(self.box[3])))
        out = img.copy(); region = out[y0:y1, x0:x1].astype(np.float32) / top; sc = self.spec['scrim']; first = 0.0
        states = [(p, self._state(p, t)) for p in self.pieces]; first = max([s['alpha'] for _, s in states] or [0.0])
        if sc.get('opacity', 0) > 0 and sc.get('side', 'none') != 'none' and first > 0:
            ys = (np.arange(y0, y1) / H)[:, None]; xs = (np.arange(x0, x1) / W)[None, :]; dist = {'bottom': (1 - ys) + 0 * xs, 'top': ys + 0 * xs, 'left': xs + 0 * ys, 'right': (1 - xs) + 0 * ys}[sc['side']]
            region *= 1 - (sc['opacity'] * first) * (np.clip(1.0 - dist / max(sc.get('extent', 0.5), 0.05), 0, 1) ** 1.5)[..., None]
        for p, s in states:
            if s['alpha'] <= 0.004: continue
            rgb, a = p.rgb, p.a
            if s['clip'] < 1.0: ramp = np.clip((s['clip'] * 1.04 * p.w - np.arange(p.w)) / max(0.04 * p.w, 2), 0, 1).astype(np.float32); a = a * ramp[None, :]; rgb = rgb * ramp[None, :, None]
            if s['track']:                                                                                          # (letters of a word that is one sprite cannot be spread: the preset only applies per letter)
                pass
            M = cv2.getRotationMatrix2D((p.w / 2, p.h / 2), -(p.rot + s['rot']), s['scale']); M[0, 2] += p.cx + s['dx'] - p.w / 2; M[1, 2] += p.cy + s['dy'] - p.h / 2
            if s['track'] and p.count > 1: M[0, 2] += s['track'] * p.el['size'] * H * (p.order - p.count / 2)
            pts = cv2.transform(np.array([[[0, 0], [p.w, 0], [p.w, p.h], [0, p.h]]], np.float32), M)[0]; bx0, by0 = max(int(pts[:, 0].min()) - 2, x0), max(int(pts[:, 1].min()) - 2, y0); bx1, by1 = min(int(np.ceil(pts[:, 0].max())) + 2, x1), min(int(np.ceil(pts[:, 1].max())) + 2, y1)
            if bx1 <= bx0 or by1 <= by0: continue
            M2 = M.copy(); M2[0, 2] -= bx0; M2[1, 2] -= by0; sz = (bx1 - bx0, by1 - by0); ra = cv2.warpAffine(a, M2, sz, flags=cv2.INTER_LINEAR); rr = cv2.warpAffine(rgb, M2, sz, flags=cv2.INTER_LINEAR)
            if s['blur'] > 0.5: k = int(s['blur']) * 2 + 1; ra = cv2.GaussianBlur(ra, (k, k), 0); rr = cv2.GaussianBlur(rr, (k, k), 0)
            sub = region[by0 - y0:by1 - y0, bx0 - x0:bx1 - x0]; region[by0 - y0:by1 - y0, bx0 - x0:bx1 - x0] = sub * (1 - ra[..., None] * s['alpha']) + rr * s['alpha']
        out[y0:y1, x0:x1] = np.clip(region * top + 0.5, 0, top).astype(img.dtype); return out


def text_bbox_fraction(title):
    """The words' rectangle (where they can reach) as fractions of the frame: (x0, y0, x1, y1)."""
    x0, y0, x1, y1 = title.box; return (x0 / title.W, y0 / title.H, x1 / title.W, y1 / title.H)


def piece_boxes(title, margin=0.0):
    """[(element index, (x0, y0, x1, y1) fractions)] of every piece at rest: the extent of its letters (rotated), without the room round them."""
    out = []
    for p in title.pieces:
        c = p.ink_corners(); out.append((p.el['_ei'], (float(c[:, 0].min()) / title.W, float(c[:, 1].min()) / title.H, float(c[:, 0].max()) / title.W, float(c[:, 1].max()) / title.H)))
    return out
