"""Local super-resolution for shots whose source holds fewer pixels than the output needs (a tight zoom, or a low-resolution street view panorama).

Model: RealPLKSR trained on web photos (`4xNomosWebPhoto_RealPLKSR`, CC-BY-4.0, by Phhofm) by default; SwinIR-M real-world GAN is the slower alternative, see MODELS; loaded with `spandrel` (optional dependency) from `models/<folder>/`. It runs in tiles on the GPU (MPS) when there is one.

One decision per SHOT, never per frame: `factor_for` is called once with the shot's worst case (its narrowest view over the whole shot), and the factor it returns is applied to every picture of the shot, so the sharpness and
texture of a shot do not change part way through. Upscaled pictures are kept beside the originals (`cached`), so a picture is upscaled once however many times it is re-projected."""
import math, os

import cv2
import numpy as np

MODELS = {
    'realplksr-nomos': ('realplksr', '4xNomosWebPhoto_RealPLKSR.pth', 'https://github.com/Phhofm/models/releases/download/4xNomosWebPhoto_RealPLKSR/4xNomosWebPhoto_RealPLKSR.pth', 256),                                                                              # RealPLKSR by Phhofm, trained on web photos with noise, blur and JPEG/WebP: CC-BY-4.0 (credit it). About as crisp as SwinIR and several times faster
                        # name: (folder, weights file, download, tile size). All 4x. Chosen by eye on a street view crop with small lettering (docs/progress.md): the compact Real-ESRGAN smoothed the writing away.
    'swinir-bsrgan': ('swinir', '003_realSR_BSRGAN_DFO_s64w8_SwinIR-M_x4_GAN.pth', 'https://github.com/JingyunLiang/SwinIR/releases/download/v0.0/003_realSR_BSRGAN_DFO_s64w8_SwinIR-M_x4_GAN.pth', 128),        # SwinIR-M, real-world (BSRGAN degradations), GAN: Apache-2.0
    'realesrgan-x4plus': ('realesrgan', 'RealESRGAN_x4plus.pth', 'https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/RealESRGAN_x4plus.pth', 256),                                                                                      # BSD-3-Clause
    'realesrgan-general': ('realesrgan', 'realesr-general-x4v3.pth', 'https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/realesr-general-x4v3.pth', 256),                                                                                    # fast (0.7 s a 4K frame) but loses fine detail
}
MODEL = 'realplksr-nomos'
PAD = 16
MODES = {'off': 0, '1080p': 1920, '1440p': 2560, 'full': None}     # how far the model enlarges a shot: not at all; to 1080p or 1440p width and then a standard resample (Lanczos) to the output size; or the model all the way to the output size
LABELS = {'off': 'No enlarging', '1080p': 'Model to 1080p, then resample', '1440p': 'Model to 1440p, then resample', 'full': 'Model to the full output size'}
MIN_RATIO = 1.5                     # upscale only when the output would need at least this many times the source's pixels per degree (below that a plain scaler is as good)
MAX_FACTOR = 4
MIN_ZOOM = 2.5                      # a shot is enlarged only when MORE than MIN_SECONDS of it need at least this many times the source's pixels per degree (zoom); the whole shot is then enlarged, so the look does not change part way through. 2.5 leaves the 85 degree views (2.26x) alone and takes the 80 degree and tighter ones
MIN_SECONDS = 0.5
_model = {}


def weights_path(name=None, root=None):
    folder, file, _, _ = MODELS[name or MODEL]
    return os.path.join(root or os.path.join(os.path.dirname(__file__), '..', '..', '..', 'models'), folder, file)


def normalize(mode):
    """A mode name from a request, a setting or the command line: one of MODES (True is 'full', False and nothing are 'off'); anything else is an error."""
    if mode in (None, False, '', 'off'): return 'off'
    if mode is True: return 'full'
    if mode in MODES: return mode
    raise ValueError(f"enlarge must be one of {', '.join(MODES)}")


def target_width(mode, out_w):
    """The width the model works up to for this mode: 0 when it is off, else the mode's width, never more than the output's."""
    w = MODES[normalize(mode)]
    return 0 if w == 0 else out_w if w is None else min(w, out_w)


def factor_for(source_px_per_deg, out_px, narrowest_fov):
    """How many times to enlarge every picture of a shot: the output needs `out_px / narrowest_fov` pixels per degree at the shot's tightest view; the source has `source_px_per_deg`. Returns 1 (leave alone) or an integer 2..4.
    Pass the narrowest FOV of the whole shot, so one tight moment upscales the entire shot."""
    ratio = (out_px / narrowest_fov) / source_px_per_deg
    return 1 if ratio < MIN_RATIO else int(min(MAX_FACTOR, max(2, round(ratio))))


def seconds_over(t, fov, dur_s, out_w, source_px_per_deg, min_zoom, step=0.05):
    """How many seconds of a shot need at least `min_zoom`: its camera path (keyframe times `t`, horizontal fields of view `fov` in degrees) is read every `step` seconds over `dur_s` (the whole shot when it has one keyframe or no length), and the zoom at each is (out_w / fov) / source_px_per_deg."""
    t = np.asarray(t, float); fov = np.asarray(fov, float); need = lambda f: (out_w / f) / source_px_per_deg >= min_zoom - 1e-9
    if len(t) < 2 or not dur_s: return float(dur_s or 1.0) if need(float(fov.min())) else 0.0
    ts = np.arange(0.0, float(dur_s), step) + step / 2; f = np.interp(ts, t - t[0], fov); return float(need(f).sum() * step)


def load(name=None):
    name = name or MODEL
    if name not in _model:
        try:
            import torch
            from spandrel import ModelLoader
        except ImportError as e: raise RuntimeError(f'enlarging needs the torch and spandrel packages ({e.name} is missing): pip install -r requirements.txt') from e
        p = weights_path(name)
        if not os.path.exists(p): raise FileNotFoundError(f'{p} is missing: download {MODELS[name][2]}')
        dev = 'mps' if torch.backends.mps.is_available() else 'cpu'
        _model[name] = (ModelLoader().load_from_file(p).model.eval().to(dev), dev)
    return _model[name]


def upscale(img, factor, wrap_x=False, model=None, name=None, bgr=True):
    """A picture `factor` times larger (2, 3 or 4), tile by tile. `img` is uint8 or uint16 (the film's working values: 16-bit, so a sky is not banded), BGR by default or RGB with `bgr=False`; the result has the same type and order.
    Each tile is enlarged 4x then brought to `factor` (area), so memory stays at the size of the result. `wrap_x`: an equirectangular picture, whose left and right edges meet."""
    import torch
    name = name or MODEL; TILE = MODELS[name][3]; m, dev = model or load(name); h, w = img.shape[:2]; top = 255.0 if img.dtype == np.uint8 else 65535.0; dt = np.uint8 if img.dtype == np.uint8 else np.uint16
    if wrap_x: img = np.concatenate([img[:, -PAD:], img, img[:, :PAD]], 1)
    H, W = img.shape[:2]; px = PAD if wrap_x else 0; oh, ow = h * factor, w * factor; out = np.zeros((oh, ow, 3), dt)
    x = torch.from_numpy(np.ascontiguousarray(img[..., ::-1] if bgr else img)).permute(2, 0, 1).float().div(top)[None]
    for y0 in range(0, h, TILE):
        for x0 in range(px, px + w, TILE):
            ya, yb, xa, xb = max(y0 - PAD, 0), min(y0 + TILE + PAD, H), max(x0 - PAD, 0), min(x0 + TILE + PAD, W)
            with torch.no_grad(): o = m(x[:, :, ya:yb, xa:xb].to(dev))[0].clamp(0, 1).permute(1, 2, 0).cpu().numpy()
            t = (o * top + .5).astype(dt)
            if bgr: t = t[..., ::-1]
            if factor != 4: t = cv2.resize(np.ascontiguousarray(t), (t.shape[1] * factor // 4, t.shape[0] * factor // 4), interpolation=cv2.INTER_AREA)
            f = factor / 4.0; oy, ox = int(round((y0 - ya) * 4 * f)), int(round((x0 - xa) * 4 * f)); hh, ww = min(TILE, h - y0) * factor, min(TILE, w + px - x0) * factor
            ww = min(ww, ow - (x0 - px) * factor); out[y0 * factor:y0 * factor + hh, (x0 - px) * factor:(x0 - px) * factor + ww] = t[oy:oy + hh, ox:ox + ww]
    return out


def cached(path, factor, box=None, log=print, name=None):
    """The picture at `path` enlarged by `factor`, kept beside it (made once). `box` = (x0, x1, y0, y1) in the picture's pixels enlarges only that window (x may run past either edge: an equirectangular picture wraps); the result is
    (x1 - x0) * factor wide. Only the part of a panorama a shot ever looks at needs enlarging, which is a fraction of the sphere."""
    tag = '' if box is None else '.w%d_%d_%d_%d' % tuple(box)
    name = name or MODEL; out = f'{os.path.splitext(path)[0]}{tag}.{name}.x{factor}.jpg'
    if os.path.exists(out):
        im = cv2.imread(out)
        if im is not None: return im
    im = cv2.imread(path)
    if im is None: raise RuntimeError(f'{path} cannot be read')
    if box is not None: x0, x1, y0, y1 = box; im = np.ascontiguousarray(np.take(im[y0:y1], np.arange(x0, x1), axis=1, mode='wrap'))
    log(f'upscaling {os.path.basename(path)}{tag} x{factor} ({im.shape[1]}x{im.shape[0]})'); up = upscale(im, factor, name=name)
    tmp = out + '.part.jpg'; cv2.imwrite(tmp, up, [cv2.IMWRITE_JPEG_QUALITY, 95]); os.replace(tmp, out); return up


def skip_reason(clip_dir):
    """Why a footage clip is left alone, or None: the same night test the object detector uses (`analysis.objects.clip_is_dark`: the sun well below the horizon and a dim exposure), read from the clip's `sun.json` and `exposure.json`.
    Night footage has nothing for the model to recover (the camera's own noise reduction has already smeared it), and lifting the exposure first did not change that. Needs the clip's `sun` stage to have run (without `sun.json` nothing is excluded)."""
    import json
    from strata360.analysis import objects
    from strata360.gps import sun as SUN
    try: exposure = json.load(open(os.path.join(clip_dir, 'exposure.json')))
    except (OSError, ValueError): exposure = None
    return objects.clip_is_dark(SUN.load(clip_dir), exposure)
