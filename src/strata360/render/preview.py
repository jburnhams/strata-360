"""A rough preview of the whole film, streamed as it is rendered: the planned windows cut from the clips' proxy videos, framed by their camera paths (edit/framing.py), hard cuts, with the race overlay (the same as the final film's, `overlay/`) and the clips' own
sound (low, full where someone is talking) under the voice-over track. Written as an HLS "event" playlist, so a browser can start playing after the first two seconds and keeps buffering while the
rest is made.

  <project>/preview/film-<key>/index.m3u8, seg00000.ts ...   the stream (the key identifies plan + voice-over, a changed plan starts a new directory)
  <project>/preview/film-<key>/status.json                    {state, frames_done, frames_total, placeholders: [clip ids without a proxy yet], started, finished}
  <project>/preview/film-<key>/audio.wav                      the mixed sound

The picture is made by the real renderer's own code (render/flat.py: projection, view rays, the globe with its backgrounds; render/camera.py: the path evaluation, including heading-follow and body
references from the stabilisation), with the clip's proxy (upright equirect) as the picture source instead of the two lenses: what differs from the final render is only the resolution. A clip without
a proxy yet is a dark card with its name."""
from strata360.pipeline import guard
import hashlib, json, math, os, shutil, subprocess, sys, time
import cv2, numpy as np
from strata360.pipeline import config
from strata360.render import camera as cam, grade as GR, synthetic as SYN
from strata360.render.flat import Globe, projection, view_rays
from strata360.render.film import compose, layout

FPS = 25.0


def film_dir(folder, key): return os.path.join(config.race_dir(folder), 'preview', f'film-{key}')


def plan_key(folder, plan):
    vo = os.path.join(config.race_dir(folder), 'voiceover', 'voiceover.wav')
    h = hashlib.sha1(json.dumps(plan['segments'], sort_keys=True, default=str).encode()); h.update(str(os.path.getmtime(vo) if os.path.exists(vo) else 0).encode())
    h.update(''.join(str(os.path.getmtime(g['synthetic'])) for g in plan['segments'] if g.get('synthetic') and os.path.exists(g['synthetic'])).encode()); h.update(b'grade1' if GR.on(folder) else b'')
    try:
        from strata360 import overlay
        h.update(overlay.inputs_signature(folder).encode())                                      # the overlay is on every frame: new cut-offs or checkpoints make the preview out of date
    except Exception: pass
    return h.hexdigest()[:10]


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
    def __init__(self, folder, segs, framing, w, h, decode_w, overlay=None, gains=None):
        self.folder, self.segs, self.framing, self.w, self.h, self.decode_w, self.overlay, self.gains = folder, segs, framing, w, h, decode_w, overlay, gains or {}; self.V = EquirectView(w, h); self.info = {}; self.done = 0

    def _clip(self, clip):
        if clip not in self.info:
            p = proxy_of(self.folder, clip); side = json.load(open(os.path.splitext(p)[0] + '.json')) if p else None
            self.info[clip] = dict(proxy=p, side=side, ts=np.array([f['t_s'] for f in side['frames']]) if side else None, stab=None)
        return self.info[clip]

    def frames(self, k, a0, a1, yaw_extra=None, pose_extra=None):
        """The frames a0..a1 of window k as BGR; with an overlay the film's race overlay (clock, numbers, maps, as in the final film) is drawn on each at the race time it shows, before any blend between shots."""
        it = self._frames(k, a0, a1, yaw_extra, pose_extra)
        if self.overlay is None: yield from it; return
        import datetime as dt
        sg = self.segs[k]; utc0 = None if sg.get('synthetic') else dt.datetime.fromisoformat(sg['utc_start'].replace('Z', '+00:00')).timestamp()
        for i, img in enumerate(it):
            t = SYN.race_time(sg, a0 + i, FPS) if utc0 is None else utc0 + (a0 + i) / FPS
            yield np.ascontiguousarray(self.overlay.apply(np.ascontiguousarray(img[..., ::-1]), t)[..., ::-1])                 # (the overlay draws RGB)

    def _frames(self, k, a0, a1, yaw_extra=None, pose_extra=None):
        sg = self.segs[k]; m = a1 - a0
        if m <= 0: return
        if sg.get('synthetic'): yield from SYN.frames(sg['synthetic'], sg['clip_start_s'], a0, a1, FPS, self.w, self.h, 'bgr'); return           # a generated clip: its pictures as they are
        clip = sg['clip']; ci = self._clip(clip); gain = self.gains.get(sg['id'])
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
                self.V.set_fov(P['fov'][i] + (float(pose_extra[i][2]) if pose_extra is not None else 0.0), P['dist'][i], (float(pose_extra[i][3]) if pose_extra is not None and len(pose_extra[i]) > 3 and pose_extra[i][3] > 0 else (P['disc'][i] if P['use_disc'] else None))); yaw = P['yaw'][i] + (float(yaw_extra[i]) if yaw_extra is not None else 0.0) + (math.radians(float(pose_extra[i][0])) if pose_extra is not None else 0.0)
                vdir = cam.direction(yaw, P['pitch'][i] + (math.radians(float(pose_extra[i][1])) if pose_extra is not None else 0.0)); img = self.V.render(fr, Ms[i].T @ vdir if P['ref'] == 'body' else vdir, ez, float(P['roll'][i]))
                yield img if gain is None else GR.apply(img, gain(max((a0 + i) / FPS, 0.0)))                          # the exposure match (render/grade.py), the same maths as the final film
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


from strata360.audio.mix import (MUTE_PAD_S, audio_of, build_audio, has_audio, mute_filter, never_spans, role_has_speech, window_gain)      # the film's sound lives in audio/mix.py; these names stay here for the callers that used them from the preview


def render(folder, plan, framing, px=960, decode_w=3072, progress=None):
    """Render the film into film_dir (see the module docstring). Blocks until done; progress(frames_done, frames_total) is called about once a second."""
    from strata360.analysis import views
    from strata360.edit import pans as PN
    key = plan_key(folder, plan)                                                                                 # of the plan as saved (the server looks the film up by it); the glides below follow from the plan, so they need no part in it
    plan = dict(plan, segments=PN.apply_pans(plan['segments'], framing, scorer=PN.looker(folder))[0])                                   # a hard cut inside one clip becomes a glide where that is gentle and keeps people in shot (edit/pans.py)
    d = film_dir(folder, key); os.makedirs(d, exist_ok=True); w = px; h = px * 9 // 16 // 2 * 2
    segs = plan['segments']; bounds = [int(round((g['film_start_s'] + g['dur_s']) * FPS)) for g in segs]; starts = [0] + bounds[:-1]; total = bounds[-1]; total_s = total / FPS
    placeholders = sorted({g['clip'] for g in segs if not g.get('synthetic') and not proxy_of(folder, g['clip'])}); status = lambda state, n, **kw: json.dump(dict(state=state, pid=os.getpid(), key=key, frames_done=n, frames_total=total, placeholders=placeholders, started=t0, **kw), open(os.path.join(d, 'status.json.tmp'), 'w')) or os.replace(os.path.join(d, 'status.json.tmp'), os.path.join(d, 'status.json'))
    t0 = time.time(); status('audio', 0); build_audio(folder, plan, os.path.join(d, 'audio.wav'), total_s)
    enc = guard.popen(['ffmpeg', '-y', '-v', 'error', '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-s', f'{w}x{h}', '-r', str(FPS), '-i', '-', '-i', os.path.join(d, 'audio.wav'), '-map', '0:v', '-map', '1:a', *encoder_args(),
                            '-pix_fmt', 'yuv420p', '-g', str(int(FPS * 2)), '-force_key_frames', 'expr:gte(t,n_forced*2)', '-c:a', 'aac', '-b:a', '128k', '-shortest', '-f', 'hls', '-hls_time', '2', '-hls_list_size', '0', '-hls_playlist_type', 'event', '-hls_flags', 'independent_segments',
                            '-hls_segment_filename', os.path.join(d, 'seg%05d.ts'), os.path.join(d, 'index.m3u8')], stdin=subprocess.PIPE)
    from strata360.overlay import for_project
    src = PreviewSource(folder, segs, framing, w, h, decode_w, overlay=for_project(folder, (w, h)), gains=GR.gains_for(folder, segs, framing)); last = [0.0]
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
    from strata360 import oslib; oslib.lower_priority(10)                                                                          # started by the user and waited for: a little above the background processing, well below the desktop
    edit = PJ.load(a.folder); plan = edit.get('plan')
    if not plan: sys.exit('no plan yet')
    fr = {k: v for k, v in FR.resolve(a.folder, plan, head=True).items()}
    key = plan_key(a.folder, plan); root = os.path.dirname(film_dir(a.folder, key))
    for n in os.listdir(root) if os.path.isdir(root) else []:                                   # only the newest build is kept
        if n.startswith('film-') and n != f'film-{key}': shutil.rmtree(os.path.join(root, n), ignore_errors=True)
    d = film_dir(a.folder, key)
    if not a.force and os.path.exists(os.path.join(d, 'status.json')) and json.load(open(os.path.join(d, 'status.json'))).get('state') == 'done': print('already rendered', d); return
    shutil.rmtree(d, ignore_errors=True); print(render(a.folder, plan, fr, px=a.px, progress=lambda i, n: print(f'\r{i}/{n}', end='', flush=True)))


if __name__ == '__main__': main()
