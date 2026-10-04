import sys, cv2, numpy as np, os, glob
D = "/Volumes/Expansion/2026-02-19 - Legends/strata360/clips"; OUT = sys.argv[1]; N = 8
W, H, V, FOV = 3840, 1920, 1024, 100
f = (V/2)/np.tan(np.radians(FOV/2)); xs, ys = np.meshgrid(np.arange(V)-V/2+.5, np.arange(V)-V/2+.5); rays = np.stack([xs/f, np.ones_like(xs), -ys/f], -1)
def maps(yaw):
    c, s = np.cos(yaw), np.sin(yaw); d = rays @ np.array([[c, s, 0], [-s, c, 0], [0, 0, 1]]).T
    return ((np.arctan2(d[..., 0], d[..., 1])/np.pi+1)/2*W).astype(np.float32), ((0.5-np.arcsin(d[..., 2]/np.linalg.norm(d, axis=-1))/np.pi)*H).astype(np.float32)
M = {y: maps(np.radians(y)) for y in range(0, 360, 60)}
for n in sys.argv[2:]:
    d = glob.glob(f'{D}/CAM_*_{n}_D')[0]; cap = cv2.VideoCapture(d + '/proxy.mp4'); fps = cap.get(cv2.CAP_PROP_FPS); nf = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)); os.makedirs(f'{OUT}/{n}', exist_ok=True)
    for k in range(N):
        i = int((k + 0.5) / N * nf); cap.set(cv2.CAP_PROP_POS_FRAMES, i); ok, fr = cap.read()
        if not ok: continue
        for y, (mx, my) in M.items(): cv2.imwrite(f'{OUT}/{n}/{i/fps:06.1f}_yaw{y:03d}.jpg', cv2.remap(fr, mx, my, cv2.INTER_LINEAR))
    print(n, len(os.listdir(f'{OUT}/{n}')), flush=True)
