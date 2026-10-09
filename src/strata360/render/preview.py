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
from strata360.render import camera as cam, final as FN, grade as GR, synthetic as SYN
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


class PreviewSource(FN.FinalSource):
    """The preview's (and the point camera clips') frames: the film's OWN renderer (render/final.py `FinalSource`: windows, camera paths, exposure match, race overlay, generated clips, point cameras) with preview parameters, as 8-bit BGR. `source` 'proxy' takes the footage from the clips' proxy videos (upright equirect, quick, rough: a clip without a proxy gives a dark card), 'osv' from the original recordings like the final film. Generated clips are taken as already made (the film's, else the planner's)."""
    def __init__(self, folder, segs, framing, w, h, decode_w, overlay=None, gains=None, fps=FPS, source='proxy'):
        super().__init__(folder, segs, framing, w, h, fps, interp='linear', overlay=overlay, gains=gains, source=source, decode_w=decode_w); self.cached_only = True; self.done = 0

    def frames(self, k, a0, a1, yaw_extra=None, pose_extra=None):
        for img in super().frames(k, a0, a1, yaw_extra, pose_extra): yield to_bgr8(img)


def encoder_args():
    """Hardware H.264 where there is one (cheap on the CPU, which the rest of the processing needs), else x264."""
    from strata360 import hw
    return hw.live_h264_args()


def card(w, h, text):
    im = np.full((h, w, 3), 24, np.uint8); cv2.putText(im, text, (24, h // 2), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (200, 200, 200), 1, cv2.LINE_AA); return im


proxy_of = FN.proxy_of


from strata360.audio.mix import (MUTE_PAD_S, audio_of, build_audio, has_audio, mute_filter, never_spans, role_has_speech, window_gain)      # the film's sound lives in audio/mix.py; these names stay here for the callers that used them from the preview


def to_bgr8(img):
    """The final renderer's RGB picture (uint16 code values) as the 8-bit BGR the HLS encoder takes."""
    a = np.asarray(img)
    if a.dtype != np.uint8: a = np.clip((a.astype(np.uint32) + 128) >> 8, 0, 255).astype(np.uint8)
    return np.ascontiguousarray(a[..., ::-1])


def render(folder, plan, framing, px=960, decode_w=3072, progress=None, source='proxy'):
    """Render the film into film_dir (see the module docstring). Blocks until done; progress(frames_done, frames_total) is called about once a second. The film is made by the final renderer's own code (render/final.py) at the preview's size and half the footage's frame rate; `source` 'proxy' takes the footage from the clips' proxy videos (quick), 'osv' from the original recordings."""
    fps = FN.resolve_fps(folder, plan, 0.0, half_rate=True)
    if source == 'osv':
        with guard.heavy('film preview', 3.0): return _render(folder, plan, framing, px, decode_w, progress, source, fps)
    return _render(folder, plan, framing, px, decode_w, progress, source, fps)


def _render(folder, plan, framing, px, decode_w, progress, source, FPS):
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
    gains = GR.gains_for(folder, segs, framing); last = [0.0]
    src = PreviewSource(folder, segs, framing, w, h, decode_w, overlay=for_project(folder, (w, h)), gains=gains, fps=FPS, source=source)
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
    ap = argparse.ArgumentParser(); ap.add_argument('folder'); ap.add_argument('--px', type=int, default=960); ap.add_argument('--force', action='store_true', help='render again even if this plan was already rendered'); ap.add_argument('--source', choices=('proxy', 'osv'), default='proxy', help="where the footage comes from: the clips' proxy videos (default, quick) or the original recordings (the final film's source); the rest of the pipeline is the final film's"); a = ap.parse_args()
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
    shutil.rmtree(d, ignore_errors=True); print(render(a.folder, plan, fr, px=a.px, source=a.source, progress=lambda i, n: print(f'\r{i}/{n}', end='', flush=True)))


if __name__ == '__main__': main()
