"""A rough preview of the whole film, streamed as it is rendered: the planned windows cut from the clips' proxy videos, framed by their camera paths (edit/framing.py), hard cuts, with the clips' own
sound (low, full where someone is talking) under the voice-over track. Written as an HLS "event" playlist, so a browser can start playing after the first two seconds and keeps buffering while the
rest is made.

  <project>/preview/film-<key>/index.m3u8, seg00000.ts ...   the stream (the key identifies plan + voice-over, a changed plan starts a new directory)
  <project>/preview/film-<key>/status.json                    {state, frames_done, frames_total, placeholders: [clip ids without a proxy yet], started, finished}
  <project>/preview/film-<key>/audio.wav                      the mixed sound

The picture is made by the real renderer's own code (render/flat.py: projection, view rays, the globe with its backgrounds; render/camera.py: the path evaluation, including heading-follow and body
references from the stabilisation), with the clip's proxy (upright equirect) as the picture source instead of the two lenses: what differs from the final render is only the resolution. A clip without
a proxy yet is a dark card with its name."""
from strata360.pipeline import guard
import hashlib, json, os, shutil, subprocess, sys, time
import cv2, numpy as np
from strata360.pipeline import config
from strata360.render import camera as cam
from strata360.render.flat import Globe, projection, view_rays
from strata360.render.film import compose, layout

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


class PreviewSource:
    """Frames of the planned windows from the clips' proxies (upright equirect), through the real renderer's projection (EquirectView). A clip without a proxy gives a dark card."""
    def __init__(self, folder, segs, framing, w, h, decode_w):
        self.folder, self.segs, self.framing, self.w, self.h, self.decode_w = folder, segs, framing, w, h, decode_w; self.V = EquirectView(w, h); self.info = {}; self.done = 0

    def _clip(self, clip):
        if clip not in self.info:
            p = proxy_of(self.folder, clip); side = json.load(open(os.path.splitext(p)[0] + '.json')) if p else None
            self.info[clip] = dict(proxy=p, side=side, ts=np.array([f['t_s'] for f in side['frames']]) if side else None, stab=None)
        return self.info[clip]

    def frames(self, k, a0, a1, yaw_extra=None):
        sg = self.segs[k]; clip = sg['clip']; ci = self._clip(clip); m = a1 - a0
        if m <= 0: return
        if not ci['proxy']:
            for _ in range(m): yield card(self.w, self.h, f'{clip[-9:]}: proxy not made yet')
            return
        path = cam.CameraPath.from_dict(self.framing[sg['id']]); self.V.set_background(path.bg, **path.bg_opts); side = ci['side']; ez = np.array([0.0, 0.0, 1.0])
        t_from = sg['clip_start_s'] + a0 / FPS; fr_n = len(side['frames']); Ms = None
        if path.ref != 'world':                                                          # heading-follow and body paths need the stabilisation of each frame (as the real renderer)
            if ci['stab'] is None: ci['stab'] = stab_matrices(json.load(open(os.path.join(config.race_dir(self.folder), 'clips', clip, 'clip.json')))['source_files']['osv'])
            idx = np.clip(np.round(np.maximum(t_from + np.arange(m) / FPS, 0.0) * FPS).astype(int), 0, fr_n - 1); Ms = [ci['stab'](side['frames'][j]['source_frame']) for j in idx]
        P = path.evaluate(np.arange(a0, a1) / FPS, Ms, FPS)
        W0, H0 = side['size']; dw = min(self.decode_w, W0); dh = dw // 2; lead = max(-t_from, 0.0)                       # time before the clip starts: the first frame is held
        dec = guard.popen(['ffmpeg', '-v', 'error', '-ss', f'{max(t_from, 0.0):.3f}', '-i', ci['proxy'], '-t', f'{(m / FPS) + 0.2:.3f}', '-an', '-vf', f'scale={dw}:{dh}:flags=fast_bilinear', '-r', str(FPS), '-pix_fmt', 'bgr24', '-f', 'rawvideo', '-'], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        fr = None; skip = int(round(lead * FPS))
        try:
            for i in range(m):
                if i >= skip or fr is None:                                                  # before the clip starts (skip frames) the first frame is held
                    buf = dec.stdout.read(dw * dh * 3)
                    if len(buf) == dw * dh * 3: fr = np.frombuffer(buf, np.uint8).reshape(dh, dw, 3)
                    elif fr is None: fr = np.zeros((dh, dw, 3), np.uint8)                   # (past the end of the clip the last frame is held)
                self.V.set_fov(P['fov'][i], P['dist'][i], P['disc'][i] if P['use_disc'] else None); yaw = P['yaw'][i] + (float(yaw_extra[i]) if yaw_extra is not None else 0.0)
                vdir = cam.direction(yaw, P['pitch'][i]); yield self.V.render(fr, Ms[i].T @ vdir if P['ref'] == 'body' else vdir, ez, float(P['roll'][i]))
        finally:
            dec.stdout.close(); dec.terminate(); dec.wait()


def encoder_args():
    """Hardware H.264 where there is one (cheap on the CPU, which the rest of the processing needs), else x264."""
    from strata360 import hw
    return hw.live_h264_args()


def card(w, h, text):
    im = np.full((h, w, 3), 24, np.uint8); cv2.putText(im, text, (24, h // 2), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (200, 200, 200), 1, cv2.LINE_AA); return im


def proxy_of(folder, clip):
    p = os.path.join(config.race_dir(folder), 'clips', clip, 'proxy.mp4'); return p if os.path.exists(p) and os.path.exists(os.path.splitext(p)[0] + '.json') else None


def has_audio(p):
    r = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'a', '-show_entries', 'stream=index', '-of', 'csv=p=0', p], capture_output=True, text=True); return bool(r.stdout.strip())


def window_gain(folder, g):
    """Linear gain for a window's own sound: you speaking is full volume; otherwise what the sound classifier found decides (analysis/sound_events.window_mix); without it the old rule (1.0 speech, 0.25 else)."""
    from strata360.analysis import sound_events as SE
    try: doc = json.load(open(os.path.join(config.race_dir(folder), 'clips', g['clip'], 'audio_events.json')))
    except (OSError, ValueError): return 1.0 if g.get('speech') else 0.25
    return 10 ** (SE.window_mix(doc, g['clip_start_s'], g['clip_start_s'] + g['dur_s'], bool(g.get('speech')))['gain_db'] / 20.0)


def audio_of(folder, clip):
    """The sound to use for a clip in the film: the cleaned audio, else the original, else the proxy's own sound; None if there is none."""
    d = os.path.join(config.race_dir(folder), 'clips', clip)
    for n in ('audio_clean.flac', 'audio_original.flac'):
        if os.path.exists(os.path.join(d, n)): return os.path.join(d, n)
    p = proxy_of(folder, clip); return p if p and has_audio(p) else None


def build_audio(folder, plan, out, total_s):
    """The film's sound: each window's own audio (0.25 gain, 1.0 where people speak) in order, mixed with the voice-over track."""
    inputs = []; chains = []; n = 0
    for g in plan['segments']:
        p = audio_of(folder, g['clip']); d = g['dur_s']; gain = window_gain(folder, g)
        if p: inputs += ['-ss', f"{g['clip_start_s']:.3f}", '-t', f'{d:.3f}', '-i', p]; chains.append(f"[{n}:a]aresample=48000,aformat=channel_layouts=mono,volume={gain},apad=whole_dur={d:.3f},atrim=0:{d:.3f},afade=t=in:d=0.01,afade=t=out:st={max(d - 0.01, 0):.3f}:d=0.01[s{n}]")
        else: inputs += ['-f', 'lavfi', '-t', f'{d:.3f}', '-i', 'anullsrc=r=48000:cl=mono']; chains.append(f'[{n}:a]anull[s{n}]')
        n += 1
    vo = os.path.join(config.race_dir(folder), 'voiceover', 'voiceover.wav'); chain = ';'.join(chains) + ';' + ''.join(f'[s{i}]' for i in range(n)) + f'concat=n={n}:v=0:a=1[nat]'
    mus = (plan.get('film') or {}).get('music'); mp = os.path.join(config.race_dir(folder), mus['file']) if mus else None; has_mu = bool(mp and os.path.exists(mp)); has_vo = os.path.exists(vo); k = n
    tail = f'apad=whole_dur={total_s:.3f},atrim=0:{total_s:.3f},alimiter=limit=0.95[m]'
    if has_vo: inputs += ['-i', vo]; chain += f";[{k}:a]aresample=48000,aformat=channel_layouts=mono,{'asplit=2[vo][vokey]' if has_mu else 'anull[vo]'}"; k += 1
    if has_mu:                                                                                        # the music from its first downbeat, ducked under the voice-over, fading out at the end
        inputs += ['-ss', f"{mus['offset_s']:.3f}", '-t', f'{total_s:.3f}', '-i', mp]
        chain += f';[{k}:a]aresample=48000,aformat=channel_layouts=mono,volume=0.5,afade=t=out:st={max(total_s - 2.5, 0):.3f}:d=2.5[mu]'
        chain += (';[mu][vokey]sidechaincompress=threshold=0.02:ratio=6:attack=30:release=500[mud]' if has_vo else ';[mu]anull[mud]')
    mix = ['[nat]'] + (['[vo]'] if has_vo else []) + (['[mud]'] if has_mu else [])
    chain += f";{''.join(mix)}amix=inputs={len(mix)}:normalize=0:duration=longest,{tail}"
    r = subprocess.run(['ffmpeg', '-y', '-v', 'error', *inputs, '-filter_complex', chain, '-map', '[m]', '-ar', '48000', '-ac', '1', out], capture_output=True, text=True)
    if r.returncode: raise RuntimeError('audio: ' + r.stderr[-300:])


def render(folder, plan, framing, px=960, decode_w=3072, progress=None):
    """Render the film into film_dir (see the module docstring). Blocks until done; progress(frames_done, frames_total) is called about once a second."""
    from strata360.analysis import views
    key = plan_key(folder, plan); d = film_dir(folder, key); os.makedirs(d, exist_ok=True); w = px; h = px * 9 // 16 // 2 * 2
    segs = plan['segments']; bounds = [int(round((g['film_start_s'] + g['dur_s']) * FPS)) for g in segs]; starts = [0] + bounds[:-1]; total = bounds[-1]; total_s = total / FPS
    placeholders = sorted({g['clip'] for g in segs if not proxy_of(folder, g['clip'])}); status = lambda state, n, **kw: json.dump(dict(state=state, pid=os.getpid(), key=key, frames_done=n, frames_total=total, placeholders=placeholders, started=t0, **kw), open(os.path.join(d, 'status.json.tmp'), 'w')) or os.replace(os.path.join(d, 'status.json.tmp'), os.path.join(d, 'status.json'))
    t0 = time.time(); status('audio', 0); build_audio(folder, plan, os.path.join(d, 'audio.wav'), total_s)
    enc = guard.popen(['ffmpeg', '-y', '-v', 'error', '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-s', f'{w}x{h}', '-r', str(FPS), '-i', '-', '-i', os.path.join(d, 'audio.wav'), '-map', '0:v', '-map', '1:a', *encoder_args(),
                            '-pix_fmt', 'yuv420p', '-g', str(int(FPS * 2)), '-force_key_frames', 'expr:gte(t,n_forced*2)', '-c:a', 'aac', '-b:a', '128k', '-shortest', '-f', 'hls', '-hls_time', '2', '-hls_list_size', '0', '-hls_playlist_type', 'event', '-hls_flags', 'independent_segments',
                            '-hls_segment_filename', os.path.join(d, 'seg%05d.ts'), os.path.join(d, 'index.m3u8')], stdin=subprocess.PIPE)
    src = PreviewSource(folder, segs, framing, w, h, decode_w); last = [0.0]
    def emit(img):
        enc.stdin.write(img.tobytes()); src.done += 1
        if time.time() - last[0] > 1.0: last[0] = time.time(); status('rendering', src.done); progress and progress(src.done, total)
    done = 0
    try:
        done = compose(segs, src, FPS, emit); enc.stdin.close(); enc.wait(); status('done', total, finished=time.time())
    except BaseException as e:
        try: enc.kill()
        except OSError: pass
        status('error', src.done, error=f'{type(e).__name__}: {e}'); raise
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
