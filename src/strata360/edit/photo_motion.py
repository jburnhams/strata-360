"""Pan and zoom on a still photo (the "Ken Burns" move) so it can be used in the film like a shot.

A move is a camera path over the photo: a crop window of the output's shape (16:9) whose centre and zoom change over time, eased, always inside the photo and never zoomed in further than the photo's own pixels allow (`max_upscale`).
Coordinates are fractions of the photo (0..1 across and down), so a path does not depend on the size a photo was analysed at. Zoom 1 is the largest window of the output's shape that fits in the photo; zoom 2 is half as wide.

Where to look (`focals`): the wearer's face first, then other faces and persons (from the photo analysis, analysis/photo_analysis.py), then the most detailed part of the picture (`saliency`), else the rule-of-thirds points. Each move goes TOWARD something:

  push_in   from the whole picture slowly in on the main subject
  pull_out  from a close view of the subject out to the whole picture
  pan       across a wide photo (or down a tall one) from one end to the other, ending on the subject
  drift     a gentle slide and zoom from one point of interest toward another
  reveal    from a detail at high zoom, moving and widening to the next point of interest
  hold      the whole picture with a slight breath (a photo that should just be seen)

`plan()` picks the style (`auto`: by the shape of the photo and what is in it, the seed breaking ties and choosing the direction; a short shot, under 3.5 s, only gets a push in, a pull out or a hold, and every move is made in proportion to the time it has: all of it in 6 s or more, a third of it in 2 s) and returns the keys; `crop_at()` gives the window at a time; `render()` yields the frames; `write_video()` makes an MP4 with ffmpeg."""
import math, subprocess

import numpy as np

STYLES = ('push_in', 'pull_out', 'pan', 'drift', 'reveal', 'hold')
ASPECT = 16 / 9
MAX_UPSCALE = 1.5          # the window may be this much smaller than the output in pixels (the photo is enlarged by at most this)
EDGE = 0.02                # the window keeps this share of the photo away from its edge when it can (a little air round a face at the border)


def ease(u): u = min(max(u, 0.0), 1.0); return u * u * (3 - 2 * u)                                    # smoothstep: starts and ends gently


def base_window(w, h, aspect=ASPECT):
    """(width, height) in pixels of the zoom-1 window: the largest of the output's shape inside the photo."""
    bw = min(w, h * aspect); return bw, bw / aspect


def max_zoom(w, h, out_w, aspect=ASPECT, max_upscale=MAX_UPSCALE):
    """How far in the window may go: until it is `out_w / max_upscale` photo pixels wide."""
    bw, _ = base_window(w, h, aspect); return max(1.0, bw / (out_w / max_upscale))


def clamp_key(k, w, h, aspect, zmax):
    """The key with its zoom limited to 1..zmax and its centre moved so that the window lies inside the photo."""
    bw, bh = base_window(w, h, aspect); z = min(max(k['z'], 1.0), zmax); ww, wh = bw / z / w, bh / z / h
    return dict(cx=min(max(k['cx'], ww / 2), 1 - ww / 2), cy=min(max(k['cy'], wh / 2), 1 - wh / 2), z=z)


def saliency(img, rows=6, cols=8):
    """The most interesting block of a picture by its detail and colour contrast (a BGR array): (cx, cy, w, h, strength 0..1) as fractions, with a slight preference for the middle. None for a picture without any."""
    import cv2
    small = cv2.resize(img, (cols * 32, rows * 32), interpolation=cv2.INTER_AREA); g = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY).astype(np.float32); lab = cv2.cvtColor(small, cv2.COLOR_BGR2LAB).astype(np.float32)
    detail = np.abs(g - cv2.GaussianBlur(g, (0, 0), 3)); colour = np.linalg.norm(lab - lab.reshape(-1, 3).mean(0), axis=2)
    s = (detail / (detail.max() + 1e-6) + 0.6 * colour / (colour.max() + 1e-6)).reshape(rows, 32, cols, 32).mean((1, 3)); yy, xx = np.mgrid[:rows, :cols]
    s = s * (1 - 0.25 * (np.hypot((xx + 0.5) / cols - 0.5, (yy + 0.5) / rows - 0.5) / 0.7))
    if s.max() <= 1e-6: return None
    r, c = np.unravel_index(int(np.argmax(s)), s.shape); return ((c + 0.5) / cols, (r + 0.5) / rows, 2.0 / cols, 2.0 / rows, float(min(1.0, s[r, c] / (s.mean() * 2.5 + 1e-6))))


def focals(doc, img=None):
    """The places worth looking at in a photo, most important first: [{cx, cy, w, h, weight, label}] as fractions. From the analysis `doc` (photos/analysis/<id>.json): the wearer's face, other faces and persons, the objects; then the most detailed block of `img`;
    always the rule-of-thirds points at the end so a path has somewhere to go."""
    out = []; det = (doc or {}).get('people') or {}; W, H = float(det.get('w') or 0), float(det.get('h') or 0); me = ((doc or {}).get('identity') or {}).get('me')
    def add(box, weight, label, grow=1.0):
        if not W or not H: return
        x0, y0, x1, y1 = box; w, h = (x1 - x0) / W * grow, (y1 - y0) / H * grow; out.append(dict(cx=(x0 + x1) / 2 / W, cy=(y0 + y1) / 2 / H, w=min(w, 1.0), h=min(h, 1.0), weight=weight, label=label))
    faces = det.get('faces') or []
    for i, f in enumerate(faces):
        if me and me.get('face') == i: add(f['box'], 1.0, 'you', 2.6)
        elif f.get('score', 0) >= 0.5: add(f['box'], 0.7, 'face', 2.6)
    for p in det.get('people') or []:
        if p.get('conf', 0) >= 0.5 and not any(abs(o['cx'] - (p['box'][0] + p['box'][2]) / 2 / W) < 0.15 and o['label'] in ('you', 'face') for o in out if W): add(p['box'], 0.6, 'person')
    ob = (doc or {}).get('objects') or {}; ow, oh = float(ob.get('w') or 0), float(ob.get('h') or 0)
    for o in ob.get('objects') or []:                                                                    # everyday objects (photos only): worth looking at when they are not tiny
        x0, y0, x1, y1 = o['box']
        if ow and oh and (x1 - x0) * (y1 - y0) / (ow * oh) >= 0.01: out.append(dict(cx=(x0 + x1) / 2 / ow, cy=(y0 + y1) / 2 / oh, w=(x1 - x0) / ow, h=(y1 - y0) / oh, weight=round(0.3 + 0.25 * o.get('conf', 0.5), 3), label=o['label']))
    if img is not None:
        s = saliency(img)
        if s: out.append(dict(cx=s[0], cy=s[1], w=s[2], h=s[3], weight=0.3 + 0.3 * s[4], label='detail'))
    for cx, cy in ((1 / 3, 1 / 3), (2 / 3, 1 / 3), (1 / 3, 2 / 3), (2 / 3, 2 / 3)): out.append(dict(cx=cx, cy=cy, w=0.3, h=0.3, weight=0.1, label='thirds'))
    return sorted(out, key=lambda f: -f['weight'])


def zoom_on(f, w, h, aspect, zmax, tight=0.55):
    """The zoom that frames a subject: the window about 1/`tight` times the subject's size (so a face fills a fair part of the frame) in both directions, within 1..zmax."""
    bw, bh = base_window(w, h, aspect); z = min(bw * tight / max(f['w'] * w, 1.0), bh * tight / max(f['h'] * h, 1.0)); return min(max(z, 1.0), zmax)


def pick_style(w, h, subjects, rng, aspect=ASPECT, duration_s=6.0):
    """The style `auto` chooses: a very wide or tall photo is panned; a photo with a main subject is pushed in on (or pulled out from, sometimes) or revealed; one with two points of interest drifts or reveals; one with nothing is held or drifts."""
    ratio = w / h; short = duration_s < 3.5                                                               # a short shot has no time for a reveal or a long drift
    if ratio > aspect * 1.35 or ratio < 1 / aspect * 0.8: return 'pan'
    strong = [s for s in subjects if s['weight'] >= 0.5]
    if short: return str(rng.choice(['push_in', 'push_in', 'pull_out'])) if strong else str(rng.choice(['push_in', 'hold']))
    if len(strong) >= 2: return str(rng.choice(['drift', 'reveal', 'push_in']))
    if strong: return str(rng.choice(['push_in', 'push_in', 'pull_out']))
    return str(rng.choice(['drift', 'push_in', 'hold']))


def plan(size, duration_s, style='auto', subjects=None, seed=0, aspect=ASPECT, out_w=1920, max_upscale=MAX_UPSCALE):
    """The camera path for a photo of `size` (w, h) in pixels over `duration_s` seconds: {style, duration_s, aspect, zmax, keys: [{t, cx, cy, z}] (two or three), subjects: the focal points used}. `style`: one of STYLES or 'auto'."""
    if style != 'auto' and style not in STYLES: raise ValueError(f'style: one of {", ".join(STYLES)} or auto')
    if duration_s <= 0: raise ValueError('the length must be more than zero seconds')
    w, h = size; rng = np.random.default_rng(int(seed)); zmax = max_zoom(w, h, out_w, aspect, max_upscale); subj = list(subjects or []) or [dict(cx=0.5, cy=0.5, w=0.5, h=0.5, weight=0.1, label='middle')]
    main = subj[0]; second = next((s for s in subj[1:] if math.hypot(s['cx'] - main['cx'], s['cy'] - main['cy']) > 0.2), subj[1] if len(subj) > 1 else main); st = pick_style(w, h, subj, rng, aspect, duration_s) if style == 'auto' else style
    zm = min(zmax, max(1.12, zoom_on(main, w, h, aspect, zmax))); mid = dict(cx=0.5, cy=0.5, z=1.0); bw, bh = base_window(w, h, aspect)
    if st == 'push_in': a, b = dict(cx=0.5 + (main['cx'] - 0.5) * 0.25, cy=0.5 + (main['cy'] - 0.5) * 0.25, z=1.0), dict(cx=main['cx'], cy=main['cy'], z=min(zm, 1.45))
    elif st == 'pull_out': a, b = dict(cx=main['cx'], cy=main['cy'], z=min(zm, 1.6)), dict(cx=0.5 + (main['cx'] - 0.5) * 0.25, cy=0.5 + (main['cy'] - 0.5) * 0.25, z=1.0)
    elif st == 'pan':                                                                                       # along the long way of the picture, to end on the side the subject is on (a centred subject: the seed chooses)
        wide = w / h >= aspect; axis = 'cx' if wide else 'cy'; first = main[axis] >= 0.5 if abs(main[axis] - 0.5) > 0.1 else bool(rng.integers(2)); lo, hi = (0.0, 1.0) if first else (1.0, 0.0)
        room = (w / bw if wide else h / bh) - 1.0; zp = 1.0 if room >= 0.25 else min(zmax, 1.4)                         # a photo with no room along its length (16:9 itself) is zoomed in a little first so there is something to pan across
        cy0, cx0 = (main['cy'] if zp > 1.0 else 0.5), (main['cx'] if zp > 1.0 else 0.5)
        a, b = (dict(cx=lo, cy=cy0, z=zp), dict(cx=hi, cy=cy0, z=zp)) if wide else (dict(cx=cx0, cy=lo, z=zp), dict(cx=cx0, cy=hi, z=zp))
    elif st == 'drift': a, b = dict(cx=main['cx'], cy=main['cy'], z=min(1.12, zmax)), dict(cx=second['cx'], cy=second['cy'], z=min(1.3, zmax))
    elif st == 'reveal': a, b = dict(cx=main['cx'], cy=main['cy'], z=min(zm * 1.15, zmax)), dict(cx=second['cx'] if second is not main else 0.5, cy=second['cy'] if second is not main else 0.5, z=min(max(1.0, zm * 0.55), 1.2))
    else: a, b = dict(cx=0.5, cy=0.5, z=1.0), dict(cx=0.5, cy=0.5, z=min(1.06, zmax))
    amount = min(1.0, max(0.35, duration_s / 6.0))                                                           # how much of the move is made: all of it in 6 s or more, a third of it in 2 s (travelling the whole way in 2 s would be too fast to watch)
    if st != 'hold': b = dict(cx=a['cx'] + (b['cx'] - a['cx']) * amount, cy=a['cy'] + (b['cy'] - a['cy']) * amount, z=math.exp(math.log(a['z']) + (math.log(b['z']) - math.log(a['z'])) * amount))
    keys = [dict(t=0.0, **clamp_key(a, w, h, aspect, zmax)), dict(t=float(duration_s), **clamp_key(b, w, h, aspect, zmax))]
    return dict(style=st, duration_s=float(duration_s), aspect=aspect, zmax=round(zmax, 3), keys=keys, subjects=subj[:3], seed=int(seed), size=[int(w), int(h)])


def key_at(pl, t):
    """The path's centre and zoom at time t (held at the ends)."""
    (k0, k1) = pl['keys'][0], pl['keys'][-1]; u = ease((t - k0['t']) / max(k1['t'] - k0['t'], 1e-9))
    z = math.exp(math.log(k0['z']) + (math.log(k1['z']) - math.log(k0['z'])) * u)                          # zoom is eased in its logarithm, so it feels even
    return dict(cx=k0['cx'] + (k1['cx'] - k0['cx']) * u, cy=k0['cy'] + (k1['cy'] - k0['cy']) * u, z=z)


def crop_at(pl, t):
    """The window at time t in photo pixels: (x0, y0, width, height) as floats."""
    w, h = pl['size']; bw, bh = base_window(w, h, pl['aspect']); k = key_at(pl, t); ww, wh = bw / k['z'], bh / k['z']
    return (min(max(k['cx'] * w - ww / 2, 0.0), w - ww), min(max(k['cy'] * h - wh / 2, 0.0), h - wh), ww, wh)


def render(img, pl, out_size, fps=25.0):
    """The frames (BGR uint8, `out_size` = (w, h)) of the move over the photo `img` (a BGR array of the size the plan was made for, or scaled the same): one per 1/fps second for the length of the plan. Sub-pixel crops, Lanczos when enlarging, a pyramid when shrinking a lot."""
    import cv2
    H, W = img.shape[:2]; ow, oh = out_size; n = max(1, int(round(pl['duration_s'] * fps))); levels = [img]; sx = W / pl['size'][0]
    while levels[-1].shape[1] > 2 * ow and levels[-1].shape[1] // 2 >= ow: levels.append(cv2.pyrDown(levels[-1]))
    for i in range(n):
        x0, y0, ww, wh = (v * sx for v in crop_at(pl, (i + 0.5) / fps if n > 1 else 0.0)); lv = 0
        while lv + 1 < len(levels) and ww / (2 ** (lv + 1)) >= ow: lv += 1
        s = 2 ** lv; src = levels[lv]; M = np.array([[ow / (ww / s), 0, -x0 / s * ow / (ww / s)], [0, oh / (wh / s), -y0 / s * oh / (wh / s)]], np.float64)
        yield cv2.warpAffine(src, M, (ow, oh), flags=cv2.INTER_LANCZOS4 if ow / (ww / s) > 1 else cv2.INTER_AREA if ww / s > 3 * ow else cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)


def write_video(path, img, pl, out_size=(960, 540), fps=25.0, crf=20):
    """Write the move as an H.264 MP4 (ffmpeg); returns the number of frames."""
    ow, oh = out_size; cmd = ['ffmpeg', '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-s', f'{ow}x{oh}', '-r', str(fps), '-i', '-', '-an', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-crf', str(crf), '-movflags', '+faststart', path]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE); n = 0
    try:
        for fr in render(img, pl, out_size, fps): p.stdin.write(np.ascontiguousarray(fr).tobytes()); n += 1
        p.stdin.close()
    except BrokenPipeError: pass
    err = p.stderr.read().decode(errors='replace'); code = p.wait()
    if code: raise RuntimeError(f'ffmpeg failed ({code}): {err[-300:]}')
    return n
