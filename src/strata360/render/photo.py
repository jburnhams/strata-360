"""Port of OpenOSV's photometric handling (Apache-2.0, https://github.com/Kemerd/OpenOSV) for the Normal-colour-mode
(Rec.709 in, Rec.709 out) case: BT.709 transfer in linear light, lens weights (FOV feather x occlusion polygon),
the occlusion rescue, and the exposure-match gain estimated from trusted co-visible pixels.

References (OpenOSV): include/osv/render/osv_kernel.h (osvLensWeight, osvOcclusionFactor, osvShadePixelWSPL, osvGainApply),
src/osv/render/SeamAnalysis.cpp (estimateGain), include/osv/geom/Blend.h (defaults), include/osv/render/PhotoSeam.h
(render-only seam inset), include/osv/color/ColorMath.h (BT.709 curves), plugins/importer/ImporterInstance.cpp (gain per bucket).
"""
import numpy as np, cv2

THETA_MAX_DEG = 97.59            # half of the usable 195.18 deg lens FOV (BlendParams::lensFovDeg)
ANALYSIS_FEATHER_DEG = 4.0       # BlendParams::featherDeg
OCCL_FEATHER_PX = 24.0           # BlendParams::occlusionFeatherPx (in 3840 px lens coordinates)
RENDER_INSET_DEG = 2.6           # kDefaultSeamInsetDeg: the render blend ends inside the calibrated FOV
RENDER_FEATHER_DEG = 3.0         # kSeamInsetFeatherDeg
TRUST_ALPHA = 0.99               # kTrustedAlpha
BAND_W, BAND_HALF_DEG = 2048, 6.0  # BandParams defaults
GAIN_BUCKET = 8                  # frames per gain measurement (importer: bucket = frame / 8)


def oetf709(e):
    e = np.clip(e, 0, 1)
    return np.where(e < 0.018, 4.5 * e, 1.099 * np.power(e, 0.45) - 0.099)

def eotf709(v):
    v = np.clip(v, 0, 1)
    return np.where(v < 0.081, v / 4.5, np.power((v + 0.099) / 1.099, 1 / 0.45))

# 16-bit code (rgb48le, 0..65535) <-> linear light
EOTF_LUT = eotf709(np.arange(65536) / 65535.0).astype(np.float32)
_OETF_LUT = np.clip(np.rint(oetf709(np.arange(65536) / 65535.0) * 65535.0), 0, 65535).astype(np.uint16)

def linear_to_code16(lin):
    return _OETF_LUT[np.clip(lin * 65535.0 + 0.5, 0, 65535).astype(np.uint16)]

def gain_lut(gain):
    """(3, 65536) uint16 tables: code -> code of (gain_c * light(code)), per channel (osvGainCode for Rec.709)."""
    return np.stack([linear_to_code16(EOTF_LUT * np.float32(g)) for g in gain])

def smoothstep(t):
    t = np.clip(t, 0, 1); return t * t * (3 - 2 * t)


def occlusion_map(poly_x, poly_y, size=3840, scale=0.5, feather=OCCL_FEATHER_PX):
    """Signed occlusion factor map at `scale` of the lens frame: 0 inside the polygon, ramping to 1 at `feather` px outside."""
    n = int(size * scale)
    pts = (np.stack([poly_x, poly_y], 1) * scale).astype(np.int32).reshape(-1, 1, 2)
    inside = np.zeros((n, n), np.uint8); cv2.fillPoly(inside, [pts], 255)
    dist = cv2.distanceTransform((inside == 0).astype(np.uint8), cv2.DIST_L2, 5) / scale   # px in lens coordinates, 0 inside
    return np.clip(dist / feather, 0, 1).astype(np.float32)

def sample_occl(omap, u, v, scale=0.5):
    return cv2.remap(omap, (u * scale).astype(np.float32), (v * scale).astype(np.float32), cv2.INTER_LINEAR,
                     borderMode=cv2.BORDER_CONSTANT, borderValue=1.0)


def lens_weight(theta_deg, occl, theta_max, feather):
    """osvLensWeight: 0 past thetaMax, smoothstep FOV feather, times the occlusion factor."""
    w = smoothstep((theta_max - theta_deg) / feather) * occl
    return np.where(theta_deg > theta_max, 0.0, w).astype(np.float32)


def rescue(w0, w1, th0, th1, oc0, oc1, theta_max, thr=1e-4):
    """Occlusion rescue: where both weights vanish, a lens that landed inside its FOV on an unoccluded pixel gets 1e-3."""
    dead = (w0 + w1) <= thr
    if dead.any():
        w0 = np.where(dead & (th0 <= theta_max) & (oc0 > 0), np.float32(1e-3), w0)
        w1 = np.where(dead & (th1 <= theta_max) & (oc1 > 0), np.float32(1e-3), w1)
    return w0, w1


def _remap16(img, u, v, shape):
    return cv2.remap(img, u.astype(np.float32).reshape(shape), v.astype(np.float32).reshape(shape), cv2.INTER_LINEAR,
                     borderMode=cv2.BORDER_CONSTANT, borderValue=0).reshape(-1, 3)   # (rows, cols) shape: remap needs dims < 32767


def estimate_gain(img_master, img_slave, lens_master, lens_slave, occl_master, occl_slave):
    """OpenOSV estimateGain: per-channel exposure match in linear light from trusted co-visible pixels around the seam.
    Returns (gain_master, gain_slave, n_trusted), a symmetric split of the mean ratio, each clamped to [0.5, 2] via sqrt.
    img_* are (3840,3840,3) uint16 code values."""
    rows = int(round(BAND_HALF_DEG * (BAND_W / 2) / 180.0)) * 2
    T = np.radians(90.0 + np.linspace(-BAND_HALF_DEG, BAND_HALF_DEG, rows))
    P = np.linspace(-np.pi, np.pi, BAND_W, endpoint=False)
    TT, PP = np.meshgrid(T, P, indexing='ij')                       # angle from the master axis (+Y) and azimuth around it
    d = np.stack([np.sin(TT) * np.cos(PP), np.cos(TT), np.sin(TT) * np.sin(PP)], -1).reshape(-1, 3)
    lin, alpha = [], []
    for img, L, om in ((img_master, lens_master, occl_master), (img_slave, lens_slave, occl_slave)):
        u, v, th = L.project(d)
        code = _remap16(img, u, v, (rows, BAND_W))
        lin.append(EOTF_LUT[code])                                  # (N,3) linear light
        oc = sample_occl(om, u.reshape(rows, BAND_W), v.reshape(rows, BAND_W)).ravel()
        alpha.append(lens_weight(np.degrees(th), oc, THETA_MAX_DEG, ANALYSIS_FEATHER_DEG))
    trusted = (alpha[0] >= TRUST_ALPHA) & (alpha[1] >= TRUST_ALPHA)
    n = int(trusted.sum())
    if n < 64:
        return np.ones(3), np.ones(3), n
    m0 = lin[0][trusted].mean(0).astype(np.float64); m1 = lin[1][trusted].mean(0).astype(np.float64)
    ratio = np.where((m0 > 1e-6) & (m1 > 1e-6), m1 / np.maximum(m0, 1e-12), 1.0)   # slave / master
    g_m = np.clip(np.sqrt(ratio), 0.5, 2.0)
    return g_m, 1.0 / g_m, n
