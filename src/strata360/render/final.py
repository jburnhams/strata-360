"""The final film: the plan rendered from the original dual-lens video at full quality, with the voice-over track.

Same planned windows, camera paths (edit/framing.py) and transitions (render/film.py) as the preview, but every frame goes through the real renderer (render/flat.py: the two lenses, stitched and
stabilised, one resample per output pixel). The film is rendered in independent pieces (a plain stretch of one window, or a transition region), each into its own file; a finished piece is kept, so a
stopped or crashed render continues where it left off. The pieces are joined without re-encoding and the sound (the clips' own sound under the voice-over track) is added.

  <project>/final/<key>/piece-pNNNN.mov   one piece each (.done marker when complete)      <key> identifies the plan and the settings
  <project>/final/<key>/status.json        {state, frames_done, frames_total, pieces_done, pieces_total, ...}
  <project>/final/<key>/film.mp4           the result

Cost: 4K at 50 frames a second takes of the order of a second per frame on this kind of Mac; the preview (render/preview.py) is for judging the cut, this for delivering it."""
from strata360.pipeline import guard
import datetime as dt, hashlib, json, os, shutil, subprocess, sys, time
import numpy as np
from strata360.pipeline import config
from strata360.render import camera as cam, flat, synthetic as SYN
from strata360.render.film import pieces, render_piece, layout
from strata360.render.preview import build_audio, proxy_of


def final_dir(folder, key): return os.path.join(config.race_dir(folder), 'final', key)


def final_key(plan, size, fps, bitrate, folder):
    vo = os.path.join(config.race_dir(folder), 'voiceover', 'voiceover.wav')
    h = hashlib.sha1(json.dumps([plan['segments'], size, fps, bitrate], sort_keys=True, default=str).encode()); h.update(str(os.path.getmtime(vo) if os.path.exists(vo) else 0).encode())
    h.update(_overlay_sig(folder).encode()); h.update(''.join(str(os.path.getmtime(g['synthetic'])) for g in plan['segments'] if g.get('synthetic') and os.path.exists(g['synthetic'])).encode()); return h.hexdigest()[:10]


def _overlay_sig(folder):
    """The overlay's part of the key (empty when it is off or there is no track, so films made before the overlay keep their key)."""
    from strata360.overlay.layout import signature
    try: cfg = config.load(folder)
    except FileNotFoundError: return ''
    st = cfg.get('overlay') or {}; track = config.track_path(folder, cfg)
    return signature(st, track) if st.get('enabled', True) and track else ''


class FinalSource:
    """Frames of the planned windows from the original OSV files (uint16 RGB code values, like flat.main)."""
    def __init__(self, folder, segs, framing, W, H, fps, interp='cubic', overlay=None):
        self.folder, self.segs, self.framing, self.W, self.H, self.fps, self.interp, self.overlay = folder, segs, framing, W, H, fps, interp, overlay; self.info = {}; self.done = 0

    def _clip(self, clip):
        if clip not in self.info:
            from strata360.osv.telemetry import read_frames
            cj = json.load(open(os.path.join(config.race_dir(self.folder), 'clips', clip, 'clip.json'))); osv = cj['source_files']['osv']
            self.info[clip] = dict(osv=osv, src_fps=float(cj['video']['nominal_fps']), n=int(cj['video']['source_frames']), R=flat.Renderer(osv, self.W, self.H, 90.0, self.interp), T=read_frames(osv))
        return self.info[clip]

    def frames(self, k, a0, a1, yaw_extra=None):
        sg = self.segs[k]
        if sg.get('synthetic'): yield from SYN.frames(sg['synthetic'], sg['clip_start_s'], a0, a1, self.fps, self.W, self.H, 'rgb', np.uint16); return           # a generated clip: no lens, no overlay (it has its own)
        ci = self._clip(sg['clip']); R = ci['R']; R.carve_seam = True; R.parallax = True; R.seam = None; R.warp = None; m = a1 - a0                                    # a new stretch of the clip: the seam starts afresh
        if m <= 0: return
        path = cam.CameraPath.from_dict(self.framing[sg['id']]); R.set_background(path.bg, **path.bg_opts); times = np.arange(a0, a1) / self.fps; t_abs = np.maximum(sg['clip_start_s'] + times, 0.0)
        ks = np.clip(np.round(t_abs * ci['src_fps']).astype(int), 0, ci['n'] - 1); quat = ci['T']['quat']; Ms = [R.stab_matrix(quat[min(int(j), len(quat) - 1)]) for j in ks]
        utc0 = dt.datetime.fromisoformat(sg['utc_start'].replace('Z', '+00:00')).timestamp() if self.overlay is not None else 0.0            # the window's first frame on the race clock
        P = path.evaluate(times, Ms, self.fps); first = int(ks[0]); ss = max(first / ci['src_fps'] - 0.002, 0.0)
        dm, ds = flat.decoder(ci['osv'], 1, ss=ss), flat.decoder(ci['osv'], 0, ss=ss); k_dec = first - 1; last_seam = None; cur_m = cur_s = None; ez = np.array([0.0, 0.0, 1.0])
        try:
            for i in range(m):
                while k_dec < ks[i]:
                    a, b = flat.read_frame(dm), flat.read_frame(ds)
                    if a is None or b is None: break                                              # past the end of the clip: the last frame is held
                    cur_m, cur_s = a, b; k_dec += 1
                if cur_m is None: raise RuntimeError(f"could not read {ci['osv']} at {t_abs[i]:.2f} s")
                if k_dec != last_seam: R.update_seam(cur_m, cur_s); last_seam = k_dec                             # one seam per source frame
                R.set_fov(P['fov'][i], P['dist'][i], P['disc'][i] if P['use_disc'] else None)
                yaw = P['yaw'][i] + (float(yaw_extra[i]) if yaw_extra is not None else 0.0); d = cam.direction(yaw, P['pitch'][i]); M = Ms[i]
                img = R.render(cur_m, cur_s, d if P['ref'] == 'body' else M @ d, M @ ez, float(P['roll'][i]))
                yield img if self.overlay is None else self.overlay.apply(img, utc0 + times[i])           # before any transition blend, so a dissolve cross-fades the two overlays too
        finally:
            for p in (dm, ds):
                p.kill(); p.wait()


def encoder_args(bitrate):
    from strata360 import hw
    if hw._hardware('hevc'): return hw.hevc_args(bitrate, main10=True)
    return ['-c:v', 'libx265', '-crf', '17', '-preset', 'medium', '-tag:v', 'hvc1', '-pix_fmt', 'yuv420p10le']


def encode_piece(path, W, H, fps, bitrate, run):
    """run(emit) renders the piece's frames into emit; they are encoded to `path` (kept only when complete)."""
    cmd = ['ffmpeg', '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgb48le', '-s', f'{W}x{H}', '-r', str(fps), '-i', '-', '-vf', 'scale=in_range=full:out_range=tv:out_color_matrix=bt709:flags=accurate_rnd+full_chroma_int',
           *encoder_args(bitrate), '-colorspace', 'bt709', '-color_primaries', 'bt709', '-color_trc', 'bt709', '-color_range', 'tv', path + '.part.mov']
    enc = guard.popen(cmd, stdin=subprocess.PIPE)
    try:
        run(lambda img: enc.stdin.write(np.ascontiguousarray(img).tobytes())); enc.stdin.close(); enc.wait()
        if enc.returncode: raise RuntimeError('the encoder failed')
    except BaseException:
        try: enc.kill()
        except OSError: pass
        raise
    os.replace(path + '.part.mov', path); open(path + '.done', 'w').close()


def render_final(*a, **k):
    with guard.heavy('final render', 4.0): return _render_final(*a, **k)


def _render_final(folder, plan, framing, size=(3840, 2160), fps=50.0, bitrate='100M', limit_pieces=None, out=None, progress=None):
    """Render (or continue) the final film; returns the path of the film. `limit_pieces` renders only the first pieces and does not assemble (for trying things out)."""
    key = final_key(plan, list(size), fps, bitrate, folder); d = final_dir(folder, key); os.makedirs(d, exist_ok=True); segs = plan['segments']; ps = pieces(segs, fps); W, H = size
    total = sum(p['frames'] for p in ps); t0 = time.time(); done_frames = 0
    def status(state, **kw): json.dump(dict(state=state, pid=os.getpid(), key=key, frames_done=done_frames, frames_total=total, pieces_done=sum(os.path.exists(os.path.join(d, p['id'] + '.mov.done')) for p in ps), pieces_total=len(ps), started=t0, **kw), open(os.path.join(d, 'status.json.tmp'), 'w')); os.replace(os.path.join(d, 'status.json.tmp'), os.path.join(d, 'status.json'))
    from strata360.overlay import for_project
    src = FinalSource(folder, segs, framing, W, H, fps, overlay=for_project(folder, (W, H))); status('rendering')
    for n, p in enumerate(ps):
        if limit_pieces is not None and n >= limit_pieces: break
        f = os.path.join(d, p['id'] + '.mov')
        if os.path.exists(f + '.done'): done_frames += p['frames']; continue
        encode_piece(f, W, H, fps, bitrate, lambda emit, p=p: render_piece(p, segs, src, emit)); done_frames += p['frames']; status('rendering'); progress and progress(done_frames, total)
    if limit_pieces is not None: status('partial'); return d
    status('assembling'); audio = os.path.join(d, 'audio.wav'); build_audio(folder, plan, audio, total / fps)
    lst = os.path.join(d, 'pieces.txt'); open(lst, 'w').write(''.join(f"file '{os.path.join(d, p['id'] + '.mov')}'\n" for p in ps)); film = out or os.path.join(d, 'film.mp4')
    r = subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'concat', '-safe', '0', '-i', lst, '-i', audio, '-map', '0:v', '-map', '1:a', '-c:v', 'copy', '-c:a', 'aac', '-b:a', '256k', '-shortest', '-movflags', '+faststart', film], capture_output=True, text=True)
    if r.returncode: status('error', error=r.stderr[-300:]); raise RuntimeError(r.stderr[-300:])
    status('done', finished=time.time(), film=film); return film


def main():
    import argparse
    from strata360.edit import framing as FR, project as PJ
    ap = argparse.ArgumentParser(); ap.add_argument('folder'); ap.add_argument('--size', default='3840x2160'); ap.add_argument('--fps', type=float, default=50.0); ap.add_argument('--bitrate', default='100M')
    ap.add_argument('--pieces', type=int, help='render only the first N pieces (a trial; nothing is assembled)'); ap.add_argument('--out'); a = ap.parse_args()
    from strata360 import oslib; oslib.lower_priority(19)
    plan = PJ.load(a.folder).get('plan')
    if not plan: sys.exit('no plan yet')
    W, H = map(int, a.size.split('x')); fr = FR.resolve(a.folder, plan)
    print(render_final(a.folder, plan, fr, (W, H), a.fps, a.bitrate, a.pieces, a.out, progress=lambda i, n: print(f'\r{i}/{n} frames', end='', flush=True)))


if __name__ == '__main__': main()
