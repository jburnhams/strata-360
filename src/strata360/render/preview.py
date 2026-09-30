"""A rough preview of the whole film, streamed as it is rendered: the planned windows cut from the clips' proxy videos, framed by their camera paths (edit/framing.py), hard cuts, with the clips' own
sound (low, full where someone is talking) under the voice-over track. Written as an HLS "event" playlist, so a browser can start playing after the first two seconds and keeps buffering while the
rest is made.

  <project>/preview/film-<key>/index.m3u8, seg00000.ts ...   the stream (the key identifies plan + voice-over, a changed plan starts a new directory)
  <project>/preview/film-<key>/status.json                    {state, frames_done, frames_total, placeholders: [clip ids without a proxy yet], started, finished}
  <project>/preview/film-<key>/audio.wav                      the mixed sound

The picture is made by the real renderer's own code (render/flat.py: projection, view rays, the globe with its backgrounds; render/camera.py: the path evaluation, including heading-follow and body
references from the stabilisation), with the clip's proxy (upright equirect) as the picture source instead of the two lenses: what differs from the final render is only the resolution. A clip without
a proxy yet is a dark card with its name."""
import hashlib, json, os, shutil, subprocess, sys, time
import cv2, numpy as np
from strata360.pipeline import config
from strata360.render import camera as cam
from strata360.render.flat import Globe, projection, view_rays

FPS = 25.0


def film_dir(folder, key): return os.path.join(config.race_dir(folder), 'preview', f'film-{key}')


def plan_key(folder, plan):
    vo = os.path.join(config.race_dir(folder), 'voiceover', 'voiceover.wav')
    h = hashlib.sha1(json.dumps(plan['segments'], sort_keys=True, default=str).encode()); h.update(str(os.path.getmtime(vo) if os.path.exists(vo) else 0).encode()); return h.hexdigest()[:10]


class EquirectView(Globe):
    """The real renderer's projection (flat.projection / view_rays) and globe look (flat.Globe), with the picture taken from an equirect frame (the clip's proxy, upright world frame) instead of
    the two lenses. Like the real renderer the maps are computed on a coarse grid; the view rays are upsampled (not the angles, which wrap) and turned into equirect coordinates per pixel."""
    def __init__(self, W, H, grid=4):
        self.W, self.H, self.grid = W, H, grid; gw, gh = W // grid + 1, H // grid + 1
        X, Y = np.meshgrid(np.linspace(0, W, gw), np.linspace(0, H, gh)); self.xn = ((X - W / 2) / (W / 2)).astype(np.float64); self.yn = ((H / 2 - Y) / (W / 2)).astype(np.float64)
        self.gw, self.gh = gw, gh; self.init_globe(); self.set_fov(90.0)

    def set_fov(self, hfov, dist=0.0, disc=None):
        self.disc = None if disc is None else float(disc); self.theta, self.cphi, self.sphi = projection(self.xn, self.yn, hfov, dist, self.disc)

    def maps(self, fwd, up, roll, eqW, eqH):
        """cv2.remap maps (full output size) into an eqW x eqH equirect frame for the view direction `fwd` (world frame) with `up`."""
        d = view_rays(self.theta, self.cphi, self.sphi, fwd, up, roll).reshape(self.gh, self.gw, 3).astype(np.float32)
        D = [cv2.resize(np.ascontiguousarray(d[..., k]), (self.W, self.H), interpolation=cv2.INTER_LINEAR) for k in range(3)]
        n = np.sqrt(D[0] ** 2 + D[1] ** 2 + D[2] ** 2) + 1e-9; lon = np.arctan2(D[0], D[1]); lat = np.arcsin(np.clip(D[2] / n, -1, 1))
        return ((lon / (2 * np.pi) + 0.5) * eqW - 0.5).astype(np.float32), ((0.5 - lat / np.pi) * eqH - 0.5).astype(np.float32)

    def _render_scene(self, eq, fwd, up, roll=0.0):
        mx, my = self.maps(fwd, up, roll, eq.shape[1], eq.shape[0]); return cv2.remap(eq, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_WRAP)

    def _small_planet(self, eq, fwd, up, roll):                                     # uint16 code values, as the globe compositing expects
        if self._bgR is None or self._bgR.W != self.W // 8:
            self._bgR = EquirectView(self.W // 8, self.H // 8, grid=2); self._bgR.set_fov(260.0, 1.0)
        return self._bgR._render_scene(eq, fwd, up, roll).astype(np.uint16) * 257

    def render(self, eq, fwd, up, roll=0.0):
        out = self._render_scene(eq, fwd, up, roll)
        if self.disc is None: return out
        return (self._apply_globe(out.astype(np.uint16) * 257, eq, fwd, up, roll) >> 8).astype(np.uint8)


def stab_matrices(osv):
    """Per source frame: d_body = M d_world (the real renderer's Renderer.stab_matrix), for paths that follow the heading or sit on the body."""
    from strata360.osv.calib import quat_to_R, imu_offsets
    from strata360.osv.telemetry import read_frames
    P, B = imu_offsets(); T = read_frames(osv)
    return lambda k: B.T @ quat_to_R(np.asarray(T['quat'][min(k, len(T['quat']) - 1)])).T @ P.T


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
    V = EquirectView(w, h); done = 0; last = 0.0; clipinfo = {}; ez = np.array([0.0, 0.0, 1.0])
    try:
        for gi, sg in enumerate(segs):
            n = bounds[gi] - starts[gi]; clip = sg['clip']; p = proxy_of(folder, clip); fr = None; path = cam.CameraPath.from_dict(framing[sg['id']]); V.set_background(path.bg, **path.bg_opts)
            side = json.load(open(os.path.splitext(p)[0] + '.json')) if p else None
            if p and clip not in clipinfo: clipinfo[clip] = (np.array([f['t_s'] for f in side['frames']]), stab_matrices(json.load(open(os.path.join(config.race_dir(folder), 'clips', clip, 'clip.json')))['source_files']['osv']) if path.ref != 'world' else None)
            Ms = None
            if p:
                ts_p, sm = clipinfo[clip]; j0 = int(np.argmin(np.abs(ts_p - sg['clip_start_s'])))
                if path.ref != 'world':
                    if sm is None: sm = clipinfo[clip] = (ts_p, stab_matrices(json.load(open(os.path.join(config.race_dir(folder), 'clips', clip, 'clip.json')))['source_files']['osv'])); sm = sm[1]
                    Ms = [sm(side['frames'][min(j0 + i, len(side['frames']) - 1)]['source_frame']) for i in range(n)]
            P = path.evaluate(np.arange(n) / FPS, Ms, FPS) if p else None; dec = None
            if p:
                W0, H0 = side['size']; dw = min(decode_w, W0); dh = dw // 2
                dec = subprocess.Popen(['ffmpeg', '-v', 'error', '-ss', f"{sg['clip_start_s']:.3f}", '-i', p, '-t', f"{n / FPS + 0.2:.3f}", '-an', '-vf', f'scale={dw}:{dh}:flags=fast_bilinear', '-r', str(FPS), '-pix_fmt', 'bgr24', '-f', 'rawvideo', '-'], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            for i in range(n):
                if dec is not None:
                    buf = dec.stdout.read(dw * dh * 3)
                    if len(buf) == dw * dh * 3: fr = np.frombuffer(buf, np.uint8).reshape(dh, dw, 3)
                if fr is None or dec is None: img = card(w, h, f'{clip[-9:]}: proxy not made yet')
                else:
                    V.set_fov(P['fov'][i], P['dist'][i], P['disc'][i] if P['use_disc'] else None); vdir = cam.direction(P['yaw'][i], P['pitch'][i])
                    img = V.render(fr, Ms[i].T @ vdir if P['ref'] == 'body' else vdir, ez, float(P['roll'][i]))          # the same steps as flat.main: body paths are rotated into the world by the stabilisation
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
