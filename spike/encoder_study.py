"""Which encoder settings preserve the most detail for the final 4K output? (study)"""
import sys, os, subprocess, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np, cv2
import render4k as r4
from telemetry import read_frames, video_pts
from skimage.metrics import structural_similarity as ssim
V = 'videos/CAM_20260221120007_0019_D.OSV'; OUT = sys.argv[1]; N = 24; START = 60
R = r4.Renderer(V, 3840, 2160, 100.0, 'cubic'); tel = read_frames(V)
dm, ds = r4.decoder(V, 1), r4.decoder(V, 0)
ref = []
for k in range(START + N):
    cm = r4.read_frame(dm); cs = r4.read_frame(ds)
    if k >= START:
        M = R.stab_matrix(tel['quat'][k]); fwd = np.array([0, -1.0, 0]); up_b = M @ np.array([0, 0, 1.0])
        ref.append(R.render(cm, cs, fwd, up_b))
dm.kill(); ds.kill()
raw = b''.join(np.ascontiguousarray(f).tobytes() for f in ref)
print('reference frames', len(ref), ref[0].shape, ref[0].dtype)
gray = lambda x: cv2.cvtColor((x / 257).astype(np.uint8) if x.dtype == np.uint16 else x, cv2.COLOR_RGB2GRAY)
lapv = lambda x: float(cv2.Laplacian(gray(x), cv2.CV_32F).var())
ref_sharp = np.mean([lapv(f) for f in ref])
def run(name, codec_args):
    path = f'{OUT}/{name}.mp4'; t0 = time.time()
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgb48le', '-s', '3840x2160', '-r', '50', '-i', '-',
                    '-vf', 'scale=in_range=full:out_range=tv:out_color_matrix=bt709:flags=accurate_rnd+full_chroma_int,format=yuv420p10le'] + codec_args +
                   ['-tag:v', 'hvc1', '-colorspace', 'bt709', '-color_primaries', 'bt709', '-color_trc', 'bt709', '-color_range', 'tv', path], input=raw, check=True)
    el = time.time() - t0
    dec = subprocess.check_output(['ffmpeg', '-v', 'error', '-i', path, '-vf', 'scale=in_range=tv:out_range=full:in_color_matrix=bt709:flags=accurate_rnd+full_chroma_int', '-pix_fmt', 'rgb48le', '-f', 'rawvideo', '-'])
    fr = np.frombuffer(dec, np.uint16).reshape(-1, 2160, 3840, 3)
    err = np.mean([np.abs(a.astype(np.float32) - b.astype(np.float32)).mean() for a, b in zip(ref[::4], fr[::4])]) / 64.0   # 10-bit codes
    ss = np.mean([ssim(gray(a), gray(b)) for a, b in zip(ref[::6], fr[::6])])
    sh = np.mean([lapv(f) for f in fr]) / ref_sharp * 100
    mbps = os.path.getsize(path) / (N / 50.0) * 8 / 1e6
    print(f'{name:22s} {mbps:7.0f} Mbit/s   enc {N / el:5.1f} fps   mean abs err {err:5.2f} (10-bit codes)   SSIM {ss:.4f}   detail kept {sh:5.1f}%', flush=True)
VT = lambda b: ['-c:v', 'hevc_videotoolbox', '-profile:v', 'main10', '-b:v', b]
X = lambda crf, preset='medium': ['-c:v', 'libx265', '-preset', preset, '-x265-params', f'crf={crf}:log-level=error']
for n, a in (('vt_80M', VT('80M')), ('vt_150M', VT('150M')), ('vt_300M', VT('300M')),
             ('x265_crf22', X(22)), ('x265_crf18', X(18)), ('x265_crf14', X(14)), ('x265_crf10', X(10)), ('x265_crf14_fast', X(14, 'fast'))):
    run(n, a)
