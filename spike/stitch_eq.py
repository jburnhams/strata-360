"""Stitch the two OSV lens frames to equirect using the file's factory calibration (KB5),
and score against a reference export. Standard layout: lon=(px/W-0.5)*2pi, lat=(0.5-py/H)*pi,
d=(sin lon cos lat, cos lon cos lat, sin lat) in the body frame (X right, Y forward, Z up)."""
import numpy as np, cv2
from osvcalib import Lens

def equirect_dirs(W, H):
    lon = ((np.arange(W) + 0.5) / W - 0.5) * 2 * np.pi
    lat = (0.5 - (np.arange(H) + 0.5) / H) * np.pi
    LON, LAT = np.meshgrid(lon, lat)
    return np.stack([np.sin(LON) * np.cos(LAT), np.cos(LON) * np.cos(LAT), np.sin(LAT)], -1).reshape(-1, 3)

def project(L, d, transpose=False):
    R = L.R.T if transpose else L.R
    dl = np.einsum('nj,ij->ni', d, R)
    t = np.arccos(np.clip(dl[:, 2], -1, 1)); phi = np.arctan2(dl[:, 1], dl[:, 0])
    thd = t * (1 + sum(L.k[i] * t ** (2 * (i + 1)) for i in range(5)))
    return L.cx + L.fx * thd * np.cos(phi), L.cy + L.fy * thd * np.sin(phi), t

def stitch(img_master, img_slave, slot_m, slot_s, W, H, transpose=False, feather=(86.0, 94.0), rot=None):
    """img_* are float32 HxWx3 at scale = img.shape[1]/3840. Returns (H,W,3) float32."""
    sc = img_master.shape[1] / 3840.0
    M, S = Lens(slot_m), Lens(slot_s)
    d = equirect_dirs(W, H)
    if rot is not None: d = np.einsum('nj,ij->ni', d, np.asarray(rot, np.float64))   # d_body = rot @ d_out
    um, vm, tm = project(M, d, transpose); us, vs, ts = project(S, d, transpose)
    def samp(img, u, v):
        return cv2.remap(img, (u * sc).astype(np.float32).reshape(H, W), (v * sc).astype(np.float32).reshape(H, W),
                         cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    a = samp(img_master, um, vm); b = samp(img_slave, us, vs)
    x = np.clip((np.degrees(tm) - feather[0]) / (feather[1] - feather[0]), 0, 1); w = 1 - (x * x * (3 - 2 * x))
    w = w.reshape(H, W, 1).astype(np.float32)
    return a * w + b * (1 - w)

def ncc(a, b, mask=None):
    a = a.astype(np.float64).ravel(); b = b.astype(np.float64).ravel()
    if mask is not None: a = a[mask.ravel()]; b = b[mask.ravel()]
    a -= a.mean(); b -= b.mean()
    return float((a * b).sum() / np.sqrt((a * a).sum() * (b * b).sum()))
