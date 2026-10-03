"""A street view section as a steady clip: a virtual camera that moves along the road through the section's pictures (streetview.py), at a speed that makes the clip the length the plan wants.

Three kinds of picture, three ways of keeping the camera steady:
  * Mapillary 360: each picture has its true 3D rotation from Mapillary's own reconstruction (`computed_rotation`), so the horizon is levelled exactly; the heading follows the smoothed path of the camera's positions, looking `LOOK_M` ahead.
  * Panoramax 360: no rotation is given, so which way is up is estimated from the picture (vertical things are vertical), lightly smoothed over neighbours; the heading follows the road.
  * Flat cameras (dashcams, phones): the pictures that face the way the runner went, each steadied by matching the far field (hills, sky line) to its neighbours, smoothing that path and cropping in a little.
The pictures between two real ones are made by moving each along the optical flow towards the other and mixing (a plain cross-fade ghosts anything near). The experiments behind the settings: docs/implementation-plan.md (street view).

`fetch(rd, section)` downloads what a section needs (once, into streetview/src/); `render(rd, section, seconds, out)` makes the clip; nothing here talks to the network except `fetch`."""
import json, math, os, subprocess

import cv2
import numpy as np
from scipy.ndimage import gaussian_filter1d

LOOK_M, SIGMA_HEADING = 25.0, {'mapillary': 4.0, 'panoramax': 5.0}          # metres ahead the camera looks; how many pictures the heading is smoothed over (chosen by measuring the shake of the finished clips)
SIGMA_UP = 1.5                                                               # pictures the estimated 'up' of a Panoramax picture is smoothed over
FOV, PITCH = 85.0, -2.0                                                      # degrees: the view's width, and a little down so the road is in it
OUT = (1920, 1080)
FLAT_CROP = 0.86                                                             # the part of a flat picture kept (the rest is room to steady it)


# ---- sources -----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def src_dir(rd, section): return os.path.join(rd, 'streetview', 'src', section['provider'])
def src_path(rd, section, item_id, preview=False): return os.path.join(src_dir(rd, section), item_id + ('.preview' if preview else '') + '.jpg')           # (the preview copy is the smaller picture the quality check uses)
def meta_path(rd, section): return os.path.join(src_dir(rd, section), section['seq'].replace('/', '_') + f"-{section['km0']:.2f}.json")


def fetch(rd, section, token=None, get=None, download=None, log=print, preview=False):
    """Download the full-size pictures of a section (`preview`: the smaller 2048 wide ones, enough to judge a section), and for Mapillary the reconstruction data (rotation and position of each). Kept: a picture already there is not
    fetched again. `get(url, params) -> json`, `download(url) -> bytes`."""
    from strata360 import streetview as SV
    get = get or SV._get; download = download or SV._bytes; os.makedirs(src_dir(rd, section), exist_ok=True)
    try: meta = json.load(open(meta_path(rd, section)))                                                                         # what an earlier fetch learnt (a picture already here needs no question to Mapillary)
    except (OSError, ValueError): meta = {}
    for it in section['items']:
        f = src_path(rd, section, it['id'], preview)
        if os.path.exists(f) and it['id'] in meta: continue
        if section['provider'] == 'mapillary':
            m = get(f"https://graph.mapillary.com/{it['id']}", dict(access_token=token, fields='thumb_original_url,thumb_2048_url,computed_rotation,computed_geometry,computed_compass_angle,compass_angle'))
            meta[it['id']] = {k: m.get(k) for k in ('computed_rotation', 'computed_geometry', 'computed_compass_angle', 'compass_angle')}; url = m.get('thumb_2048_url' if preview else 'thumb_original_url')
        else: url = (it.get('u') if preview else it.get('h')) or it.get('u'); meta[it['id']] = {'compass_angle': it.get('c')}                              # (the full-size picture, else the 2048 wide one)
        if not os.path.exists(f):
            if not url: raise RuntimeError(f"{section['provider']} has no picture to fetch for {it['id']}")
            tmp = f + '.part'; open(tmp, 'wb').write(download(url)); os.replace(tmp, f)
    json.dump(meta, open(meta_path(rd, section), 'w')); log(f"{section['provider']} {section['id']}: {len(section['items'])} pictures ready")


# ---- the maths of a virtual camera ------------------------------------------------------------------------------------------------------------------------------------------------------------
def Ry(a): c, s = math.cos(a), math.sin(a); return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])
def Rx(a): c, s = math.cos(a), math.sin(a); return np.array([[1, 0, 0], [0, c, -s], [0, s, c]])


def reproject(img, R, fov=FOV, size=OUT):
    """A flat view out of an equirectangular picture; R turns the view camera (x right, y up, z forward) into the picture's own frame (its centre column is straight ahead)."""
    W, H = size; h, w = img.shape[:2]; f = (W / 2) / math.tan(math.radians(fov) / 2)
    xs, ys = np.meshgrid(np.arange(W) - W / 2 + 0.5, np.arange(H) - H / 2 + 0.5); ray = np.stack([xs / f, -ys / f, np.ones_like(xs)], -1) @ R.T
    lon = np.arctan2(ray[..., 0], ray[..., 2]); lat = np.arctan2(ray[..., 1], np.hypot(ray[..., 0], ray[..., 2]))
    return cv2.remap(img, ((lon / (2 * math.pi) + 0.5) * w).astype(np.float32), ((0.5 - lat / math.pi) * h).astype(np.float32), cv2.INTER_LINEAR, borderMode=cv2.BORDER_WRAP)


def level_view(heading, pitch=PITCH):
    """The view camera in the world (x east, y north, z up) looking at compass `heading` degrees and `pitch` up, level: columns right, up, forward."""
    h, p = math.radians(heading), math.radians(pitch); z = np.array([math.sin(h) * math.cos(p), math.cos(h) * math.cos(p), math.sin(p)]); x = np.array([math.cos(h), -math.sin(h), 0.0]); return np.stack([x, np.cross(x, z), z], axis=1)


def sfm_to_world(rvec):
    """Camera (x right, y down, z forward) to world (east, north, up) from Mapillary's `computed_rotation` (the axis-angle of the world to camera rotation)."""
    R, _ = cv2.Rodrigues(np.array(rvec, float)); return R.T


FLIP = np.diag([1.0, -1.0, 1.0])                  # Mapillary's camera has y down, the view camera y up


def up_rotation(u):
    """Rotation taking (0,1,0) to the unit vector u."""
    y = np.array([0, 1.0, 0]); v = np.cross(y, u); s = np.linalg.norm(v); c = float(y @ u)
    if s < 1e-9: return np.eye(3)
    vx = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]]); return np.eye(3) + vx + vx @ vx * ((1 - c) / s ** 2)


def _score(small, u, px=300):
    Q = up_rotation(u); tot = 0.0
    for a in (0, 90, 180, 270):
        g = cv2.cvtColor(reproject(small, Q @ Ry(math.radians(a)), 90.0, (px, px)), cv2.COLOR_BGR2GRAY).astype(np.float32)[int(px * 0.2):int(px * 0.8)]
        gx = cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=3); tot += float(((gx.sum(axis=0)) ** 2).sum() / (np.sum(gx ** 2) + 1.0))
    return tot


def _vec(theta, phi): t, p = math.radians(theta), math.radians(phi); return np.array([math.sin(t) * math.cos(p), math.cos(t), math.sin(t) * math.sin(p)])


def estimate_up(img):
    """Which way is up in a 360 picture, from the picture alone: the direction that makes trees, poles and building edges vertical in flat views looking out every way (a grid search, then refined). Within about 3 degrees."""
    small = cv2.resize(img, (1440, 720), interpolation=cv2.INTER_AREA); best = (_score(small, _vec(0, 0)), 0.0, 0.0)
    for th in (3, 6, 9, 12, 16, 20):
        for ph in range(0, 360, 45):
            s = _score(small, _vec(th, ph))
            if s > best[0]: best = (s, th, ph)
    _, th, ph = best
    for step in (2.0, 1.0):
        for dt in (-step, 0, step):
            for dp in (-15 * step, 0, 15 * step):
                s = _score(small, _vec(max(0.0, th + dt), ph + dp))
                if s > best[0]: best = (s, max(0.0, th + dt), ph + dp)
        _, th, ph = best
    return _vec(th, ph)


def view_in_picture(u, centre_heading, heading, pitch=PITCH):
    """For a Panoramax picture with up vector `u` (its own frame) and the compass heading of its centre column: the rotation for a level view looking at `heading`."""
    z0 = np.array([0, 0, 1.0]); z0 = z0 - (z0 @ u) * u; z0 /= np.linalg.norm(z0); x0 = np.cross(u, z0); d = math.radians((heading - centre_heading + 180) % 360 - 180)
    z = math.cos(d) * z0 + math.sin(d) * x0; x = np.cross(u, z); x /= np.linalg.norm(x); R = np.stack([x, u, z], axis=1); p = math.radians(pitch)
    return R @ Rx(-p) if p else R


def smooth_heading(deg, sigma):
    r = np.radians(deg); return np.degrees(np.arctan2(gaussian_filter1d(np.sin(r), sigma, mode='nearest'), gaussian_filter1d(np.cos(r), sigma, mode='nearest'))) % 360


def heading_along(prog, xy, at, look):
    """Compass heading of the path (progress `prog` in metres, positions `xy` east/north in metres) at progress `at`, from `look`/2 behind to `look` ahead."""
    a = np.array([np.interp(at - look / 2, prog, xy[:, 0]), np.interp(at - look / 2, prog, xy[:, 1])]); b = np.array([np.interp(at + look, prog, xy[:, 0]), np.interp(at + look, prog, xy[:, 1])])
    return math.degrees(math.atan2(b[0] - a[0], b[1] - a[1])) % 360


def flow_blend(A, B, alpha):
    """The picture alpha of the way from A to B: both moved along the optical flow between them and mixed."""
    g0 = cv2.cvtColor(A, cv2.COLOR_BGR2GRAY); g1 = cv2.cvtColor(B, cv2.COLOR_BGR2GRAY); dis = cv2.DISOpticalFlow_create(cv2.DISOPTICAL_FLOW_PRESET_MEDIUM)
    F = cv2.resize(dis.calc(cv2.resize(g0, None, fx=.5, fy=.5), cv2.resize(g1, None, fx=.5, fy=.5), None), (A.shape[1], A.shape[0])) * 2.0
    h, w = g0.shape; gx, gy = np.meshgrid(np.arange(w, dtype=np.float32), np.arange(h, dtype=np.float32)); alpha = float(alpha)
    wa = cv2.remap(A, (gx - alpha * F[..., 0]).astype(np.float32), (gy - alpha * F[..., 1]).astype(np.float32), cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    wb = cv2.remap(B, (gx + (1 - alpha) * F[..., 0]).astype(np.float32), (gy + (1 - alpha) * F[..., 1]).astype(np.float32), cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    return cv2.addWeighted(wa, 1 - alpha, wb, alpha, 0)


# ---- flat cameras ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def far_shift(A, B):
    """(dx, dy, rotation in degrees) of the far field of B against A (small pictures): matches in the upper, distant part, the slow-moving ones, as a similarity transform. None when too few agree."""
    ga = cv2.cvtColor(A, cv2.COLOR_BGR2GRAY); gb = cv2.cvtColor(B, cv2.COLOR_BGR2GRAY); mask = np.zeros_like(ga); mask[: int(ga.shape[0] * 0.62)] = 255
    sift = cv2.SIFT_create(1500); ka, da = sift.detectAndCompute(ga, mask); kb, db = sift.detectAndCompute(gb, mask)
    if da is None or db is None or len(ka) < 20 or len(kb) < 20: return None
    good = [m for m, n in cv2.BFMatcher().knnMatch(da, db, k=2) if m.distance < 0.75 * n.distance]
    if len(good) < 12: return None
    pa = np.float32([ka[m.queryIdx].pt for m in good]); pb = np.float32([kb[m.trainIdx].pt for m in good]); fl = np.linalg.norm(pb - pa, axis=1); keep = fl < max(np.percentile(fl, 60), 2.0)
    if keep.sum() < 12: return None
    M, inl = cv2.estimateAffinePartial2D(pa[keep], pb[keep], method=cv2.RANSAC, ransacReprojThreshold=1.5)
    if M is None or inl.sum() < 10: return None
    cx, cy = ga.shape[1] / 2, ga.shape[0] / 2; return float(M[0, 0] * cx - M[0, 1] * cy + M[0, 2] - cx), float(M[1, 0] * cx + M[1, 1] * cy + M[1, 2] - cy), math.degrees(math.atan2(M[1, 0], M[0, 0]))


def steady_flat(imgs, sigma=2.5):
    """For flat pictures: per-picture (dx, dy, rotation) that take out the quick shake (the path of far-field shifts, minus its smooth version), in pixels of the originals."""
    small = [cv2.resize(im, (960, int(960 * im.shape[0] / im.shape[1]))) for im in imgs]; k = imgs[0].shape[1] / 960.0; steps = []
    for a, b in zip(small, small[1:]):
        s = far_shift(a, b); steps.append((0.0, 0.0, 0.0) if s is None else s)
    path = np.vstack([np.zeros(3), np.cumsum(np.array(steps), axis=0)]); fast = path - gaussian_filter1d(path, sigma, axis=0, mode='nearest'); return [(-d[0] * k, -d[1] * k, -d[2]) for d in fast]


def flat_view(img, shift, size=OUT):
    """A 16:9 crop of a flat picture (FLAT_CROP of it), moved and turned by `shift` (dx, dy, degrees) to steady it, scaled to `size`."""
    h, w = img.shape[:2]; cw = w * FLAT_CROP; ch = min(h * FLAT_CROP, cw * size[1] / size[0]); cw = ch * size[0] / size[1]; cx, cy = w / 2 - shift[0], h / 2 - shift[1]
    A = cv2.getRotationMatrix2D((cx, cy), shift[2], size[0] / cw); A[0, 2] += size[0] / 2 - cx; A[1, 2] += size[1] / 2 - cy
    return cv2.warpAffine(img, A, size, flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)


# ---- the clip ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def forward_items(section, limit=45.0):
    """The items of a section a clip can use: all of them for a 360 camera, for a flat one those facing the way the runner went (the others look sideways or back)."""
    if section['kind'] == '360': return list(section['items'])
    return [it for it in section['items'] if it.get('a') is not None and abs(it['a']) <= limit]


def road_xy(line):
    """(progress in metres, east/north metres) of a road line [[lat, lon], ...] (smoothed lightly)."""
    p = np.array(line, float); p = np.stack([gaussian_filter1d(p[:, 0], 2.0, mode='nearest'), gaussian_filter1d(p[:, 1], 2.0, mode='nearest')], 1); la0 = p[0, 0]
    xy = np.stack([(p[:, 1] - p[0, 1]) * math.cos(math.radians(la0)) * 111320, (p[:, 0] - la0) * 111320], 1); return np.concatenate([[0], np.cumsum(np.hypot(*np.diff(xy, axis=0).T))]), xy


class Rig:
    """What a section's camera needs: the pictures facing the way the runner went (`items`), how far along each is (`prog`, metres), the heading wanted at each (`hs`) and `view(i, yaw)`, the steady view out of picture i looking at compass `yaw`."""
    def __init__(self, items, prog, hs, view): self.items, self.prog, self.hs, self.view, self.n = items, prog, hs, view, len(items)


def build(rd, section, road=None, size=OUT, preview=False):
    """The camera rig for a section (see Rig); the maths depends on the kind of picture (module notes). Raises ValueError when there are too few pictures, RuntimeError when one has not been fetched."""
    its = forward_items(section)
    if len(its) < 8: raise ValueError(f"{section['id']}: only {len(its)} pictures face the way the runner went")
    prov = section['provider']; imgs = {}
    def img(i):
        if i not in imgs:
            if len(imgs) > 4: imgs.clear()
            im = cv2.imread(src_path(rd, section, its[i]['id'], preview))
            if im is None: raise RuntimeError(f"{section['id']}: picture {its[i]['id']} has not been fetched")
            imgs[i] = im
        return imgs[i]
    km = np.array([it['km'] for it in its]) * 1000.0; n = len(its); view = None
    if section['kind'] == '360' and prov == 'mapillary':
        meta = json.load(open(meta_path(rd, section))); pos = np.array([meta[it['id']]['computed_geometry']['coordinates'] for it in its]); la0 = pos[:, 1].mean()
        xy = np.stack([(pos[:, 0] - pos[0, 0]) * math.cos(math.radians(la0)) * 111320, (pos[:, 1] - pos[0, 1]) * 111320], 1); xy = np.stack([gaussian_filter1d(xy[:, 0], 1.0, mode='nearest'), gaussian_filter1d(xy[:, 1], 1.0, mode='nearest')], 1)
        prog = np.concatenate([[0], np.cumsum(np.hypot(*np.diff(xy, axis=0).T))]) + km[0]; Rc = [sfm_to_world(meta[it['id']]['computed_rotation']) for it in its]
        hs = smooth_heading([heading_along(prog, xy, p, LOOK_M) for p in prog], SIGMA_HEADING['mapillary']); view = lambda i, yaw: reproject(img(i), FLIP @ Rc[i].T @ level_view(yaw), FOV, size)
    elif section['kind'] == '360':
        if not road: raise ValueError('a Panoramax 360 section needs the road (its line and where it starts) to aim along')
        meta = json.load(open(meta_path(rd, section))); rp, rxy = road_xy(road['line']); rp = rp + road['km0'] * 1000.0; prog = km
        ups = cached_ups(rd, section, [img(i) for i in range(n)], n, preview); ups = gaussian_filter1d(ups, SIGMA_UP, axis=0, mode='nearest'); ups /= np.linalg.norm(ups, axis=1, keepdims=True)
        hs = smooth_heading([heading_along(rp, rxy, p, LOOK_M) for p in prog], SIGMA_HEADING['panoramax']); comp = [meta[it['id']]['compass_angle'] or 0.0 for it in its]; view = lambda i, yaw: reproject(img(i), view_in_picture(ups[i], comp[i], yaw), FOV, size)
    else:
        prog = km; shifts = steady_flat([img(i) for i in range(n)]); view = lambda i, yaw: flat_view(img(i), shifts[i], size)
        hs = np.zeros(n)
    return Rig(its, prog, hs, view)


def ups_path(rd, section, preview=False): return meta_path(rd, section) + ('.preview' if preview else '') + '.ups.npy'


def cached_ups(rd, section, imgs, n, preview=False):
    """The estimated 'up' of each Panoramax picture, kept beside the pictures (the search takes seconds a picture)."""
    f = ups_path(rd, section, preview)
    if os.path.exists(f) and len(np.load(f)) == n: return np.load(f)
    u = np.array([estimate_up(im) for im in (imgs if imgs is not None else [])]); np.save(f, u); return u


def render(rd, section, seconds, out, road=None, fps=30, size=OUT, encode_size=None, log=print, preview=False):
    """Write the clip of `section` (an entry of streetview.annotate with `items`) lasting `seconds` to `out` (H.264). The whole section is played through, so its pictures per second follow from the length. `road` is the stretch
    {line: [[lat, lon], ...], km0} (for Panoramax headings). `encode_size`, e.g. (3840, 2160), scales the finished picture; `preview` uses the smaller copies of the pictures."""
    rig = build(rd, section, road, size, preview); prog, hs, view, n = rig.prog, rig.hs, rig.view, rig.n
    L = prog[-1] - prog[0]; N = max(2, int(seconds * fps)); w, h = encode_size or size
    cmd = ['ffmpeg', '-y', '-v', 'error', '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-s', f'{size[0]}x{size[1]}', '-r', str(fps), '-i', '-'] + (['-vf', f'scale={w}:{h}:flags=lanczos'] if (w, h) != tuple(size) else []) + ['-c:v', 'libx264', '-crf', '17', '-pix_fmt', 'yuv420p', out + '.part.mp4']
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    try:
        for k in range(N):
            pos = prog[0] + L * k / (N - 1); i = max(0, min(int(np.searchsorted(prog, pos, side='right') - 1), n - 2)); a = float(np.clip((pos - prog[i]) / max(prog[i + 1] - prog[i], 1e-6), 0, 1))
            yaw = (hs[i] + ((hs[i + 1] - hs[i] + 180) % 360 - 180) * a) % 360; p.stdin.write(flow_blend(view(i, yaw), view(i + 1, yaw), a).tobytes())
        p.stdin.close(); p.wait()
    except BrokenPipeError: p.wait()
    if p.returncode: raise RuntimeError('ffmpeg failed to write the street view clip')
    os.replace(out + '.part.mp4', out); log(f"{section['id']}: {N} frames, {n} pictures over {L:.0f} m in {seconds:g} s ({n / seconds:.1f} pictures a second)"); return dict(frames=N, pictures=n, metres=round(L), per_s=round(n / seconds, 1))


# ---- how good a clip will be -------------------------------------------------------------------------------------------------------------------------------------------------------------------
PROBE_MS, PROBE_S, PROBE_FPS = 25.0, 4.0, 30      # the test clip moves along the road at 25 m/s (about 90 km/h, what a fast-forward insert looks like) for about 4 s, whatever the spacing of the pictures


def quality(rd, section, road=None, size=(640, 360), samples=16, preview=True):
    """Measure how good the clip of a section will look, without making the whole of it: {psnr, jerk, roll, pictures, spacing_m, score}.
      psnr   how well the picture between two real ones can be made: for sample pictures, the picture is rebuilt from its two neighbours by the flow blend and compared with the real one (dB, higher is better; it falls as the pictures
             get further apart, the camera is badly levelled, or things near the road move too much between pictures);
      jerk   how unsteady the view is: a short test clip is played at 25 m/s along the road and the far field (hills, sky line) is followed from frame to frame; the jerk is how much its movement changes between frames (degrees,
             95th percentile; a steady camera has a smooth drift, a shaking one jumps);
      roll   how far the view turns about its axis between frames (degrees, 95th percentile).
    `score` is 0 to 100 from them (see `score`); `grade` calls it poor, fair or good."""
    rig = build(rd, section, road, size, preview); n = rig.n
    if n < 5: raise ValueError(f"{section['id']}: only {n} usable pictures")
    idx = sorted({int(round(v)) for v in np.linspace(1, n - 2, min(samples, n - 2))}); ps = []
    h0, w0 = size[1], size[0]; crop = (slice(int(h0 * 0.1), int(h0 * 0.9)), slice(int(w0 * 0.1), int(w0 * 0.9)))
    for i in idx:
        yaw = rig.hs[i]; A, R, B = rig.view(i - 1, yaw), rig.view(i, yaw), rig.view(i + 1, yaw); span = rig.prog[i + 1] - rig.prog[i - 1]; a = float(np.clip((rig.prog[i] - rig.prog[i - 1]) / max(span, 1e-6), 0.05, 0.95))
        ps.append(cv2.PSNR(flow_blend(A, B, a)[crop], R[crop]))
    f = (size[0] / 2) / math.tan(math.radians(FOV) / 2); L = rig.prog[-1] - rig.prog[0]; v = PROBE_MS; N = int(min(PROBE_S, L / v) * PROBE_FPS); start = max(0.0, (L - v * N / PROBE_FPS) / 2)       # (the middle of the section)
    prev = None; yaw_shift = []; roll = []
    for k in range(N):
        pos = rig.prog[0] + start + v * k / PROBE_FPS; i = max(0, min(int(np.searchsorted(rig.prog, pos, side='right') - 1), n - 2)); a = float(np.clip((pos - rig.prog[i]) / max(rig.prog[i + 1] - rig.prog[i], 1e-6), 0, 1))
        yaw = (rig.hs[i] + ((rig.hs[i + 1] - rig.hs[i] + 180) % 360 - 180) * a) % 360; fr = flow_blend(rig.view(i, yaw), rig.view(i + 1, yaw), a)
        if prev is not None:
            s = far_shift(prev, fr)
            if s is not None: yaw_shift.append(math.degrees(math.atan2(s[0], f))); roll.append(abs(s[2]))
        prev = fr
    jerk = np.abs(np.diff(yaw_shift)) if len(yaw_shift) > 3 else None
    out = dict(psnr=round(float(np.median(ps)), 1), jerk=None if jerk is None else round(float(np.percentile(jerk, 95)), 2), roll=round(float(np.percentile(roll, 95)), 2) if roll else None, pictures=n, spacing_m=round(float(np.median(np.diff(rig.prog))), 1))
    out['score'] = score(out); return out


SCORE_PSNR = (12.0, 20.0)         # dB that count as 0 and as full marks for how well in-between pictures can be made
SCORE_JERK = (0.2, 3.0)           # degrees of jerk: full marks and none
SCORE_ROLL = (0.5, 6.0)           # degrees of turning between frames


def score(m):
    """0 to 100 from the measurements of `quality`: the in-between pictures count half, the steadiness (jerk) a third and the turning the rest. A measurement that could not be made counts as the worst."""
    def lin(v, lo, hi): return 0.0 if v is None else float(np.clip((v - lo) / (hi - lo), 0, 1))
    p = lin(m.get('psnr'), *SCORE_PSNR); k = 1.0 - lin(m.get('jerk') if m.get('jerk') is not None else SCORE_JERK[1], *SCORE_JERK); r = 1.0 - lin(m.get('roll') if m.get('roll') is not None else SCORE_ROLL[1], *SCORE_ROLL)
    return round(100.0 * (0.5 * p + 0.33 * k + 0.17 * r))


def grade(sc): return 'good' if sc >= 65 else 'fair' if sc >= 40 else 'poor'
