"""Fit a dual-fisheye lens model from the overlap band of the two lenses.

Model (equidistant fisheye): pixel radius r = f * theta, theta = angle from the lens optical axis.
Lens A looks along +z, lens B along -z (rotated 180 deg about y) plus small rotation errors.
Parameters: f (px/rad, shared), centre (cx, cy) per lens, small rotation of B (rx, ry, rz).
Objective: robust photometric difference between the two lenses over directions that both see.

Usage: python fit_lens.py lens0.png lens1.png [scale]
"""
import sys, numpy as np, cv2
from scipy.optimize import least_squares

def load(p, scale):
    im = cv2.imread(p, cv2.IMREAD_UNCHANGED)
    g = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY).astype(np.float32)
    g /= 65535.0 if im.dtype == np.uint16 else 255.0
    if scale != 1: g = cv2.resize(g, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    g = cv2.GaussianBlur(g, (0, 0), 1.5)
    return g

def rotmat(rx, ry, rz):
    return cv2.Rodrigues(np.array([rx, ry, rz], dtype=np.float64))[0]

def sample(img, f, cx, cy, d):
    theta = np.arccos(np.clip(d[:, 2], -1, 1))
    phi = np.arctan2(d[:, 1], d[:, 0])
    r = f * theta
    x = (cx + r * np.cos(phi)).astype(np.float32); y = (cy + r * np.sin(phi)).astype(np.float32)
    return cv2.remap(img, x.reshape(-1, 1), y.reshape(-1, 1), cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=-1).ravel()

def make_dirs(theta_lo, theta_hi, n_theta=24, n_phi=720):
    th = np.deg2rad(np.linspace(theta_lo, theta_hi, n_theta)); ph = np.linspace(-np.pi, np.pi, n_phi, endpoint=False)
    T, P = np.meshgrid(th, ph, indexing='ij')
    return np.stack([np.sin(T) * np.cos(P), np.sin(T) * np.sin(P), np.cos(T)], -1).reshape(-1, 3)

def residual(p, A, B, dirs, w):
    f, cxa, cya, cxb, cyb, rx, ry, rz = p
    a = sample(A, f, cxa, cya, dirs)
    R = rotmat(rx, ry, rz) @ np.diag([-1, 1, -1])   # 180 deg about y, then small error
    db = dirs @ R.T
    b = sample(B, f, cxb, cyb, db)
    ok = (a >= 0) & (b >= 0)
    r = np.where(ok, (a - b) * w, 0.0)
    return r

if __name__ == '__main__':
    scale = float(sys.argv[3]) if len(sys.argv) > 3 else 0.5
    A = load(sys.argv[1], scale); B = load(sys.argv[2], scale)
    H = A.shape[0]
    dirs = make_dirs(84, 96); w = 1.0
    for fov in (180, 186, 190, 194, 198, 204):
        f0 = (H / 2 * 0.96) / np.deg2rad(fov / 2)   # circle ~96% of half-height
        p0 = np.array([f0, H / 2, H / 2, H / 2, H / 2, 0, 0, 0], float)
        r0 = residual(p0, A, B, dirs, w)
        res = least_squares(residual, p0, args=(A, B, dirs, w), loss='soft_l1', f_scale=0.05, x_scale=[f0 * .05, 20, 20, 20, 20, .05, .05, .05], max_nfev=60)
        f, cxa, cya, cxb, cyb, rx, ry, rz = res.x
        eff_fov = 2 * np.degrees((H / 2 * 0.96) / f)
        print(f"start fov {fov}: cost {np.abs(r0).mean():.4f} -> {np.abs(res.fun).mean():.4f} | f={f/scale:.1f}px/rad  (circle r@96% ~ {np.degrees(H/2*0.96/f)*2:.1f}deg)  cA=({cxa/scale:.0f},{cya/scale:.0f}) cB=({cxb/scale:.0f},{cyb/scale:.0f}) rot(deg)=({np.degrees(rx):.2f},{np.degrees(ry):.2f},{np.degrees(rz):.2f})")
