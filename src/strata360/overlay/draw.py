"""Drawing for the overlay: text, icons, the marker and the rounded map frames, as RGBA patches (uint8 numpy arrays), and laying patches onto a film frame.

Pillow draws the text (FreeType, with the bundled Inter font: SIL Open Font License, fonts/OFL.txt); shapes are drawn at four times their size and reduced, so their edges are smooth at
any size, and OpenCV draws the route lines (anti-aliased, sub-pixel). Text and icons get a soft dark shadow so they read on snow and sky as well as on rock. Digits are set in equal-width
cells, so a changing number does not shift sideways."""
import functools, math, os
import numpy as np, cv2
from PIL import Image, ImageDraw, ImageFilter, ImageFont

FONT_DIR = os.path.join(os.path.dirname(__file__), 'fonts')
VALUE_FONT, LABEL_FONT = os.path.join(FONT_DIR, 'Inter-SemiBold.ttf'), os.path.join(FONT_DIR, 'Inter-Medium.ttf')
SS = 4                                       # supersampling of shapes


@functools.lru_cache(maxsize=64)
def font(path, px): return ImageFont.truetype(path, max(1, int(round(px))))


def shadowed(mask, fill, px, strength=0.65, shadow=(0, 0, 0)):
    """RGBA patch of `fill` through the L-mode `mask` with a soft shadow around it; returns (rgba, pad), the patch being `pad` pixels larger than the mask on every side."""
    pad = max(2, int(math.ceil(px / 9))); m = Image.new('L', (mask.width + 2 * pad, mask.height + 2 * pad)); m.paste(mask, (pad, pad))
    sh = m.filter(ImageFilter.MaxFilter(3)).filter(ImageFilter.GaussianBlur(max(1.0, px / 18)))
    a_t = np.asarray(m, np.float32) / 255.0; a_s = np.asarray(sh, np.float32) / 255.0 * strength; a = a_t + a_s * (1 - a_t)
    with np.errstate(invalid='ignore', divide='ignore'): k = np.where(a > 0, a_t / a, 0.0)
    rgb = np.asarray(fill, np.float32)[None, None, :3] * k[..., None] + np.asarray(shadow, np.float32)[None, None, :3] * (1 - k[..., None])
    return np.dstack([rgb, a * 255.0 * (fill[3] / 255.0 if len(fill) > 3 else 1.0)]).round().astype(np.uint8), pad


def text(s, px, path=VALUE_FONT, fill=(255, 255, 255), tabular=True, shadow=(0, 0, 0)):
    """(rgba, pad, width): the text with its top at the font's ascender line; `width` is the advance of the text alone (the patch adds `pad` around it)."""
    f = font(path, px); asc, desc = f.getmetrics(); cell = max(f.getlength(d) for d in '0123456789')
    xs, x = [], 0.0
    for ch in s:
        w = cell if tabular and ch.isdigit() else f.getlength(ch); xs.append(x + (w - f.getlength(ch)) / 2); x += w
    if not tabular: xs, x = [0.0], f.getlength(s)
    w = max(1, int(math.ceil(x))); m = Image.new('L', (w + 2, asc + desc)); d = ImageDraw.Draw(m)
    for ch, cx in zip(s if tabular else [s], xs): d.text((cx, asc), ch, font=f, fill=255, anchor='ls')
    rgba, pad = shadowed(m, fill, px, strength=0.9 if shadow != (0, 0, 0) else 0.65, shadow=shadow); return rgba, pad, x


def _ss(size, draw_fn):
    """L mask of `size` (w, h) drawn at SS times the size by draw_fn(ImageDraw, scale) and reduced."""
    big = Image.new('L', (size[0] * SS, size[1] * SS)); draw_fn(ImageDraw.Draw(big), SS); return big.resize(size, Image.LANCZOS)


def _poly(n, f):
    t = np.linspace(0, 2 * np.pi, n, endpoint=False); return list(zip(*f(t)))


ICONS = {   # shapes in a unit square (0..1), drawn white unless the icon gives a colour
    'mountain': dict(polys=[[(0.02, 0.86), (0.36, 0.24), (0.56, 0.58), (0.68, 0.42), (0.98, 0.86)]]),
    'slope': dict(polys=[[(0.06, 0.84), (0.94, 0.84), (0.94, 0.22)]]),
    'slope_down': dict(polys=[[(0.06, 0.84), (0.94, 0.84), (0.06, 0.22)]]),
    'heart': dict(polys=[_poly(96, lambda t: (0.5 + 0.028 * 16 * np.sin(t) ** 3, 0.47 - 0.028 * (13 * np.cos(t) - 5 * np.cos(2 * t) - 2 * np.cos(3 * t) - np.cos(4 * t))))], fill=(255, 84, 96)),
}


def icon(name, px):
    """(rgba, pad) of a named icon `px` pixels square."""
    spec = ICONS[name]; s = max(4, int(round(px)))
    m = _ss((s, s), lambda d, k: [d.polygon([(x * s * k, y * s * k) for x, y in p], fill=255) for p in spec['polys']])
    return shadowed(m, spec.get('fill', (255, 255, 255)), px)


def marker(radius, fill=(0, 102, 255), edge=(0, 0, 0)):
    """RGBA disc (a position marker) with a dark edge, 2*radius+3 pixels square, centred."""
    s = int(math.ceil(radius * 2)) + 3; c = s / 2; e = max(1.0, radius / 4)
    outer = np.asarray(_ss((s, s), lambda d, k: d.ellipse([(c - radius) * k, (c - radius) * k, (c + radius) * k, (c + radius) * k], fill=255)), np.float32) / 255
    inner = np.asarray(_ss((s, s), lambda d, k: d.ellipse([(c - radius + e) * k, (c - radius + e) * k, (c + radius - e) * k, (c + radius - e) * k], fill=255)), np.float32) / 255
    rgb = np.asarray(edge, np.float32) * (1 - inner[..., None]) + np.asarray(fill, np.float32) * inner[..., None]
    return np.dstack([rgb, outer * 255]).round().astype(np.uint8)


@functools.lru_cache(maxsize=16)
def rounded(size, radius, width=0.0):
    """Float mask (0..1) of a rounded square `size` px with corner `radius`; with `width`, only its outline ring of that width."""
    r = radius
    def fill(d, k, inset=0.0): d.rounded_rectangle([inset * k, inset * k, (size - inset) * k - 1, (size - inset) * k - 1], radius=max(0, (r - inset)) * k, fill=255)
    a = np.asarray(_ss((size, size), fill), np.float32) / 255
    if not width: return a
    return np.clip(a - np.asarray(_ss((size, size), lambda d, k: fill(d, k, width)), np.float32) / 255, 0, 1)


def framed(rgb, radius, opacity, outline=(0, 0, 0), outline_w=1.5):
    """A square map picture (H x W x 3 uint8) as an RGBA patch: rounded corners, see-through by `opacity`, with an opaque outline."""
    s = rgb.shape[0]; body = rounded(s, radius) * opacity; ring = rounded(s, radius, outline_w) if outline is not None and outline_w > 0 else np.zeros((s, s), np.float32)
    a = ring + body * (1 - ring)
    with np.errstate(invalid='ignore', divide='ignore'): k = np.where(a > 0, ring / a, 0.0)[..., None]
    col = rgb.astype(np.float32) * (1 - k) + np.asarray(outline if outline is not None else (0, 0, 0), np.float32) * k
    return np.dstack([col, a * 255]).round().astype(np.uint8)


def route_line(img, u, v, colour=(230, 20, 20), width=3.0):
    """Draw the route (picture coordinates u, v; NaN breaks it) on an RGB uint8 image in place, anti-aliased. Points far outside the picture are left out."""
    h, w = img.shape[:2]; m = 4 * max(w, h); keep = np.isfinite(u) & np.isfinite(v) & (u > -m) & (u < w + m) & (v > -m) & (v < h + m)
    pts = np.round(np.nan_to_num(np.stack([u, v], 1)) * 16).astype(np.int64); idx = np.flatnonzero(keep)
    if not len(idx): return img
    runs = np.split(idx, np.flatnonzero(np.diff(idx) > 1) + 1)
    cv2.polylines(img, [pts[r].astype(np.int32).reshape(-1, 1, 2) for r in runs if len(r) > 1], False, tuple(int(c) for c in colour), max(1, int(round(width))), cv2.LINE_AA, 4)
    return img


def line_mask(shape, u, v, width, ss=4):
    """Coverage (0..1, float32) of the route (picture coordinates u, v; NaN breaks it) drawn `width` pixels thick: fractions of a pixel work (it is drawn `ss` times larger and averaged down). At most a few thousand points of a long route are used."""
    h, w = shape[:2]; m = 4 * max(w, h); keep = np.isfinite(u) & np.isfinite(v) & (u > -m) & (u < w + m) & (v > -m) & (v < h + m); idx = np.flatnonzero(keep)
    im = Image.new('L', (w * ss, h * ss), 0); dr = ImageDraw.Draw(im); th = max(1, int(round(width * ss)))
    for run in (np.split(idx, np.flatnonzero(np.diff(idx) > 1) + 1) if len(idx) else []):
        if len(run) < 2: continue
        run = run[::max(1, len(run) // 6000)] if len(run) > 6000 else run
        dr.line([(float(u[k]) * ss, float(v[k]) * ss) for k in run], fill=255, width=th, joint='curve')
    return np.asarray(im.reduce(ss), np.float32) / 255


def line_layer(shape, layers, clip=None, opacity=1.0):
    """RGBA patch of route lines [(u, v, width, colour), ...] painted in that order (later over earlier, by coverage), cut by the 0..1 mask `clip` and made see-through by `opacity`; the lines are not part of any map picture, so their opacity is their own."""
    h, w = shape[:2]; prem = np.zeros((h, w, 3), np.float32); a = np.zeros((h, w), np.float32)
    for u, v, width, colour in layers:
        m = line_mask(shape, u, v, width); prem = prem * (1 - m[..., None]) + np.asarray(colour, np.float32) * m[..., None]; a = a * (1 - m) + m
    with np.errstate(invalid='ignore', divide='ignore'): rgb = np.where(a[..., None] > 0, prem / a[..., None], 0.0)
    return np.dstack([rgb, a * (clip if clip is not None else 1.0) * opacity * 255]).round().astype(np.uint8)


def blend_line(img, u, v, colour, width):
    """Like route_line, but for any thickness: the route laid over an RGB uint8 image in place by its coverage."""
    a = line_mask(img.shape, u, v, width)[..., None]; img[:] = np.round(img.astype(np.float32) * (1 - a) + np.asarray(colour, np.float32) * a).astype(np.uint8); return img


@functools.lru_cache(maxsize=256)
def arrow(size, angle, fill=(0, 102, 255), edge=(0, 0, 0)):
    """RGBA arrow head `size` px (rounded up to 4) across, centred, pointing `angle` degrees clockwise from up (north): the pointing end is further from the middle than the base."""
    s = int(math.ceil(size)) + 4; c = s / 2; r = size / 2; a = math.radians(angle)
    def rot(x, y): return (c + (x * math.cos(a) - y * math.sin(a)) * r, c + (x * math.sin(a) + y * math.cos(a)) * r)
    shape = [(0.0, -1.0), (0.78, 0.85), (0.0, 0.42), (-0.78, 0.85)]                                   # tip, right wing, notch, left wing
    outer = np.asarray(_ss((s, s), lambda d, k: d.polygon([(x * k, y * k) for x, y in (rot(*p) for p in shape)], fill=255)), np.float32) / 255
    e = max(1, int(round(r / 7))); inner = cv2.erode(outer, np.ones((e * 2 + 1,) * 2, np.uint8))                                  # (a thin dark edge)
    rgb = np.asarray(edge, np.float32) * (1 - inner[..., None]) + np.asarray(fill, np.float32) * inner[..., None]
    return np.dstack([rgb, outer * 255]).round().astype(np.uint8)


@functools.lru_cache(maxsize=64)
def badge(label, diameter, kind='number'):
    """RGBA round badge `diameter` px across (a little more with the edge): `number` a blue disc with the label in white, `start` a green disc with a play triangle, `finish` a chequered disc; all with a white edge."""
    s = int(math.ceil(diameter)) + 4; c = s / 2; r = diameter / 2; e = max(1.0, diameter / 9)
    outer = np.asarray(_ss((s, s), lambda d, k: d.ellipse([(c - r) * k, (c - r) * k, (c + r) * k, (c + r) * k], fill=255)), np.float32) / 255
    inner = np.asarray(_ss((s, s), lambda d, k: d.ellipse([(c - r + e) * k, (c - r + e) * k, (c + r - e) * k, (c + r - e) * k], fill=255)), np.float32) / 255
    if kind == 'finish':
        yy, xx = np.mgrid[:s, :s]; g = max(2.0, (2 * r) / 4); chk = (((xx - (c - r)) // g + (yy - (c - r)) // g) % 2 == 0).astype(np.float32)[..., None]; body = np.repeat((1 - chk) * 255, 3, axis=2)
    else:
        fill = (22, 163, 74) if kind == 'start' else (29, 78, 216); body = np.broadcast_to(np.asarray(fill, np.float32), (s, s, 3)).copy()
        if kind == 'start':
            tri = np.asarray(_ss((s, s), lambda d, k: d.polygon([((c - r * 0.3) * k, (c - r * 0.5) * k), ((c - r * 0.3) * k, (c + r * 0.5) * k), ((c + r * 0.55) * k, c * k)], fill=255)), np.float32) / 255
            body = body * (1 - tri[..., None]) + 255 * tri[..., None]
        else:
            f = font(VALUE_FONT, max(6, int(round(diameter * 0.62)))); m = Image.new('L', (s, s)); ImageDraw.Draw(m).text((c, c), str(label), font=f, fill=255, anchor='mm'); tm = np.asarray(m, np.float32)[..., None] / 255
            body = body * (1 - tm) + 255 * tm
    rgb = 255 * (1 - inner[..., None]) + body * inner[..., None]
    return np.dstack([rgb, outer * 255]).round().astype(np.uint8)


def composite(frame, patches):
    """Lay RGBA patches [(x, y, rgba uint8)] onto an RGB frame (uint8 or uint16 code values) in place; parts outside the frame are cut off."""
    top = 65535.0 if frame.dtype == np.uint16 else 255.0; H, W = frame.shape[:2]
    for x, y, p in patches:
        x, y = int(round(x)), int(round(y)); x0, y0, x1, y1 = max(x, 0), max(y, 0), min(x + p.shape[1], W), min(y + p.shape[0], H)
        if x0 >= x1 or y0 >= y1: continue
        q = p[y0 - y:y1 - y, x0 - x:x1 - x]; a = q[..., 3:4].astype(np.float32) / 255.0
        if not a.any(): continue
        reg = frame[y0:y1, x0:x1]; reg[:] = np.round(reg.astype(np.float32) * (1 - a) + q[..., :3].astype(np.float32) * (top / 255.0) * a).astype(frame.dtype)
    return frame
