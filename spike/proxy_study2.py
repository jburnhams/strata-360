"""How do proxy resolution / bitrate / still-frame choices affect recognition-style tasks? (study, not pipeline code)"""
import sys, os, subprocess, json, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np, cv2
import make_proxy as mp, render4k as r4
from telemetry import read_frames, video_pts
from skimage.metrics import structural_similarity as ssim
V = 'videos/CAM_20260221120007_0019_D.OSV'; OUT = sys.argv[1]; N = 24; START = 90   # 24 consecutive proxy frames = 0.96 s
R = mp.EquirectRenderer(V, 3840, 1920); tel = read_frames(V)
dm, ds = mp.decoder(V, 1, 2), mp.decoder(V, 0, 2)
ref = []
for j in range(START + N):
    cm = r4.read_frame(dm); cs = r4.read_frame(ds)
    if j >= START: ref.append(R.render(cm, cs, R.stab_matrix(tel['quat'][2 * j]), None))
dm.kill(); ds.kill()
ref8 = [np.clip(np.rint(f.astype(np.float32) / 257.0), 0, 255).astype(np.uint8) for f in ref]     # 8-bit reference (lossless)
print('reference frames', len(ref8), ref8[0].shape)

def encode(name, size, bitrate, codec='hevc_videotoolbox', extra=None):
    W, H = size; path = f'{OUT}/{name}.mp4'
    rawin = b''.join(np.ascontiguousarray(cv2.resize(f, (W, H), interpolation=cv2.INTER_AREA) if W != 3840 else f).tobytes() for f in ref8)
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{W}x{H}', '-r', '25', '-i', '-',
                    '-vf', 'scale=in_range=full:out_range=tv:out_color_matrix=bt709:flags=accurate_rnd+full_chroma_int,format=yuv420p',
                    '-c:v', codec] + (extra if extra else ['-profile:v', 'main', '-b:v', bitrate]) + ['-tag:v', 'hvc1', '-colorspace', 'bt709', '-color_range', 'tv', path], input=rawin, check=True)
    dec = subprocess.check_output(['ffmpeg', '-v', 'error', '-i', path, '-pix_fmt', 'rgb24', '-f', 'rawvideo', '-'])
    fr = np.frombuffer(dec, np.uint8).reshape(-1, H, W, 3)
    return list(fr), os.path.getsize(path) / (N / 25.0) * 8 / 1e6

def jpeg(name, size, q):
    W, H = size; frs = []; tot = 0
    for f in ref8:
        g = cv2.resize(f, (W, H), interpolation=cv2.INTER_AREA) if W != 3840 else f
        ok, b = cv2.imencode('.jpg', cv2.cvtColor(g, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, q]); tot += len(b)
        frs.append(cv2.cvtColor(cv2.imdecode(b, 1), cv2.COLOR_BGR2RGB))
    return frs, tot / N / 1e6           # MB per frame

# detectors run on the horizon band (lat +-30 deg) where equirect distortion is small
hog = cv2.HOGDescriptor(); hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())
face = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_alt2.xml')
def detect(img):
    """returns boxes in 3840x1920 coordinates: (people, faces)"""
    H, W = img.shape[:2]; s = 3840.0 / W
    y0, y1 = int(H * 0.25), int(H * 0.75); band = cv2.cvtColor(img[y0:y1], cv2.COLOR_RGB2GRAY)
    up = 1.0 if W >= 3840 else 3840.0 / W                                       # detectors want a similar pixel scale: upsample smaller ones
    b = cv2.resize(band, None, fx=up, fy=up, interpolation=cv2.INTER_CUBIC) if up != 1.0 else band
    b = cv2.resize(b, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA)        # search at half of 3840 for speed
    pr, _ = hog.detectMultiScale(b, winStride=(8, 8), padding=(8, 8), scale=1.05, hitThreshold=0.3)
    fr = face.detectMultiScale(b, scaleFactor=1.1, minNeighbors=4, minSize=(30, 30))
    conv = lambda bx: [(x * 2, y * 2 + y0 * (3840.0 / W) * (1 if True else 1), w * 2, h * 2) for (x, y, w, h) in bx]
    # boxes are in 3840-wide band coordinates; add the band offset scaled to 3840 space
    off = y0 * (3840.0 / W)
    return [(x * 2, y * 2 + off, w * 2, h * 2) for (x, y, w, h) in pr], [(x * 2, y * 2 + off, w * 2, h * 2) for (x, y, w, h) in fr]
def iou(a, b):
    ax, ay, aw, ah = a; bx, by, bw, bh = b
    ix = max(0, min(ax + aw, bx + bw) - max(ax, bx)); iy = max(0, min(ay + ah, by + bh) - max(ay, by)); i = ix * iy
    return i / (aw * ah + bw * bh - i + 1e-9)
def recall(det, refdet):
    if not refdet: return float('nan')
    return sum(1 for r in refdet if any(iou(r, d) > 0.3 for d in det)) / len(refdet)

def lapvar(img): return float(cv2.Laplacian(cv2.cvtColor(img, cv2.COLOR_RGB2GRAY), cv2.CV_32F).var())
gray = lambda x: cv2.cvtColor(x, cv2.COLOR_RGB2GRAY)
variants = []
t0 = time.time()
X = lambda crf, extra='': ['-preset', 'medium', '-x265-params', f'crf={crf}:log-level=error' + extra]
for name, size, extra in (('x265_3840_crf20', (3840, 1920), X(20)), ('x265_3840_crf24', (3840, 1920), X(24)), ('x265_3840_crf28', (3840, 1920), X(28)),
                          ('x265_2560_crf22', (2560, 1280), X(22)), ('x265_1920_crf22', (1920, 960), X(22)),
                          ('x265_3840_intra_crf24', (3840, 1920), X(24, ':keyint=1'))):
    fr, mbps = encode(name, size, None, 'libx265', extra); variants.append((name, fr, size, f'{mbps:.0f} Mbit/s'))
for name, size, q in (('jpeg_3840_q90', (3840, 1920), 90),):
    fr, mb = jpeg(name, size, q); variants.append((name, fr, size, f'{mb:.2f} MB/frame ({mb * 25 * 8:.0f} Mbit/s at 25 fps)'))
print(f'encoded {len(variants)} variants in {time.time() - t0:.0f} s')
# reference detections
refdet = [detect(f) for f in ref8]
nref_p = sum(len(p) for p, _ in refdet); nref_f = sum(len(f) for _, f in refdet)
print(f'reference (lossless 3840x1920): {nref_p} person boxes, {nref_f} face boxes over {N} frames; sharpness (Laplacian var) {np.mean([lapvar(f) for f in ref8]):.1f}')
print(f'{"variant":16s} {"rate":38s} {"SSIM(vs ref@3840)":>18s} {"PSNR":>6s} {"sharp%":>7s} {"people recall":>14s} {"faces recall":>13s} {"extra people":>12s} {"extra faces":>11s}')
for name, fr, size, rate in variants:
    up = [cv2.resize(f, (3840, 1920), interpolation=cv2.INTER_CUBIC) if size[0] != 3840 else f for f in fr]
    ss = np.mean([ssim(gray(a), gray(b)) for a, b in zip(ref8[::4], up[::4])])
    mse = np.mean([np.mean((a.astype(np.float32) - b.astype(np.float32)) ** 2) for a, b in zip(ref8[::4], up[::4])]); psnr = 10 * np.log10(255 ** 2 / mse)
    sh = np.mean([lapvar(f) for f in fr]) / np.mean([lapvar(cv2.resize(r, (size[0], size[1]), interpolation=cv2.INTER_AREA)) for r in ref8]) * 100
    dets = [detect(f) for f in fr]
    rp = np.nanmean([recall(d[0], r[0]) for d, r in zip(dets, refdet) if r[0]]); rf = np.nanmean([recall(d[1], r[1]) for d, r in zip(dets, refdet) if r[1]])
    ep = sum(1 for d, r in zip(dets, refdet) for x in d[0] if not any(iou(x, y) > 0.3 for y in r[0])); ef = sum(1 for d, r in zip(dets, refdet) for x in d[1] if not any(iou(x, y) > 0.3 for y in r[1]))
    print(f'{name:16s} {rate:38s} {ss:18.4f} {psnr:6.1f} {sh:7.0f} {rp:14.2f} {rf:13.2f} {ep:12d} {ef:11d}')
