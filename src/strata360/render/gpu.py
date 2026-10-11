"""The renderer's per-pixel work on the GPU (CUDA through torch): the lens frames are uploaded once, and the overlap band of the seam / parallax measurement, the resampling of both lenses and the blend all run there.

Same maths as the CPU code in render/flat.py (`Renderer._render_scene`), render/seam.py (`SeamCarver.band`) and render/parallax.py (`Warp.apply`); the CPU code stays the reference and the fallback
(no CUDA, `STRATA_GPU_RENDER=0`). Differences are rounding only: bilinear / bicubic sampling in float32 instead of cv2's fixed point (tests/integration/test_gpu_render.py compares the two).

Conventions: images are float32 (1, 3, H, W) tensors holding 16-bit code values; sampling coordinates are pixel units where an integer is a pixel centre (cv2.remap), which is `align_corners=True` in grid_sample;
the coarse maps the renderer computes on its 1/8 grid are enlarged to the output size with `align_corners=False` (cv2.resize's half-pixel centres)."""
import os, warnings
import numpy as np
from strata360 import hw

warnings.filterwarnings('ignore', message='The given NumPy array is not writable')
_DEV = 'cuda'
_state = {}


def available():
    """True when the GPU path may be used: CUDA is there and `STRATA_GPU_RENDER` is not 0."""
    if os.environ.get('STRATA_GPU_RENDER') == '0': return False
    if 'ok' not in _state:
        try: _state['ok'] = hw.gpu_device() == 'cuda'
        except Exception: _state['ok'] = False
    return _state['ok']


def _t():
    import torch
    return torch


def to_gpu(img):
    """(H, W, 3) uint16 code values -> float32 (1, 3, H, W) on the GPU. The last four uploads are kept (the seam update and the render of one frame use the same pair)."""
    if isinstance(img, GpuFrame): return img.t
    cache = _state.setdefault('frames', [])
    for ref, t in cache:
        if ref is img: return t
    torch = _t(); a = np.ascontiguousarray(img)
    f = torch.from_numpy(a.view(np.int16)).to(_DEV).to(torch.float32); f = torch.where(f < 0, f + 65536.0, f)
    t = f.permute(2, 0, 1).unsqueeze(0).contiguous(); cache.append((img, t)); del cache[:-4]; return t


def to_numpy16(t):
    """float32 (3, H, W) or (H, W, 3) code values -> (H, W, 3) uint16 numpy."""
    torch = _t()
    if t.shape[0] == 3 and t.ndim == 3: t = t.permute(1, 2, 0)
    i = torch.clamp(torch.round(t), 0, 65535).to(torch.int32); i = torch.where(i > 32767, i - 65536, i).to(torch.int16)
    return i.cpu().numpy().view(np.uint16)


def _tensor(key, make):
    """A numpy array turned into a GPU tensor once (keyed by the array's identity; the array is kept so its id stays valid)."""
    cache = _state.setdefault('tensors', {})
    hit = cache.get(id(key))
    if hit is not None and hit[0] is key: return hit[1]
    t = make(); cache[id(key)] = (key, t)
    if len(cache) > 64: cache.pop(next(iter(cache)))
    return t


def remap(img_t, u, v, mode='bilinear'):
    """cv2.remap(img, u, v, interpolation, BORDER_CONSTANT 0) on the GPU: u, v (h, w) float tensors in pixel units; returns (1, 3, h, w), cubic overshoot clamped to the 16-bit range."""
    torch = _t(); F = torch.nn.functional; H, W = img_t.shape[-2:]
    grid = torch.stack([u * (2.0 / (W - 1)) - 1.0, v * (2.0 / (H - 1)) - 1.0], -1).unsqueeze(0)
    out = F.grid_sample(img_t, grid.to(img_t.dtype), mode=mode, padding_mode='zeros', align_corners=True)
    return torch.clamp(out, 0.0, 65535.0)


def project(lens, d):
    """osv/calib.py Lens.project on the GPU, in float64: body-frame unit directions (N, 3) -> (u, v, theta)."""
    torch = _t(); R = _tensor(lens, lambda: torch.tensor(lens.R, dtype=torch.float64, device=_DEV)); dd = d @ R.T
    th = torch.acos(torch.clamp(dd[:, 2], -1, 1)); phi = torch.atan2(dd[:, 1], dd[:, 0]); k = lens.k
    thd = th * (1 + sum(float(k[i]) * th ** (2 * (i + 1)) for i in range(5)))
    return lens.cx + lens.fx * thd * torch.cos(phi), lens.cy + lens.fy * thd * torch.sin(phi), th


def warp_apply(warp, d, sign):
    """render/parallax.py Warp.apply on the GPU: directions as the master (+1) or slave (-1) lens should sample them."""
    torch = _t(); from strata360.render import seam as SM
    g_lon, g_lat = _tensor(warp, lambda: (torch.tensor(warp.dlon, dtype=torch.float64, device=_DEV), torch.tensor(warp.dlat, dtype=torch.float64, device=_DEV)))
    lat = torch.asin(torch.clamp(d[:, 1], -1.0, 1.0)); lon = torch.atan2(d[:, 2], d[:, 0]); latd = torch.rad2deg(lat)
    if not bool((latd.abs() < SM.BAND_DEG).any()): return d
    rows, cols = g_lon.shape; u = (lon + np.pi) / (2 * np.pi) * cols - 0.5; i0 = torch.floor(u); f = u - i0; a = (i0.long() % cols); b = ((i0.long() + 1) % cols)
    v = (SM.BAND_DEG - latd) / (2 * SM.BAND_DEG) * rows - 0.5; inside = (v > -1.0) & (v < rows)
    j0 = torch.clamp(torch.floor(v).long(), 0, rows - 1); j1 = torch.clamp(j0 + 1, 0, rows - 1); gv = torch.clamp(v - torch.floor(v), 0, 1)
    def sample(g):
        top = g[j0, a] * (1 - f) + g[j0, b] * f; bot = g[j1, a] * (1 - f) + g[j1, b] * f
        return torch.where(inside, top * (1 - gv) + bot * gv, torch.zeros_like(top))
    near = latd.abs() < SM.BAND_DEG; dl = torch.where(near, sample(g_lon), torch.zeros_like(f)); dt = torch.where(near, sample(g_lat), torch.zeros_like(f))
    la = lat + sign * dt; lo = lon + sign * dl
    return torch.stack([torch.cos(la) * torch.cos(lo), torch.sin(la), torch.cos(la) * torch.sin(lo)], -1)


def _occl_t(omap):
    torch = _t(); return _tensor(omap, lambda: torch.from_numpy(np.ascontiguousarray(omap, dtype=np.float32) - 1.0).to(_DEV)[None, None])


def sample_occl(omap, u, v, scale=0.5):
    """render/photo.py sample_occl: the occlusion map at (u, v) lens pixels, 1 outside the map (sampled as map - 1 with zero padding, plus 1)."""
    torch = _t(); F = torch.nn.functional; m = _occl_t(omap); n = m.shape[-1]
    grid = torch.stack([(u * scale) * (2.0 / (n - 1)) - 1.0, (v * scale) * (2.0 / (n - 1)) - 1.0], -1).unsqueeze(0).to(torch.float32)
    return F.grid_sample(m, grid, mode='bilinear', padding_mode='zeros', align_corners=True)[0, 0] + 1.0


def lens_weight(theta_deg, occl, theta_max, feather):
    """render/photo.py lens_weight."""
    torch = _t(); x = torch.clamp((theta_max - theta_deg) / feather, 0, 1); w = x * x * (3 - 2 * x) * occl
    return torch.where(theta_deg > theta_max, torch.zeros_like(w), w)


def band(carver, img_m, img_s, warp=None):
    """SeamCarver.band on the GPU: [(luma, coverage), (luma, coverage)] as float32 numpy arrays (BAND_ROWS, BAND_COLS)."""
    torch = _t(); from strata360.render import seam as SM, photo as ph
    d = _tensor(carver, lambda: torch.from_numpy(carver.dirs).to(_DEV, torch.float64)); out = []
    for img, lens, om, sign in ((img_m, carver.master, carver.occl_m, 1), (img_s, carver.slave, carver.occl_s, -1)):
        u, v, th = project(lens, d if warp is None else warp_apply(warp, d, sign)); u2 = u.to(torch.float32).reshape(SM.BAND_ROWS, SM.BAND_COLS); v2 = v.to(torch.float32).reshape(SM.BAND_ROWS, SM.BAND_COLS)
        rgb = remap(to_gpu(img), u2, v2)[0] / 65535.0; y = rgb[0] * 0.2126 + rgb[1] * 0.7152 + rgb[2] * 0.0722
        cov = lens_weight(torch.rad2deg(th).reshape(SM.BAND_ROWS, SM.BAND_COLS).to(torch.float32), sample_occl(om, u2, v2), ph.THETA_MAX_DEG, ph.ANALYSIS_FEATHER_DEG)
        out.append(torch.stack([y.to(torch.float32), cov.to(torch.float32)]))
    both = torch.stack(out).cpu().numpy()                                                              # one transfer (one wait for the GPU) for the four bands
    return [(both[0, 0], both[0, 1]), (both[1, 0], both[1, 1])]


def _luts():
    torch = _t()
    if 'luts' not in _state:
        from strata360.render import photo as ph
        _state['luts'] = (torch.from_numpy(ph.EOTF_LUT).to(_DEV), torch.from_numpy(ph._OETF_LUT.astype(np.int32)).to(_DEV))
    return _state['luts']


def compose(R, L_master, L_slave, um, vm, us, vs, wn, cover, keep=False):
    """The full-resolution half of Renderer._render_scene on the GPU. um, vm, us, vs: lens pixel coordinates, wn: the master's share, cover: where any lens sees, all on the renderer's coarse grid (numpy).
    Returns the (H, W, 3) uint16 picture, or with `keep` a GpuFrame (the picture stays on the GPU for the next step)."""
    torch = _t(); F = torch.nn.functional; W, H = R.W, R.H
    fin = (lambda t: GpuFrame(torch.round(t).clamp_(0, 65535)[None])) if keep else to_numpy16
    mode = {'cubic': 'bicubic', 'linear': 'bilinear', 'lanczos': 'bicubic'}[{1: 'linear', 2: 'cubic', 4: 'lanczos'}[int(R.interp)]]
    T = lambda a: a if isinstance(a, torch.Tensor) else torch.from_numpy(np.ascontiguousarray(a)).to(_DEV)                            # the coarse maps arrive as numpy (CPU maths) or tensors (scene())
    up = lambda a: F.interpolate(T(a).to(torch.float32)[None, None], size=(H, W), mode='bilinear', align_corners=False)[0, 0]
    cover = T(cover); wn = T(wn)
    im, is_ = to_gpu(L_master), to_gpu(L_slave)
    lutm, luts = R._lut if R._lut else (None, None)
    lut_t = None if lutm is None else [_tensor(l, lambda l=l: torch.from_numpy(np.ascontiguousarray(l).astype(np.int32)).to(_DEV)) for l in (lutm, luts)]
    def single(img, uu, vv, lut):
        out = torch.round(remap(img, up(uu), up(vv), mode))[0]
        return out if lut is None else torch.stack([lut[c][out[c].long()].to(torch.float32) for c in range(3)], 0)
    allc = bool(cover.all())
    if allc and bool(wn.min() > 0.9995): return fin(single(im, um, vm, None if lut_t is None else _lut_tab(lutm)))
    if allc and bool(wn.max() < 0.0005): return fin(single(is_, us, vs, None if lut_t is None else _lut_tab(luts)))
    a = torch.round(remap(im, up(um), up(vm), mode))[0]; b = torch.round(remap(is_, up(us), up(vs), mode))[0]
    wnf = up(wn); covf = up(cover.to(torch.float32)) > 0.5
    m_only = (wnf >= 0.9995) & covf; s_only = (wnf <= 0.0005) & covf; band_ = (wnf > 0.0005) & (wnf < 0.9995) & covf
    if lutm is not None:
        la, lb = _lut_tab(lutm), _lut_tab(luts)
        a = torch.stack([la[c][a[c].long()].to(torch.float32) for c in range(3)], 0); b = torch.stack([lb[c][b[c].long()].to(torch.float32) for c in range(3)], 0)
    out = torch.where(s_only[None], b, a); out = torch.where(covf[None], out, torch.zeros_like(out))
    eotf, oetf = _luts()
    gm = 1.0 if lutm is not None else torch.tensor(R.gain_m, dtype=torch.float32, device=_DEV)[:, None, None]; gs = 1.0 if lutm is not None else torch.tensor(R.gain_s, dtype=torch.float32, device=_DEV)[:, None, None]
    w = wnf[None]; lin = w * (gm * eotf[a.long()]) + (1 - w) * (gs * eotf[b.long()])
    code = oetf[torch.clamp(lin * 65535.0 + 0.5, 0, 65535).long()].to(torch.float32)
    out = torch.where(band_[None], code, out)
    return fin(out)


def _lut_tab(lut):
    torch = _t(); return _tensor(lut, lambda: torch.from_numpy(np.ascontiguousarray(lut).astype(np.int32)).to(_DEV))


# ---- video in and out: the colour conversions between the codec's YUV and the renderer's 16-bit RGB, on the GPU -----------------------------------------------------------------------------------
# ffmpeg's own conversion (swscale) runs on the CPU, about 65 ms for a 3840 x 3840 frame and one core per stream, which with six renders at once used the whole CPU. The video is read as native 10-bit
# YUV (p010, half the bytes) and converted here instead. Measured against swscale on a real frame: mean difference 45 of 65535 codes (under one 10-bit step), the larger differences are at the edges of
# saturated colours where the chroma is upsampled differently (BT.709, limited range, chroma sited left; swscale scales its 16-bit range by 255/256 and 256/255, which is copied).

class GpuFrame:
    """A decoded lens frame that lives on the GPU: float32 (1, 3, H, W) of 16-bit code values. Stands in for the (H, W, 3) uint16 array of the CPU path wherever the GPU renderer reads a frame."""
    def __init__(self, t): self.t = t

    @property
    def shape(self): return (self.t.shape[2], self.t.shape[3], 3)

    def numpy(self): return to_numpy16(self.t[0])


def native_decode():
    """Decode lens streams to native YUV and convert on the GPU (`STRATA_GPU_DECODE=0` keeps ffmpeg's conversion)."""
    return available() and os.environ.get('STRATA_GPU_DECODE') != '0'


def p010_bytes(side):
    """Bytes of one p010 frame of side x side pixels (16-bit samples: the Y plane, then U and V interleaved at half size)."""
    return side * side * 3


def _up2(c):
    """Chroma plane (h, w) -> (2h, 2w), sited left (a chroma sample sits on the even luma column, between two luma rows), bilinear."""
    torch = _t(); F = torch.nn.functional
    r = torch.cat([c, c[:, -1:]], 1); x = torch.empty(c.shape[0], 2 * c.shape[1], device=c.device, dtype=c.dtype); x[:, 0::2] = c; x[:, 1::2] = 0.5 * (r[:, :-1] + r[:, 1:])
    p = F.pad(x[None, None], (0, 0, 1, 1), mode='replicate')[0, 0]; o = torch.empty(2 * c.shape[0], x.shape[1], device=c.device, dtype=c.dtype)
    o[0::2] = 0.75 * x + 0.25 * p[:-2]; o[1::2] = 0.75 * x + 0.25 * p[2:]
    return o


def frame_from_p010(buf, side):
    """The bytes of a p010 frame -> GpuFrame of RGB code values (what ffmpeg's -pix_fmt rgb48le gave, BT.709 limited range)."""
    torch = _t()
    raw = torch.from_numpy(np.frombuffer(buf, dtype=np.int16)).to(_DEV).to(torch.float32); raw = torch.where(raw < 0, raw + 65536.0, raw) / 64.0
    y = (raw[:side * side].view(side, side) - 64.0) / 876.0; uv = raw[side * side:].view(side // 2, side // 2, 2)
    cb = (_up2(uv[..., 0].contiguous()) - 512.0) / 896.0; cr = (_up2(uv[..., 1].contiguous()) - 512.0) / 896.0
    rgb = torch.stack([y + 1.5748 * cr, y - 0.187324 * cb - 0.468124 * cr, y + 1.8556 * cb], 0).clamp_(0.0, 1.0) * (65535.0 * 255.0 / 256.0)
    return GpuFrame(rgb.unsqueeze(0).contiguous())


def rgb48_to_p010(img):
    """(H, W, 3) uint16 RGB code values (full range) -> bytes of a p010le frame, BT.709 limited range, chroma by the mean of 2 x 2 (what `scale=in_range=full:out_range=tv:out_color_matrix=bt709` gave, to within a
    quarter of a 10-bit step in the luma). H and W must be even."""
    torch = _t()
    if isinstance(img, GpuFrame): f = img.t[0].permute(1, 2, 0) / 65535.0
    else:
        a = np.ascontiguousarray(img); f = torch.from_numpy(a.view(np.int16)).to(_DEV).to(torch.float32); f = torch.where(f < 0, f + 65536.0, f) / 65535.0
    r, g, b = f[..., 0], f[..., 1], f[..., 2]; y = 0.2126 * r + 0.7152 * g + 0.0722 * b; k = 256.0 / 255.0
    cb = (b - y) / 1.8556; cr = (r - y) / 1.5748; box = lambda c: 0.25 * (c[0::2, 0::2] + c[0::2, 1::2] + c[1::2, 0::2] + c[1::2, 1::2])
    q = lambda x, lo, hi: (torch.clamp(torch.round(x), lo, hi) * 64.0).to(torch.int32)
    Y = q(64.0 + 876.0 * k * y, 64, 943); U = q(512.0 + 896.0 * k * box(cb), 64, 960); V = q(512.0 + 896.0 * k * box(cr), 64, 960)
    out = torch.cat([Y.reshape(-1), torch.stack([U, V], -1).reshape(-1)]); out = torch.where(out > 32767, out - 65536, out).to(torch.int16)
    return out.cpu().numpy().tobytes()


def seam_share(seam, d):
    """render/seam.py Seam.master_share on the GPU: the master lens's share (0..1) for body-frame unit directions d (N, 3) float64."""
    torch = _t(); lat_a, hw_a = _tensor(seam, lambda: (torch.from_numpy(np.asarray(seam.lat, np.float64)).to(_DEV), torch.from_numpy(np.asarray(seam.hw, np.float64)).to(_DEV))); n = len(lat_a)
    lat = np.pi / 2 - torch.acos(torch.clamp(d[:, 1], -1.0, 1.0)); lon = torch.atan2(d[:, 2], d[:, 0]); u = (lon + np.pi) / (2 * np.pi) * n - 0.5; i0 = torch.floor(u); f = u - i0; a = i0.long() % n; b = (i0.long() + 1) % n
    s = lat_a[a] * (1 - f) + lat_a[b] * f; h = torch.clamp(hw_a[a] * (1 - f) + hw_a[b] * f, min=1e-5); x = torch.clamp((lat - s) / (2 * h) + 0.5, 0, 1); return x * x * (3 - 2 * x)


def scene(R, L_master, L_slave, d, keep=False):
    """Renderer._render_scene entirely on the GPU: the lens projection of the rays `d` (N, 3, body frame, numpy), the stick and field-of-view weights, the carved seam, the rescue, then `compose`. One round trip for the whole picture."""
    torch = _t(); from strata360.render import photo as ph, seam as SM
    dt = torch.from_numpy(np.ascontiguousarray(d, np.float64)).to(_DEV); gh, gw = R.gh, R.gw; per = []
    for lens, om, sign in ((R.master, R.occl_m, 1), (R.slave, R.occl_s, -1)):
        u, v, th = project(lens, dt if R.warp is None else warp_apply(R.warp, dt, sign)); u = u.to(torch.float32).reshape(gh, gw); v = v.to(torch.float32).reshape(gh, gw); thd = torch.rad2deg(th).to(torch.float32).reshape(gh, gw)
        per.append((u, v, thd, sample_occl(om, u, v)))
    (um, vm, tm, ocm), (us, vs, ts, ocs) = per
    wm = lens_weight(tm, ocm, R.rtm, ph.RENDER_FEATHER_DEG); ws = lens_weight(ts, ocs, R.rtm, ph.RENDER_FEATHER_DEG)
    if R.seam is not None:
        t = seam_share(R.seam, dt).reshape(gh, gw).to(torch.float32); vis_m = lens_weight(tm, ocm, R.rtm, SM.EDGE_RAMP_DEG); vis_s = lens_weight(ts, ocs, R.rtm, SM.EDGE_RAMP_DEG)
        wm, ws = t * vis_m, (1.0 - t) * vis_s; dead = (wm + ws) < 1e-3; wm = torch.where(dead, vis_m, wm); ws = torch.where(dead, vis_s, ws)
    dead = (wm + ws) <= 1e-4; tiny = torch.full_like(wm, 1e-3); wm = torch.where(dead & (tm <= ph.THETA_MAX_DEG) & (ocm > 0), tiny, wm); ws = torch.where(dead & (ts <= ph.THETA_MAX_DEG) & (ocs > 0), tiny, ws)
    wsum = wm + ws; cover = wsum > 1e-4; wn = torch.where(cover, wm / torch.clamp(wsum, min=1e-9), torch.zeros_like(wsum))
    return compose(R, L_master, L_slave, um, vm, us, vs, wn, cover, keep)
