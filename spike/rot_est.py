"""Estimate the rotation between two equirect frames (same scene, different orientation) by SIFT + RANSAC-Kabsch."""
import numpy as np, cv2

def rays(pts, W, H):
    lon = (pts[:, 0] / W - 0.5) * 2 * np.pi; lat = (0.5 - pts[:, 1] / H) * np.pi
    return np.stack([np.sin(lon) * np.cos(lat), np.cos(lon) * np.cos(lat), np.sin(lat)], 1)

def kabsch(a, b):
    """R minimising |R a - b| (rows are vectors)."""
    U, _, Vt = np.linalg.svd(b.T @ a); D = np.diag([1, 1, np.sign(np.linalg.det(U @ Vt))])
    return U @ D @ Vt

def estimate(img_a, img_b, seed=0, iters=1500, thr_deg=1.0):
    """Return R (maps dirs of a -> dirs of b), inlier count, total matches."""
    g = lambda im: cv2.cvtColor(im, cv2.COLOR_RGB2GRAY) if im.ndim == 3 else im
    H, W = img_a.shape[:2]
    sift = cv2.SIFT_create(nfeatures=6000)
    ka, da = sift.detectAndCompute(g(img_a), None); kb, db = sift.detectAndCompute(g(img_b), None)
    m = cv2.BFMatcher().knnMatch(da, db, k=2)
    good = [x[0] for x in m if len(x) == 2 and x[0].distance < 0.75 * x[1].distance]
    pa = np.float64([ka[x.queryIdx].pt for x in good]); pb = np.float64([kb[x.trainIdx].pt for x in good])
    ra, rb = rays(pa, W, H), rays(pb, W, H)
    rng = np.random.default_rng(seed); best = (0, None)
    cthr = np.cos(np.radians(thr_deg))
    for _ in range(iters):
        i = rng.choice(len(good), 3, replace=False)
        R = kabsch(ra[i], rb[i]); inl = ((ra @ R.T) * rb).sum(1) > cthr
        if inl.sum() > best[0]: best = (inl.sum(), inl)
    inl = best[1]; R = kabsch(ra[inl], rb[inl])
    inl = ((ra @ R.T) * rb).sum(1) > cthr
    return R, int(inl.sum()), len(good)

def angle_deg(R): return float(np.degrees(np.arccos(np.clip((np.trace(R) - 1) / 2, -1, 1))))
