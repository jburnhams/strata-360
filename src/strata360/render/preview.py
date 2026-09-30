"""A rough preview of the whole film, streamed as it is rendered: the planned windows cut from the clips' proxy videos, framed by their camera paths (edit/framing.py), hard cuts, with the clips' own
sound (low, full where someone is talking) under the voice-over track. Written as an HLS "event" playlist, so a browser can start playing after the first two seconds and keeps buffering while the
rest is made.

  <project>/preview/film-<key>/index.m3u8, seg00000.ts ...   the stream (the key identifies plan + voice-over, a changed plan starts a new directory)
  <project>/preview/film-<key>/status.json                    {state, frames_done, frames_total, placeholders: [clip ids without a proxy yet], started, finished}
  <project>/preview/film-<key>/audio.wav                      the mixed sound

Projection: rectilinear for ordinary fields of view, blending to stereographic (little planet) above 100 degrees, so planet / tunnel techniques look right; the globe technique is approximated by a
planet. `heading` and `body` references follow the runner's heading (motion.json). A clip without a proxy yet is a dark card with its name."""
import hashlib, json, os, shutil, subprocess, sys, time
import cv2, numpy as np
from strata360.pipeline import config
from strata360.render.camera import CameraPath

FPS = 25.0


def film_dir(folder, key): return os.path.join(config.race_dir(folder), 'preview', f'film-{key}')


def plan_key(folder, plan):
    vo = os.path.join(config.race_dir(folder), 'voiceover', 'voiceover.wav')
    h = hashlib.sha1(json.dumps(plan['segments'], sort_keys=True, default=str).encode()); h.update(str(os.path.getmtime(vo) if os.path.exists(vo) else 0).encode()); return h.hexdigest()[:10]


class Grid:
    """Output pixel geometry: r (distance from the centre in half-widths) and the unit direction in the image plane."""
    def __init__(self, w, h):
        x = ((np.arange(w) + 0.5) / w * 2 - 1).astype(np.float32)[None, :].repeat(h, 0); y = ((1 - (np.arange(h) + 0.5) / h * 2) * h / w).astype(np.float32)[:, None].repeat(w, 1)
        self.w, self.h = w, h; self.r = np.hypot(x, y); s = np.maximum(self.r, 1e-6); self.cx = x / s; self.cy = y / s


def view_maps(g, eqW, eqH, yaw, pitch, roll, fov):
    """cv2.remap maps for one frame (all angles in radians, fov in degrees)."""
    m = float(np.clip((fov - 100.0) / 100.0, 0.0, 1.0)); fr = min(fov, 170.0)
    th = (1 - m) * np.arctan(g.r * np.tan(np.radians(fr) / 2)) + m * 2 * np.arctan(g.r * np.tan(np.radians(min(fov, 340.0)) / 4))
    cr, sr = np.cos(roll), np.sin(roll); cx = g.cx * cr - g.cy * sr; cy = g.cx * sr + g.cy * cr
    f = np.array([np.sin(yaw) * np.cos(pitch), np.cos(yaw) * np.cos(pitch), np.sin(pitch)]); R = np.array([np.cos(yaw), -np.sin(yaw), 0.0]); U = np.cross(R, f)
    ct, st = np.cos(th), np.sin(th); a = st * cx; b = st * cy
    X = ct * f[0] + a * R[0] + b * U[0]; Y = ct * f[1] + a * R[1] + b * U[1]; Z = ct * f[2] + a * R[2] + b * U[2]
    lon = np.arctan2(X, Y); lat = np.arcsin(np.clip(Z, -1, 1))
    return ((lon / (2 * np.pi) + 0.5) * eqW - 0.5).astype(np.float32), ((0.5 - lat / np.pi) * eqH - 0.5).astype(np.float32)


def frame_camera(path, t_rel, heading_deg):
    """(yaw, pitch, roll, fov) in radians/degrees for one frame of a framing path dict."""
    cp = CameraPath(path['keyframes'], 'world'); ev = cp.evaluate(np.asarray(t_rel, float))
    yaw = ev['yaw'] + (np.radians(heading_deg) if path.get('ref') in ('heading', 'body') else 0.0); fov = np.full_like(ev['fov'], 260.0) if ev['use_disc'] else ev['fov']
    return yaw, ev['pitch'], ev['roll'], fov


def encoder_args():
    """Hardware H.264 where there is one (cheap on the CPU, which the rest of the processing needs), else x264."""
    try: enc = subprocess.run(['ffmpeg', '-v', 'quiet', '-encoders'], capture_output=True, text=True, timeout=20).stdout
    except (OSError, subprocess.SubprocessError): enc = ''
    if sys.platform == 'darwin' and 'h264_videotoolbox' in enc: return ['-c:v', 'h264_videotoolbox', '-b:v', '5M', '-realtime', '1']
    if sys.platform == 'win32' and 'h264_nvenc' in enc: return ['-c:v', 'h264_nvenc', '-preset', 'p1', '-b:v', '5M']
    return ['-c:v', 'libx264', '-preset', 'ultrafast', '-tune', 'zerolatency', '-crf', '26', '-threads', '2']


def card(w, h, text):
    im = np.full((h, w, 3), 24, np.uint8); cv2.putText(im, text, (24, h // 2), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (200, 200, 200), 1, cv2.LINE_AA); return im


def proxy_of(folder, clip):
    p = os.path.join(config.race_dir(folder), 'clips', clip, 'proxy.mp4'); return p if os.path.exists(p) and os.path.exists(os.path.splitext(p)[0] + '.json') else None


def has_audio(p):
    r = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'a', '-show_entries', 'stream=index', '-of', 'csv=p=0', p], capture_output=True, text=True); return bool(r.stdout.strip())


def build_audio(folder, plan, out, total_s):
    """The film's sound: each window's own audio (0.25 gain, 1.0 where people speak) in order, mixed with the voice-over track."""
    inputs = []; chains = []; n = 0
    for g in plan['segments']:
        p = proxy_of(folder, g['clip']); d = g['dur_s']; gain = 1.0 if g.get('speech') else 0.25
        if p and has_audio(p): inputs += ['-ss', f"{g['clip_start_s']:.3f}", '-t', f'{d:.3f}', '-i', p]; chains.append(f"[{n}:a]aresample=48000,aformat=channel_layouts=mono,volume={gain},apad=whole_dur={d:.3f},atrim=0:{d:.3f},afade=t=in:d=0.01,afade=t=out:st={max(d - 0.01, 0):.3f}:d=0.01[s{n}]")
        else: inputs += ['-f', 'lavfi', '-t', f'{d:.3f}', '-i', 'anullsrc=r=48000:cl=mono']; chains.append(f'[{n}:a]anull[s{n}]')
        n += 1
    vo = os.path.join(config.race_dir(folder), 'voiceover', 'voiceover.wav'); chain = ';'.join(chains) + ';' + ''.join(f'[s{i}]' for i in range(n)) + f'concat=n={n}:v=0:a=1[nat]'
    if os.path.exists(vo): inputs += ['-i', vo]; chain += f';[{n}:a]aresample=48000,aformat=channel_layouts=mono[vo];[nat][vo]amix=inputs=2:normalize=0:duration=longest,apad=whole_dur={total_s:.3f},atrim=0:{total_s:.3f},alimiter=limit=0.95[m]'
    else: chain += f';[nat]apad=whole_dur={total_s:.3f},atrim=0:{total_s:.3f}[m]'
    r = subprocess.run(['ffmpeg', '-y', '-v', 'error', *inputs, '-filter_complex', chain, '-map', '[m]', '-ar', '48000', '-ac', '1', out], capture_output=True, text=True)
    if r.returncode: raise RuntimeError('audio: ' + r.stderr[-300:])


def render(folder, plan, framing, px=960, decode_w=3072, progress=None):
    """Render the film into film_dir (see the module docstring). Blocks until done; progress(frames_done, frames_total) is called about once a second."""
    from strata360.analysis import views
    key = plan_key(folder, plan); d = film_dir(folder, key); os.makedirs(d, exist_ok=True); w = px; h = px * 9 // 16 // 2 * 2
    segs = plan['segments']; bounds = [int(round((g['film_start_s'] + g['dur_s']) * FPS)) for g in segs]; starts = [0] + bounds[:-1]; total = bounds[-1]; total_s = total / FPS
    placeholders = sorted({g['clip'] for g in segs if not proxy_of(folder, g['clip'])}); status = lambda state, n, **kw: json.dump(dict(state=state, key=key, frames_done=n, frames_total=total, placeholders=placeholders, started=t0, **kw), open(os.path.join(d, 'status.json.tmp'), 'w')) or os.replace(os.path.join(d, 'status.json.tmp'), os.path.join(d, 'status.json'))
    t0 = time.time(); status('audio', 0); build_audio(folder, plan, os.path.join(d, 'audio.wav'), total_s)
    enc = subprocess.Popen(['ffmpeg', '-y', '-v', 'error', '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-s', f'{w}x{h}', '-r', str(FPS), '-i', '-', '-i', os.path.join(d, 'audio.wav'), '-map', '0:v', '-map', '1:a', *encoder_args(),
                            '-pix_fmt', 'yuv420p', '-g', str(int(FPS * 2)), '-force_key_frames', 'expr:gte(t,n_forced*2)', '-c:a', 'aac', '-b:a', '128k', '-shortest', '-f', 'hls', '-hls_time', '2', '-hls_list_size', '0', '-hls_playlist_type', 'event', '-hls_flags', 'independent_segments',
                            '-hls_segment_filename', os.path.join(d, 'seg%05d.ts'), os.path.join(d, 'index.m3u8')], stdin=subprocess.PIPE)
    g = Grid(w, h); done = 0; last = 0.0; heads = {}; clipdirs = {}
    try:
        for gi, sg in enumerate(segs):
            n = bounds[gi] - starts[gi]; clip = sg['clip']; p = proxy_of(folder, clip); fr = None
            if clip not in heads: cd = os.path.join(config.race_dir(folder), 'clips', clip); heads[clip] = views.heading_fn(cd, json.load(open(os.path.join(cd, 'clip.json')))['source_files']['osv'])
            ts = np.arange(n) / FPS; yaw, pitch, roll, fov = frame_camera(framing[sg['id']], ts, [heads[clip](sg['clip_start_s'] + t) for t in ts])
            dec = None
            if p:
                side = json.load(open(os.path.splitext(p)[0] + '.json')); W, H = side['size']; dw = min(decode_w, W); dh = dw // 2
                dec = subprocess.Popen(['ffmpeg', '-v', 'error', '-ss', f"{sg['clip_start_s']:.3f}", '-i', p, '-t', f"{n / FPS + 0.2:.3f}", '-an', '-vf', f'scale={dw}:{dh}:flags=fast_bilinear', '-r', str(FPS), '-pix_fmt', 'bgr24', '-f', 'rawvideo', '-'], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            for i in range(n):
                if dec is not None:
                    buf = dec.stdout.read(dw * dh * 3)
                    if len(buf) == dw * dh * 3: fr = np.frombuffer(buf, np.uint8).reshape(dh, dw, 3)
                if fr is None or dec is None: img = card(w, h, f'{clip[-9:]}: proxy not made yet')
                else:
                    mx, my = view_maps(g, dw, dh, float(yaw[i]), float(pitch[i]), float(roll[i]), float(fov[i])); img = cv2.remap(fr, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_WRAP)
                enc.stdin.write(img.tobytes()); done += 1
                if time.time() - last > 1.0: last = time.time(); status('rendering', done); progress and progress(done, total)
            if dec is not None: dec.stdout.close(); dec.terminate(); dec.wait()
        enc.stdin.close(); enc.wait(); status('done', total, finished=time.time())
    except BaseException as e:
        try: enc.kill()
        except OSError: pass
        status('error', done, error=f'{type(e).__name__}: {e}'); raise
    return d


def main():
    import argparse
    from strata360.edit import framing as FR, project as PJ
    ap = argparse.ArgumentParser(); ap.add_argument('folder'); ap.add_argument('--px', type=int, default=960); ap.add_argument('--force', action='store_true', help='render again even if this plan was already rendered'); a = ap.parse_args()
    cv2.setNumThreads(2)
    try: os.nice(10)                                                                          # started by the user and waited for: a little above the background processing, well below the desktop
    except (OSError, AttributeError): pass
    edit = PJ.load(a.folder); plan = edit.get('plan')
    if not plan: sys.exit('no plan yet')
    fr = {k: v for k, v in FR.resolve(a.folder, plan).items()}
    key = plan_key(a.folder, plan); root = os.path.dirname(film_dir(a.folder, key))
    for n in os.listdir(root) if os.path.isdir(root) else []:                                   # only the newest build is kept
        if n.startswith('film-') and n != f'film-{key}': shutil.rmtree(os.path.join(root, n), ignore_errors=True)
    d = film_dir(a.folder, key)
    if not a.force and os.path.exists(os.path.join(d, 'status.json')) and json.load(open(os.path.join(d, 'status.json'))).get('state') == 'done': print('already rendered', d); return
    shutil.rmtree(d, ignore_errors=True); print(render(a.folder, plan, fr, px=a.px, progress=lambda i, n: print(f'\r{i}/{n}', end='', flush=True)))


if __name__ == '__main__': main()
