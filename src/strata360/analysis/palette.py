"""`palette` stage: a colour scheme for each clip, for the animated and overlaid text. From frames of the clip's proxy it finds the colours that are really there and builds a small scheme around them:

  base      the clip's dominant hue, at a lightness that reads against the footage (the colour the text borrows from the picture)
  accent    the complementary hue (180 degrees round the hue circle), the same readability: the contrasting colour for a second word, an underline or a glow
  support   a split-complement (150 degrees on), a third voice for small text
  light     / dark   near-white and near-black tinted with the base hue: the neutral fills and the outlines
  outline   the neutral of the opposite tone to the footage, for strokes and shadows
  gradient  base to accent, for a gradient fill

Every colour of the scheme keeps a WCAG contrast of at least MIN_CONTRAST against the footage's typical colours (its darkest and brightest quartile of lightness are both tried, and the text colours are moved towards light or dark, never changed in hue, until they pass). A clip with no real colour in it (grey fog, night) borrows the hue from the sun/sky convention: warm amber with a cool teal accent.

Output `palette.json`: the measured colours (`colours`: hex, share, chroma, lightness), the `mood` (light or dark, vivid or muted, warm or cool) and the `scheme`. `for_prompt` writes it as the words the title designer reads (edit/title_design.py)."""
import json, math, os, subprocess
import numpy as np

from strata360.render import titles as TT

FILE = 'palette.json'
SAMPLES = 16                      # frames looked at, evenly through the clip
W, H = 480, 240                   # the proxy frame as read (equirect, 2:1)
BAND = (0.25, 0.75)               # the rows kept: the horizon band, where a flat view of the film looks (the poles are stretched sky and ground)
K = 6                             # clusters of the pooled pixels
MIN_CHROMA = 14.0                 # a cluster this colourful (Lab chroma) can supply the hue; below it the clip counts as grey
MIN_CONTRAST = 4.5                # WCAG AA for text; the text colours are moved in lightness until they reach it against the footage
FALLBACK_HUE = 55.0               # amber, in LCh degrees, when the clip has no colour of its own
MAX_WEIGHT_L = (12.0, 95.0)       # lightness of a cluster outside this (black, white) is not a colour to borrow


def _rgb_to_lab(rgb):
    """rgb: (..., 3) float 0..1 -> Lab (L 0..100)."""
    import cv2
    a = np.ascontiguousarray(rgb, np.float32).reshape(-1, 1, 3); return cv2.cvtColor(a, cv2.COLOR_RGB2LAB).reshape(rgb.shape)


def lch_to_rgb(L, C, h):
    """(r, g, b) in 0..1 of the LCh colour; the chroma is lowered until it fits inside sRGB, so the hue and the lightness are kept."""
    import cv2
    L = float(np.clip(L, 0.0, 100.0))
    for c in np.linspace(C, 0.0, 24):
        a, b = c * math.cos(math.radians(h)), c * math.sin(math.radians(h)); lab = np.array([[[L, a, b]]], np.float32); rgb = cv2.cvtColor(lab, cv2.COLOR_LAB2RGB)[0, 0]
        if rgb.min() >= -0.002 and rgb.max() <= 1.002: return tuple(float(v) for v in np.clip(rgb, 0, 1))
    return tuple(float(v) for v in np.clip(rgb, 0, 1))


def to_hex(rgb): return '#%02x%02x%02x' % tuple(int(round(float(v) * 255)) for v in rgb)


def lch_of(rgb):
    L, a, b = _rgb_to_lab(np.array(rgb, np.float32).reshape(1, 3))[0]; return float(L), float(math.hypot(a, b)), float(math.degrees(math.atan2(b, a)) % 360)


def dominant(pixels, k=K):
    """The k main colours of `pixels` ((n, 3) float RGB 0..1): [dict(hex, share, L, C, h)] by share, largest first. The clustering is in Lab, where distance is closer to what the eye sees."""
    import cv2
    lab = _rgb_to_lab(pixels).astype(np.float32); k = int(min(k, len(lab)))
    if k < 1: return []
    _, lab_idx, cen = cv2.kmeans(lab, k, None, (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 20, 0.5), 3, cv2.KMEANS_PP_CENTERS)
    share = np.bincount(lab_idx.ravel(), minlength=k) / len(lab_idx); out = []
    for i in np.argsort(-share):
        L, a, b = (float(v) for v in cen[i]); C = math.hypot(a, b); h = math.degrees(math.atan2(b, a)) % 360
        rgb = lch_to_rgb(L, C, h); out.append(dict(hex=to_hex(rgb), share=round(float(share[i]), 3), L=round(L, 1), C=round(C, 1), h=round(h, 1)))
    return out


def pick_hue(colours):
    """(hue, chroma, found): the hue that stands for the clip. Each cluster counts by its share times its chroma (a big dull cluster loses to a smaller vivid one, but not to a speck), black and white clusters not at all.
    `found` is False when nothing in the clip is colourful enough; the hue is then FALLBACK_HUE."""
    best = None
    for c in colours:
        if c['C'] < MIN_CHROMA or not (MAX_WEIGHT_L[0] <= c['L'] <= MAX_WEIGHT_L[1]): continue
        w = c['share'] * c['C']
        if best is None or w > best[0]: best = (w, c)
    if best is None: return FALLBACK_HUE, 0.0, False
    return best[1]['h'], best[1]['C'], True


def _passes(rgb, backs, need): return min(TT.contrast(rgb, b) for b in backs) >= need


def readable(L, C, h, backs, need=MIN_CONTRAST):
    """The LCh colour moved in lightness (the hue kept) until it has contrast `need` against every colour of `backs`: towards light when the footage is mostly dark, towards dark when it is bright. When both ends fail
    (footage of both very light and very dark parts) the end that does better is returned: the outline carries the rest."""
    rgb = lch_to_rgb(L, C, h)
    if _passes(rgb, backs, need): return rgb
    mean_l = np.mean([TT.luminance(b) for b in backs]); step = 2.0 if mean_l < 0.35 else -2.0; best = (min(TT.contrast(rgb, b) for b in backs), rgb); l = L
    while 0.0 <= l <= 100.0:
        l += step; cand = lch_to_rgb(l, C, h); worst = min(TT.contrast(cand, b) for b in backs)
        if worst > best[0]: best = (worst, cand)
        if worst >= need: return cand
    return best[1]


def build_scheme(colours, light_q, dark_q):
    """The scheme for a clip from its measured `colours` and the two ends of its lightness: `light_q` and `dark_q`, (r, g, b) 0..1 colours of the brightest and darkest quarter of the frames' pixels (the backgrounds the text will have to stand on)."""
    hue, chroma, found = pick_hue(colours); backs = [light_q, dark_q]; mean_l = np.mean([TT.luminance(b) for b in backs]); bright = mean_l > 0.35
    vivid = float(np.clip(max(chroma, 30.0) * 1.2, 40.0, 90.0)) if found else 55.0                                   # the scheme is more colourful than the footage: text is a signal on it
    comp_h, split_h = (hue + 180.0) % 360, (hue + 150.0) % 360
    if not found: comp_h = (FALLBACK_HUE + 190.0) % 360                                                              # amber with teal
    base = readable(70.0 if not bright else 38.0, vivid, hue, backs); accent = readable(72.0 if not bright else 36.0, vivid, comp_h, backs); support = readable(78.0 if not bright else 32.0, vivid * 0.7, split_h, backs)
    light = lch_to_rgb(96.0, 6.0, hue); dark = lch_to_rgb(10.0, 8.0, hue); outline = dark if bright else light
    if not _passes(light, backs, 3.0) and not _passes(dark, backs, 3.0): outline = dark if mean_l > 0.18 else light
    sw = swatches(hue, vivid, found)
    scheme = dict(swatches=sw, base=to_hex(base), accent=to_hex(accent), support=to_hex(support), light=to_hex(light), dark=to_hex(dark), outline=to_hex(outline), gradient=[to_hex(base), to_hex(accent)], hue=round(hue, 1), complement_hue=round(comp_h, 1), found=found)
    scheme['contrast'] = {k: round(min(TT.contrast(TT.hex_rgb(scheme[k]), b) for b in backs), 1) for k in ('base', 'accent', 'support', 'light', 'dark')}; return scheme


HARMONY = (('base', 0.0), ('accent', 180.0), ('support', 150.0), ('analogous', 30.0), ('triad', 120.0))        # colour theory: the hue itself, its complement, the split-complement, an analogous neighbour, a triad corner
TONES = (('light', 88.0, 0.75), ('dark', 18.0, 0.75), ('mid_light', 72.0, 1.0), ('mid_dark', 34.0, 1.0))     # (name, lightness, chroma kept): pale and deep versions for light and dark areas, and the full-colour mid tones


def swatches(hue, chroma, found=True):
    """[dict(role, tone, hex, hue, L)] every colour the text may pick from: each harmony hue at four lightnesses, then the two neutrals tinted with the base hue. A word chooses among them for the area it sits on (`choose`)."""
    out = []
    for role, off in HARMONY:
        h = (hue + off) % 360 if (found or role != 'accent') else (FALLBACK_HUE + 190.0) % 360
        for tone, L, k in TONES: rgb = lch_to_rgb(L, chroma * k, h); out.append(dict(role=role, tone=tone, hex=to_hex(rgb), hue=round(h, 1), L=L))
    for tone, L in (('light', 97.0), ('dark', 9.0)): out.append(dict(role='neutral', tone=tone, hex=to_hex(lch_to_rgb(L, 5.0, hue)), hue=round(hue, 1), L=L))
    return out


def _lum(px): return 0.2126 * _lin(px[:, 0]) + 0.7152 * _lin(px[:, 1]) + 0.0722 * _lin(px[:, 2])


def _lin(c): return np.where(c <= 0.03928, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def pixel_contrast(hex_, lum, pct=20):
    """The contrast of the colour against the pixels behind it (`lum`: their relative luminance), as the `pct` percentile: 80 percent of the area has at least this much. Judging by the worst quarter fails every colour on a busy area (sky above, crowd below);
    a percentile asks for what most of the letters sit on."""
    ls = TT.luminance(TT.hex_rgb(hex_)); hi = np.maximum(lum, ls); lo = np.minimum(lum, ls); return float(np.percentile((hi + 0.05) / (lo + 0.05), pct))


def region_lum(rgb_pixels, n=4000):
    px = np.asarray(rgb_pixels, np.float32).reshape(-1, 3)
    if len(px) > n: px = px[np.random.default_rng(0).choice(len(px), n, replace=False)]
    return _lum(px)


def choose(sw, rgb_pixels, prefer=('base', 'accent'), margin=0.85, exclude=(), against=None, aa=MIN_CONTRAST):
    """(hex, contrast, swatch): the palette colour with the highest contrast against the area behind the word (`pixel_contrast`). Among the colours within `margin` of the best (and at least AA when anything reaches it), the first role of `prefer` wins, so the
    choice stays on the scheme's hues and goes to a neutral only when no hue reads. `exclude`: hexes not to return (the neighbouring word's colour). `against`: a hex to contrast with instead of the pixels (for the outline: the fill)."""
    lum = region_lum(rgb_pixels) if against is None else np.array([TT.luminance(TT.hex_rgb(against))]); sc = [(pixel_contrast(s['hex'], lum), s) for s in sw if s['hex'] not in exclude]
    if not sc: return None, 0.0, None
    best = max(c for c, _ in sc); floor = max(best * margin, min(best, aa)); ok = [(c, s) for c, s in sc if c >= floor]
    ok.sort(key=lambda cs: (prefer.index(cs[1]['role']) if cs[1]['role'] in prefer else len(prefer) + (cs[1]['role'] == 'neutral'), -cs[0])); c, s = ok[0]; return s['hex'], round(c, 2), s


def choose_coloured(sw, rgb_pixels, prefer=('base', 'accent'), exclude=(), aa=2.5):
    """(hex, contrast, swatch) for coloured lettering: only the saturated swatches (the hues at their mid tones, then at their pale and deep tones when no mid tone reaches `aa`), because the outline and the drop shadow carry the legibility, so the fill may be as colourful
    as the scheme allows and needs only a modest contrast with the picture. When no hue reaches `aa` the best of all the hues is still used, never a neutral."""
    for tones in (('mid_light', 'mid_dark'), ('light', 'dark')):
        pool = [x for x in sw if x['role'] != 'neutral' and x['tone'] in tones]; hex_, ct, sel = choose(pool, rgb_pixels, prefer, exclude=exclude, aa=aa)
        if hex_ and ct >= aa: return hex_, ct, sel
    pool = [x for x in sw if x['role'] != 'neutral']; return choose(pool, rgb_pixels, prefer, exclude=exclude, aa=aa)               # none reaches `aa`: the best hue there is; the outline and shadow do the rest


def mood(colours, light_q, dark_q, scheme):
    """Words for the clip: light (bright or dark footage), vivid or muted, warm or cool."""
    mean_l = float(np.mean([TT.luminance(b) for b in (light_q, dark_q)])); chroma = sum(c['share'] * c['C'] for c in colours); h = scheme['hue']
    warm = (h < 100 or h >= 320) and scheme['found']; return dict(tone='bright' if mean_l > 0.35 else 'dark', saturation='vivid' if chroma > 28 else 'muted' if chroma > 12 else 'grey', temperature=('warm' if warm else 'cool') if scheme['found'] else 'neutral')


def analyse_pixels(frames_rgb):
    """The palette document of a clip from its frames (a list of (h, w, 3) uint8 RGB pictures): `colours`, `mood`, `scheme`. Raises RuntimeError without frames."""
    if not len(frames_rgb): raise RuntimeError('no frames to take a palette from')
    px = []
    for f in frames_rgb:
        r0, r1 = int(BAND[0] * f.shape[0]), max(int(BAND[1] * f.shape[0]), int(BAND[0] * f.shape[0]) + 1); px.append(f[r0:r1:2, ::2].reshape(-1, 3))
    px = np.concatenate(px).astype(np.float32) / 255.0; rng = np.random.default_rng(0)
    if len(px) > 120000: px = px[rng.choice(len(px), 120000, replace=False)]
    lum = 0.2126 * px[:, 0] + 0.7152 * px[:, 1] + 0.0722 * px[:, 2]; order = np.argsort(lum); q = max(len(px) // 4, 1)
    dark_q = tuple(float(v) for v in px[order[:q]].mean(0)); light_q = tuple(float(v) for v in px[order[-q:]].mean(0))                    # the typical dark and light parts of the footage
    colours = dominant(px); scheme = build_scheme(colours, light_q, dark_q)
    return dict(colours=colours, backgrounds=dict(light=to_hex(light_q), dark=to_hex(dark_q)), mood=mood(colours, light_q, dark_q, scheme), scheme=scheme)


def frames(path, duration, n=SAMPLES):
    """`n` RGB frames of the proxy, evenly through its `duration` seconds, scaled to W x H (area average), one ffmpeg run reading at the rate that gives n frames."""
    rate = max(n / max(duration, 1e-3), 0.01); cmd = ['ffmpeg', '-v', 'error', '-threads', '2', '-i', path, '-an', '-vf', f'fps={rate:.6f},scale={W}:{H}:flags=area', '-frames:v', str(n), '-pix_fmt', 'rgb24', '-f', 'rawvideo', '-']
    from strata360.pipeline import guard
    p = guard.popen(cmd, stdout=subprocess.PIPE, bufsize=W * H * 3 * 2); size = W * H * 3; out = []
    try:
        while True:
            b = p.stdout.read(size)
            if len(b) < size: break
            out.append(np.frombuffer(b, np.uint8).reshape(H, W, 3).copy())
    finally:
        p.stdout.close(); p.wait()
    return out


def analyse(proxy_path, duration, n=SAMPLES):
    return dict(samples=n, **analyse_pixels(frames(proxy_path, duration, n)))


def load(clip_dir):
    """The clip's palette document, or None when the palette stage has not made it."""
    try: return json.load(open(os.path.join(clip_dir, FILE)))
    except (OSError, ValueError): return None


def for_prompt(doc):
    """The scheme as the sentence the title designer reads, or '' without a palette."""
    if not doc: return ''
    s, m = doc['scheme'], doc['mood']
    return (f"Colour scheme worked out for this clip ({m['tone']}, {m['saturation']}, {m['temperature']} footage): base {s['base']}, contrasting accent {s['accent']} (its complement), support {s['support']}, neutrals {s['light']} and {s['dark']}, outline {s['outline']}. "
            f"Use these for fills, outlines and glows: the base for the main word, the accent for a second word or an extruded edge or a glow, a gradient from {s['gradient'][0]} to {s['gradient'][1]} where a gradient suits. They already read against the footage.")
