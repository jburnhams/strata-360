"""The final film: the plan rendered from the original dual-lens video at full quality, with the voice-over track.

Same planned windows, camera paths (edit/framing.py) and transitions (render/film.py) as the preview, but every frame goes through the real renderer (render/flat.py: the two lenses, stitched and
stabilised, one resample per output pixel). The film is rendered in independent pieces (a plain stretch of one window, or a transition region), each into its own file; a finished piece is kept, so a
stopped or crashed render continues where it left off. The pieces are joined without re-encoding and the sound (the clips' own sound under the voice-over track) is added.

  <project>/final/<key>/piece-pNNNN.mov   one piece each (.done marker when complete)      <key> identifies the plan and the settings
  <project>/final/<key>/status.json        {state, frames_done, frames_total, pieces_done, pieces_total, ...}
  <project>/final/<key>/film.mp4           the result

Cost: 4K at 50 frames a second takes of the order of a second per frame on this kind of Mac; the preview (render/preview.py) is for judging the cut, this for delivering it."""
from strata360.pipeline import guard
import datetime as dt, hashlib, json, math, os, shutil, subprocess, sys, time
import cv2
import numpy as np
from strata360.pipeline import config
from strata360.render import camera as cam, flat, gpu as GPU, grade as GR, seam as SM, synthetic as SYN
from strata360.render.film import pieces, render_piece, layout
from strata360.audio.mix import build_audio
from strata360.render.progress import Null
from strata360.edit import upscale as UP, hyperlapse as HL


LOUDNESS_LUFS = -14.0       # the delivered film's integrated loudness (a streaming-platform level); race.json `audio.loudness_lufs` changes it


def loudness_target(folder):
    try: return float((config.load(folder).get('audio') or {}).get('loudness_lufs', LOUDNESS_LUFS))
    except (FileNotFoundError, ValueError, TypeError): return LOUDNESS_LUFS


def proxy_of(folder, clip):
    """The clip's proxy video (upright equirect, the preview's source) when it and its side file are made, else None."""
    p = os.path.join(config.race_dir(folder), 'clips', clip, 'proxy.mp4'); return p if os.path.exists(p) and os.path.exists(os.path.splitext(p)[0] + '.json') else None


def clip_rates(folder, plan):
    """{clip id: source frame rate} of the footage clips the plan plays (`video.nominal_fps` of clip.json)."""
    rd = config.race_dir(folder); out = {}
    for g in plan['segments']:
        c = g.get('clip')
        if g.get('synthetic') or not c or c in out: continue
        try: out[c] = float(json.load(open(os.path.join(rd, 'clips', c, 'clip.json')))['video']['nominal_fps'])
        except (OSError, ValueError, KeyError): pass
    return out


def source_fps(folder, plan, default=50.0):
    """The film's frame rate: the rate most of the plan's footage was shot at (by seconds played); the others are resampled by nearest source frame (the renderer finds each frame by its time). `default` when the plan has no footage."""
    rates = clip_rates(folder, plan); secs = {}
    for g in plan['segments']:
        r = rates.get(g.get('clip'))
        if r: secs[r] = secs.get(r, 0.0) + float(g.get('dur_s') or 0.0)
    return max(secs, key=secs.get) if secs else float(default)


def resolve_fps(folder, plan, fps=0.0, half_rate=False):
    """The rate to render at: `fps` when given, else the source's; half of it with `half_rate` (every other source frame: faster, and the preview, overlay, time map and sound all follow the same rate)."""
    base = float(fps) if fps else source_fps(folder, plan)
    return base / 2.0 if half_rate else base


def ffmpeg_rate(fps):
    """`fps` as ffmpeg wants it: an integer or a rational (29.97 is 30000/1001), never a rounded decimal."""
    from fractions import Fraction
    for base in (24, 30, 48, 60, 120):                                                                    # the NTSC rates are n x 1000/1001 (29.97 is 30000/1001), however many digits were stored
        if abs(float(fps) - base * 1000 / 1001) < 0.005: return f'{base * 1000}/1001'
    f = Fraction(float(fps)).limit_denominator(1001); return str(f.numerator) if f.denominator == 1 else f'{f.numerator}/{f.denominator}'


def final_dir(folder, key): return os.path.join(config.race_dir(folder), 'final', key)


def final_key(plan, size, fps, bitrate, folder, upscale='off', min_zoom=None):
    vo = os.path.join(config.race_dir(folder), 'voiceover', 'voiceover.wav')
    h = hashlib.sha1(json.dumps([plan['segments'], size, fps, bitrate], sort_keys=True, default=str).encode()); h.update(str(os.path.getmtime(vo) if os.path.exists(vo) else 0).encode())
    h.update(_overlay_sig(folder).encode()); h.update(_text_sig(folder).encode()); h.update(b'grade1' if GR.on(folder) else b''); h.update(f'upscale:{UP.MODEL}:{UP.target_width(upscale, size[0])}:z{UP.MIN_ZOOM if min_zoom is None else min_zoom}:s{UP.MIN_SECONDS}'.encode() if UP.target_width(upscale, size[0]) else b''); h.update(''.join(str(os.path.getmtime(g['synthetic'])) for g in plan['segments'] if g.get('synthetic') and os.path.exists(g['synthetic'])).encode()); return h.hexdigest()[:10]


def _text_sig(folder):
    """The part of the key for the text drawn on the pieces: the word-art cards (film_text.json) and whether the subtitles are on (empty when there are none, so earlier keys hold)."""
    p = os.path.join(config.race_dir(folder), 'film_text.json'); sig = f'cards:{os.path.getmtime(p):.0f}' if os.path.exists(p) else ''
    return sig + ('nosubs' if os.environ.get('STRATA_SUBTITLES') == '0' else 'subs')


def _overlay_sig(folder):
    """The overlay's part of the key (empty when it is off or there is no track, so films made before the overlay keep their key)."""
    from strata360.overlay.layout import signature
    try: cfg = config.load(folder)
    except FileNotFoundError: return ''
    st = cfg.get('overlay') or {}; track = config.track_path(folder, cfg)
    return signature(st, track) if st.get('enabled', True) and track else ''


class FinalSource:
    """Frames of the planned windows from the original OSV files (uint16 RGB code values, like flat.main)."""
    def __init__(self, folder, segs, framing, W, H, fps, interp='cubic', overlay=None, gains=None, upscale='off', progress=None, source='osv', decode_w=3072, up_min_zoom=None):
        self.folder, self.segs, self.framing, self.W, self.H, self.fps, self.interp, self.overlay, self.gains = folder, segs, framing, W, H, fps, interp, overlay, gains or {}; self.info = {}; self.done = 0
        self.upscale = UP.normalize(upscale); self.up_w = UP.target_width(self.upscale, W); self.pg, self._factors, self.why = progress or Null(), {}, {}; self.last_only = False; self.up_min_zoom = UP.MIN_ZOOM if up_min_zoom is None else float(up_min_zoom); self.up_min_s = UP.MIN_SECONDS; self.film_synthetic = True; self.cached_only = False; self.source, self.decode_w, self._pinfo, self._eq = source, decode_w, {}, None; self._synth = {}; self._pc = {}; self._ramps = {}        # last_only: only the last frame of a stretch is wanted (a still): the ones before it only settle the seam, so they are not enlarged, graded or given the overlay      # gains: render/grade.py, the exposure match of each footage window

    def _boxes(self, clip, osv):
        """t -> [(yaw, pitch, height_deg)] of the people seen near t (edit/clip_views.py), for a seam that goes round them; None when off (`STRATA_SEAM_PEOPLE=0`) or the clip has no people records."""
        if os.environ.get('STRATA_SEAM_PEOPLE') == '0': return None
        from strata360.edit import clip_views as CV
        return CV.load(os.path.join(config.race_dir(self.folder), 'clips', clip), osv)['boxes']

    def _clip(self, clip):
        if clip not in self.info:
            from strata360.osv.telemetry import read_frames, video_pts
            cj = json.load(open(os.path.join(config.race_dir(self.folder), 'clips', clip, 'clip.json'))); osv = config.source(cj['source_files']['osv'], os.path.join(config.race_dir(self.folder), 'clips', clip))
            R = flat.Renderer(osv, self.W, self.H, 90.0, self.interp); self.info[clip] = dict(boxes=self._boxes(clip, osv), osv=osv, src_fps=float(cj['video']['nominal_fps']), n=int(cj['video']['source_frames']), R=R, Rs={(self.W, self.H): R}, T=read_frames(osv), pts=np.asarray(video_pts(osv, 0), float))
        return self.info[clip]

    def shot_factor(self, sg):
        """How many times the shot's pictures are enlarged by the local model (edit/upscale.py): ONE answer for the whole shot, from the narrowest field of view anywhere on its camera path, so the look does not change part way through; 1 when upscaling is off,
        for a generated clip, for night footage (`upscale.skip_reason`) and where the footage already holds enough pixels."""
        if not self.up_w: return 1
        if sg.get('synthetic'): self.why[sg['id']] = 'generated clip'; return 1
        if sg['id'] not in self._factors:
            from strata360.analysis.views import NATIVE_PPD as _PPD
            try: ls = self._clip(sg['clip'])['R'].ls                                                       # lens pixels per degree: fewer on a smaller lens picture
            except (OSError, KeyError): ls = 3840                                                          # no clip record to read (the footage is judged by name only): a DJI-sized lens
            NATIVE_PPD = _PPD * ls / 3840.0
            why = UP.skip_reason(os.path.join(config.race_dir(self.folder), 'clips', sg['clip'])); path = cam.CameraPath.from_dict(self.framing[sg['id']]); fov = float(np.min(path.fov)); f = 1 if why else UP.factor_for(NATIVE_PPD, self.up_w, fov)
            if f > 1:                                                                                  # only a shot with more than up_min_s seconds at or over the zoom threshold is enlarged (the whole shot then)
                over = UP.seconds_over(path.t, path.fov, sg.get('dur_s'), self.W, NATIVE_PPD, self.up_min_zoom)
                if over <= self.up_min_s: f = 1; why = f'only {over:.1f} s of it need {self.up_min_zoom:g}x or more'
            self._factors[sg['id']] = f; self.why[sg['id']] = why or ('' if f > 1 else 'the footage already holds enough pixels')
            if f > 1 or why: self.pg.note(f"{sg['id']}: " + (f'not enlarged ({why})' if why else f'enlarged x{f} (narrowest view {fov:.0f} degrees)'))
        return self._factors[sg['id']]

    def _renderer(self, ci, f):
        """The renderer for a shot with enlargement f: it makes the picture at 1/f of the size the model works up to (`up_w`: the output's, or 1080p or 1440p; about what the lens holds), which the model then enlarges."""
        size = (self.W, self.H) if f == 1 else (-(-self.up_w // f), -(-(self.up_w * self.H // self.W) // f))
        if size not in ci['Rs']: ci['Rs'][size] = ci['R'] if size == (self.W, self.H) else flat.Renderer(ci['osv'], size[0], size[1], 90.0, self.interp)
        return ci['Rs'][size]

    def _enlarge(self, img, f):
        with self.pg.timed('upscale'): out = UP.upscale(img, f, bgr=False)
        if out.shape[:2] == (self.H, self.W): return out
        with self.pg.timed('resample'): return cv2.resize(out, (self.W, self.H), interpolation=cv2.INTER_LANCZOS4 if out.shape[1] < self.W else cv2.INTER_AREA)         # the standard resample from where the model stopped to the output size

    def synthetic_path(self, sg):
        """The video of a generated window: the clip rendered from its original sources at THIS film's frame rate and size (edit/synth_render.py: the same renderers as the preview's clip, other parameters; kept for the next render), else the clip the planner made (a kind cut from footage, a clip that cannot be made, or `film_synthetic` off for a quick still)."""
        if not self.film_synthetic: return sg['synthetic']
        from strata360.edit import synth_render as SR, synthetic as SY
        key = (sg['clip'], self.fps, self.W, self.H)
        if key not in self._synth:
            path = None
            try:
                doc = next((c for c in SY.load(self.folder)['clips'] if c['id'] == sg['clip']), None)
                if doc is not None and (self.last_only or self.cached_only):                                                  # a still or the preview: the film's clip when it has been made, never a whole new render for a quick look
                    p = SR.film_path(self.folder, doc, self.fps, (self.W, self.H)); path = p if os.path.exists(p) else None
                elif doc is not None: path = SR.for_film(self.folder, doc, self.fps, (self.W, self.H), log=self.pg.note)
            except (ValueError, RuntimeError, OSError) as e: self.pg.note(f"{sg['clip']}: not made at the film's size and rate ({e}); the planner's clip is used")
            self._synth[key] = path or sg['synthetic']
        return self._synth[key]

    def pointcam_footage(self, sg):
        """A point camera on a clip (edit/pointcam.py) is not a video to play: it is the clip's own footage seen through the camera's path, so the final render cuts it from the original OSV like any shot (full resolution, the film's rate). Returns the window as a footage window and registers its camera path, or None for any other generated clip."""
        if sg['id'] in self._pc: return self._pc[sg['id']]
        out = None
        try:
            from strata360.edit import pointcam as PCM, pointcam_clip as PK, synthetic as SY
            rd = config.race_dir(self.folder); cam = next((c for c in PCM.load(rd)['cams'] if c['id'] == sg['clip']), None)
            if cam is not None and cam['source']['kind'] == 'clip':
                doc = next(c for c in SY.load(self.folder)['clips'] if c['id'] == sg['clip']); pl = PK.plan(self.folder, cam, doc['seconds']); t0 = pl['t0'] - pl['extra'][0]; shift = float(sg['clip_start_s'])
                path = PK.clip_path(pl['samples'], t0, pl['north_offset']); path['keyframes'] = [dict(kf, t=round(kf['t'] - shift, 3)) for kf in path['keyframes']]              # (the path's times are from the shot's start; the window may start part way in)
                self.framing[sg['id']] = path; out = dict(sg, synthetic=None, clip=cam['source']['clip'], clip_start_s=t0 + shift, utc_start=dt.datetime.fromtimestamp(pl['t0'] + shift, dt.timezone.utc).isoformat().replace('+00:00', 'Z'))
        except (ValueError, RuntimeError, OSError, StopIteration) as e: self.pg.note(f"{sg['clip']}: cannot be cut from the footage ({e}); the planner's clip is used")
        self._pc[sg['id']] = out; return out

    def source_times(self, sg, a0, a1, ci=None):
        """Clip seconds of window frames a0..a1 (unclamped): `clip_start_s + i / fps`, or for a ramp window (edit/hyperlapse.py) the ramp's times, with the frames the picker chose from the clip's gyro and
        accelerometer when `ci` (the clip's record: pts and telemetry) is given. The choice is made once for the whole window (and a little either side, for a transition), so pieces agree."""
        t = np.arange(a0, a1) / self.fps
        if not sg.get('ramp'): return sg['clip_start_s'] + t
        key = (sg['id'], self.fps, ci is not None)
        if key not in self._ramps:
            n = int(round(float(sg['dur_s']) * self.fps)); pad = min(n, int(math.ceil(4 * self.fps))); tt = np.arange(-pad, n + pad + 1) / self.fps
            self._ramps[key] = (-pad, HL.source_times(sg, tt, ci['pts'], ci['T'].get('quat'), ci['T'].get('acc')) if ci is not None else HL.src_time(sg, tt))
        lo, src = self._ramps[key]; i = np.arange(a0, a1) - lo; inside = (i >= 0) & (i < len(src))
        return np.where(inside, src[np.clip(i, 0, len(src) - 1)], HL.src_time(sg, t))

    def _proxy_frames(self, sg, a0, a1, yaw_extra=None, pose_extra=None):
        """A footage window from the clip's PROXY (upright equirect video, render/preview.py) instead of the original lenses: the quick source of the preview. Everything after the picture is the film's own: the camera path, the projection (EquirectView = the renderer's maths), the exposure match and the race overlay, giving the same RGB code values; a clip with no proxy yet gives a dark card."""
        from strata360.render import preview as PV
        m = a1 - a0
        if m <= 0: return
        clip, fps = sg['clip'], self.fps; src = self.source_times(sg, a0, a1)          # (a ramp window plays its clip faster: edit/hyperlapse.py; the preview takes the ramp's own times, without the frame picker)
        if clip not in self._pinfo:
            p = proxy_of(self.folder, clip); side = json.load(open(os.path.splitext(p)[0] + '.json')) if p else None; self._pinfo[clip] = dict(proxy=p, side=side, stab=None)
        ci = self._pinfo[clip]; gain = self.gains.get(sg['id'])
        def out(img, i):
            img = np.ascontiguousarray(img[..., ::-1]).astype(np.uint16) * 257                                        # BGR 8-bit to the renderer's RGB code values
            return img if self.overlay is None else self.overlay.apply(img, utc0 + float(src[i]) - sg['clip_start_s'])
        utc0 = dt.datetime.fromisoformat(sg['utc_start'].replace('Z', '+00:00')).timestamp() if self.overlay is not None else 0.0
        if not ci['proxy']:
            for i in range(m): yield out(PV.card(self.W, self.H, f'{clip[-9:]}: proxy not made yet'), i)
            return
        if self._eq is None: self._eq = PV.EquirectView(self.W, self.H)
        V = self._eq; path = cam.CameraPath.from_dict(self.framing[sg['id']]); V.set_background(path.bg, **path.bg_opts); side = ci['side']; ez = np.array([0.0, 0.0, 1.0])
        t_from = float(src[0]); fr_n = len(side['frames']); Ms = None
        if path.ref != 'world':                                                          # heading-follow and body paths need the stabilisation of each frame (as the real renderer)
            if ci['stab'] is None: ci['stab'] = PV.stab_matrices(config.source(json.load(open(os.path.join(config.race_dir(self.folder), 'clips', clip, 'clip.json')))['source_files']['osv'], os.path.join(config.race_dir(self.folder), 'clips', clip)))
            idx = np.clip(np.round(np.maximum(src, 0.0) * fps).astype(int), 0, fr_n - 1); Ms = [ci['stab'](side['frames'][j]['source_frame']) for j in idx]
        P = path.evaluate(np.arange(a0, a1) / fps, Ms, fps)
        W0, H0 = side['size']; dw = min(self.decode_w, W0); dh = dw // 2
        dec = guard.popen(['ffmpeg', '-v', 'error', '-ss', f'{max(t_from, 0.0):.3f}', '-i', ci['proxy'], '-t', f'{max(float(src[-1]) - max(t_from, 0.0), 0.0) + 1.0 / fps + 0.2:.3f}', '-an', '-vf', f'scale={dw}:{dh}:flags=fast_bilinear', '-r', ffmpeg_rate(fps), '-pix_fmt', 'bgr24', '-f', 'rawvideo', '-'], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        fr = None; want = np.round((np.maximum(src, 0.0) - max(t_from, 0.0)) * fps).astype(int); got = -1; eof = False          # the decoded frame each output frame shows: before the clip starts the first frame is held
        try:
            for i in range(m):
                while (got < want[i] or fr is None) and not eof:                              # (a ramp window skips the frames between; past the end of the clip the last frame is held)
                    buf = dec.stdout.read(dw * dh * 3)
                    if len(buf) == dw * dh * 3: fr = np.frombuffer(buf, np.uint8).reshape(dh, dw, 3); got += 1
                    else:
                        eof = True
                        if fr is None: fr = np.zeros((dh, dw, 3), np.uint8)
                V.set_fov(P['fov'][i] + (float(pose_extra[i][2]) if pose_extra is not None else 0.0), P['dist'][i], (float(pose_extra[i][3]) if pose_extra is not None and len(pose_extra[i]) > 3 and pose_extra[i][3] > 0 else (P['disc'][i] if P['use_disc'] else None)))
                yaw = P['yaw'][i] + (float(yaw_extra[i]) if yaw_extra is not None else 0.0) + (math.radians(float(pose_extra[i][0])) if pose_extra is not None else 0.0)
                vdir = cam.direction(yaw, P['pitch'][i] + (math.radians(float(pose_extra[i][1])) if pose_extra is not None else 0.0)); img = V.render(fr, Ms[i].T @ vdir if P['ref'] == 'body' else vdir, ez, float(P['roll'][i]))
                yield out(img if gain is None else GR.apply(img, gain(max((a0 + i) / fps, 0.0))), i)                      # the exposure match (render/grade.py), the same maths as the final film
        finally:
            dec.stdout.close(); dec.terminate(); dec.wait()

    def frames(self, k, a0, a1, yaw_extra=None, pose_extra=None):
        sg = self.segs[k]
        if sg.get('synthetic') and self.film_synthetic: sg = self.pointcam_footage(sg) or sg
        if sg.get('synthetic'):                                                                                    # a generated clip: no lens; the film's own overlay goes on it, at the race time each frame shows
            frames = SYN.frames(self.synthetic_path(sg), sg['clip_start_s'], a0, a1, self.fps, self.W, self.H, 'rgb', np.uint16)
            if self.overlay is None: yield from frames; return
            for i, img in enumerate(frames): yield self.overlay.apply(img, SYN.race_time(sg, a0 + i, self.fps))
            return
        if self.source == 'proxy': yield from self._proxy_frames(sg, a0, a1, yaw_extra, pose_extra); return
        gain = self.gains.get(sg['id']); ci = self._clip(sg['clip']); f = self.shot_factor(sg); R = self._renderer(ci, f); R.carve_seam = True; R.parallax = True; R.seam = None; R.warp = None; m = a1 - a0                                    # a new stretch of the clip: the seam starts afresh
        if m <= 0: return
        path = cam.CameraPath.from_dict(self.framing[sg['id']]); R.set_background(path.bg, **path.bg_opts); times = np.arange(a0, a1) / self.fps; src = self.source_times(sg, a0, a1, ci); t_abs = np.maximum(src, 0.0); clock = HL.src_time(sg, times) - sg['clip_start_s']          # (a ramp window's frames: edit/hyperlapse.py)
        pts = ci['pts']; ks = np.minimum(flat.frame_at(pts, t_abs), ci['n'] - 1); quat = ci['T']['quat']             # the frame shown at clip time t is found by the frame timestamps, not by t x fps (a clip whose camera dropped frames has timestamps that jump)
        Ms = [R.stab_matrix(quat[min(int(j), len(quat) - 1)]) for j in ks]
        utc0 = dt.datetime.fromisoformat(sg['utc_start'].replace('Z', '+00:00')).timestamp() if self.overlay is not None else 0.0            # the window's first frame on the race clock
        P = path.evaluate(times, Ms, self.fps); first = int(ks[0]); ss = max(float(pts[first]) - 0.002, 0.0)
        nat = GPU.native_decode(); dm, ds = flat.decoder(ci['osv'], 1, ss=ss, native=nat), flat.decoder(ci['osv'], 0, ss=ss, native=nat); k_dec = first - 1; last_seam = None; cur_m = cur_s = None; ez = np.array([0.0, 0.0, 1.0])
        try:
            for i in range(m):
                while k_dec < ks[i]:
                    with self.pg.timed('decode'): a, b = flat.read_frame(dm, nat), flat.read_frame(ds, nat)
                    if a is None or b is None: break                                              # past the end of the clip: the last frame is held
                    cur_m, cur_s = a, b; k_dec += 1
                if cur_m is None: raise RuntimeError(f"could not read {ci['osv']} at {t_abs[i]:.2f} s")
                if k_dec != last_seam:
                    with self.pg.timed('seam'): R.update_seam(cur_m, cur_s, people=SM.people_in_layout(ci['boxes'](float(t_abs[i])), lambda d, M=Ms[i]: M @ d) if ci['boxes'] else None)
                    last_seam = k_dec                             # one seam per source frame
                R.set_fov(P['fov'][i] + (float(pose_extra[i][2]) if pose_extra is not None else 0.0), P['dist'][i], (float(pose_extra[i][3]) if pose_extra is not None and len(pose_extra[i]) > 3 and pose_extra[i][3] > 0 else (P['disc'][i] if P['use_disc'] else None)))
                yaw = P['yaw'][i] + (float(yaw_extra[i]) if yaw_extra is not None else 0.0) + (math.radians(float(pose_extra[i][0])) if pose_extra is not None else 0.0); d = cam.direction(yaw, P['pitch'][i] + (math.radians(float(pose_extra[i][1])) if pose_extra is not None else 0.0)); M = Ms[i]
                with self.pg.timed('project'): img = R.render(cur_m, cur_s, d if P['ref'] == 'body' else M @ d, M @ ez, float(P['roll'][i]))
                if self.last_only and i < m - 1: yield img; continue
                if f > 1: img = self._enlarge(img, f)                                                  # the model's work, before the grade and the overlay (they are made at full size)
                if gain is not None:
                    with self.pg.timed('grade'): img = GR.apply(img, gain(max(times[i], 0.0)))         # the exposure match, before the overlay so the numbers are never graded
                if self.overlay is None: yield img
                else:
                    with self.pg.timed('overlay'): img = self.overlay.apply(img, utc0 + float(clock[i]))          # the race clock races through a ramp: the ramp's own time (the time map's), at most a few source frames from the frame the picker chose
                    yield img           # before any transition blend, so a dissolve cross-fades the two overlays too
        finally:
            for p in (dm, ds):
                p.kill(); p.wait()


def encoder_args(bitrate):
    from strata360 import hw
    if hw._hardware('hevc'): return hw.hevc_args(bitrate, main10=True)
    return ['-c:v', 'libx265', '-crf', '17', '-preset', 'medium', '-tag:v', 'hvc1', '-pix_fmt', 'yuv420p10le']


def encode_piece(path, W, H, fps, bitrate, run, pg=None, post=None):
    """run(emit) renders the piece's frames into emit; they are encoded to `path` (kept only when complete). `pg`: a render/progress.py recorder that is told how long the encoder takes to accept the frames."""
    native = GPU.available() and W % 2 == 0 and H % 2 == 0 and os.environ.get('STRATA_GPU_DECODE') != '0'          # the RGB to YUV conversion on the GPU too (ffmpeg's takes a core per encoder): the pipe carries p010
    src_args = ['-pix_fmt', 'p010le', '-color_range', 'tv', '-colorspace', 'bt709'] if native else ['-pix_fmt', 'rgb48le']
    cmd = ['ffmpeg', '-v', 'error', '-y', '-f', 'rawvideo', *src_args, '-s', f'{W}x{H}', '-r', ffmpeg_rate(fps), '-i', '-', *([] if native else ['-vf', 'scale=in_range=full:out_range=tv:out_color_matrix=bt709:flags=accurate_rnd+full_chroma_int']),
           *encoder_args(bitrate), '-colorspace', 'bt709', '-color_primaries', 'bt709', '-color_trc', 'bt709', '-color_range', 'tv', path + '.part.mov']
    enc = guard.popen(cmd, stdin=subprocess.PIPE)
    count = [0]

    def put(img):
        if post is not None: img = post(img, count[0])                                                         # subtitles (and any other text) on the finished frame
        count[0] += 1
        data = GPU.rgb48_to_p010(img) if native else np.ascontiguousarray(img).tobytes()
        if pg is None: enc.stdin.write(data)
        else:
            with pg.timed('encode'): enc.stdin.write(data)
    try:
        run(put); enc.stdin.close(); enc.wait()
        if enc.returncode: raise RuntimeError('the encoder failed')
    except BaseException:
        try: enc.kill()
        except OSError: pass
        raise
    os.replace(path + '.part.mov', path); open(path + '.done', 'w').close()


def render_final(*a, **k):
    with guard.heavy('final render', 4.0): return _render_final(*a, **k)


THREAD_VARS = ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS')


def vram_workers(width, height):
    """How many render processes fit in the free GPU memory, or None without CUDA. Each holds the lens frames, the sampling maps and the encoder's copy of the picture: measured 2.6 GB at 1920x1080 and 5.2 GB at 3840x2160 (about 1.2 GB plus 0.5 GB a megapixel of output); six at 4K ran the card out of memory and the encoders died."""
    from strata360.render import gpu
    if not gpu.available(): return None
    import torch
    free = torch.cuda.mem_get_info()[0] / 1e9; return max(1, int(free // (1.2 + 0.5 * width * height / 1e6)))


def render_workers(size=(3840, 2160)):
    """How many processes render pieces at once. A piece is independent of the others, so they scale with the cores. `STRATA_RENDER_WORKERS` sets it; by default 1 on macOS (the machine stays usable for other work) and, elsewhere, one per five logical CPUs and six GB of memory, at most 6, and no more than the GPU's free memory holds for this output size."""
    try: return max(int(os.environ['STRATA_RENDER_WORKERS']), 1)
    except (KeyError, ValueError): pass
    if sys.platform == 'darwin': return 1
    from strata360.pipeline import resources as RS
    n = max(1, min(6, (os.cpu_count() or 4) // 5, int(RS.mem_total_gb() // 6))); v = vram_workers(*size)
    return n if v is None else min(n, v)


def _claim(path):
    """Take the piece for this process: True when the claim file was created (it holds our pid), or when the process that held it has died. Several workers share the pieces through these files."""
    from strata360 import oslib
    for _ in range(2):
        try: fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY); os.write(fd, str(os.getpid()).encode()); os.close(fd); return True
        except FileExistsError:
            try: pid = int(open(path).read() or 0)
            except (OSError, ValueError): return False
            if oslib.pid_alive(pid): return False
            try: os.remove(path)
            except OSError: return False
    return False


def render_bookends(folder, d, size, fps, bitrate, pg):
    """The opening and the ending as pieces of their own (edit/bookends.py): the chosen shot from the original footage with its camera move, the title over it, no race overlay. Returns {where: (movie, seconds)}; pieces already made are kept."""
    from strata360.edit import bookends as BK
    from strata360.render import titles as TT
    W, H = size; out = {}
    for b in BK.for_film(folder):
        c = b['c']; spec = b['spec']; sig = hashlib.sha1(json.dumps([c, spec, size, fps, bitrate], sort_keys=True, default=str).encode()).hexdigest()[:8]; f = os.path.join(d, f"bookend-{b['where']}-{sig}.mov"); n = int(round(c['dur_s'] * fps))
        if not os.path.exists(f + '.done'):
            pg.detail(f"the {b['where']}: {c['id']}"); g = BK.segment_of(c); src = FinalSource(folder, [g], {g['id']: BK.framing_of(folder, c)}, W, H, fps, progress=pg); tt = TT.Title(spec, W, H, c['dur_s']) if spec else None
            encode_piece(f, W, H, fps, bitrate, lambda emit: [emit(img) for img in src.frames(0, 0, n)], pg, post=(lambda im, i: tt.apply(im, i / fps)) if tt else None)
        out[b['where']] = (f, n / fps)
    return out


def _prepare(folder, plan, framing, size, fps, upscale, min_zoom, pg):
    """The part of a render every worker does: glides, exposure match, overlay, subtitle cues. Returns (plan, segs, pieces, source, captions)."""
    from strata360.edit import pans as PN
    from strata360.overlay import for_project
    W, H = size; plan0 = plan; plan = dict(plan, segments=PN.apply_pans(plan['segments'], framing, scorer=PN.looker(folder))[0]); segs = plan['segments']
    ps = pieces(segs, fps)
    src = FinalSource(folder, segs, framing, W, H, fps, overlay=for_project(folder, (W, H)), gains=GR.gains_for(folder, segs, framing), upscale=upscale, progress=pg, up_min_zoom=min_zoom)
    from strata360.render.captions import Captions
    from strata360.render import preview as PVW
    return plan, segs, ps, src, Captions.for_project(folder, plan, W, H, fps, key=PVW.plan_key(folder, plan0))                                          # (the subtitle track: voice-over and speech, in film time)


def _work(d, ps, segs, src, W, H, fps, bitrate, pg, on_done=None, limit_pieces=None, caps=None):
    """Render the pieces nobody else has claimed or finished, in order; returns the number rendered here."""
    mine = 0; base = {}; acc = 0
    for p in ps: base[p['id']] = acc; acc += p['frames']                                                       # the film frame each piece starts at: the subtitles are drawn by film time
    for n, p in enumerate(ps):
        if limit_pieces is not None and n >= limit_pieces: break
        f = os.path.join(d, p['id'] + '.mov')
        if os.path.exists(f + '.done') or not _claim(f + '.claim'): continue
        try:
            t_piece = time.time(); pg.detail(f'piece {n + 1} of {len(ps)}')
            encode_piece(f, W, H, fps, bitrate, lambda emit, p=p: render_piece(p, segs, src, emit), pg, post=(lambda im, i, b=base[p['id']]: caps.apply(im, b + i)) if caps is not None else None); mine += 1
            pg.note(f"piece {n + 1} of {len(ps)} ({p['kind']}, {p['frames']} frames) in {time.time() - t_piece:.0f} s")
        finally:
            try: os.remove(f + '.claim')
            except OSError: pass
        on_done and on_done()
    return mine


def worker_main(argfile):
    """A helper process of a parallel render: loads what the main render saved, renders pieces until none is left."""
    import pickle
    a = pickle.load(open(argfile, 'rb')); from strata360.render.progress import Null
    from strata360 import oslib; oslib.lower_priority(19)
    pg = Null(); plan, segs, ps, src, caps = _prepare(a['folder'], a['plan'], a['framing'], a['size'], a['fps'], a['upscale'], a['min_zoom'], pg)
    _work(a['d'], ps, segs, src, a['size'][0], a['size'][1], a['fps'], a['bitrate'], pg, limit_pieces=a['limit_pieces'], caps=caps)


def _render_final(folder, plan, framing, size=(3840, 2160), fps=50.0, bitrate='100M', limit_pieces=None, out=None, progress=None, upscale='off', pg=None, min_zoom=None, workers=None):
    """Render (or continue) the final film; returns the path of the film. `limit_pieces` renders only the first pieces and does not assemble (for trying things out). `upscale`: a mode of edit/upscale.py (off, 1080p, 1440p, full): enlarge the shots that hold too few pixels with the local model up to that width, and resample from the model's size to the output's.
    `progress(frames_done, frames_total)`: a callback; `pg`: the render/progress.py recorder (default: progress.json in the film's folder), which the page shows.
    `workers`: how many processes render pieces at the same time (`render_workers()` by default): the others are started here, share the pieces through `.claim` files and are waited for."""
    from strata360.render.progress import Progress
    key = final_key(plan, list(size), fps, bitrate, folder, upscale, min_zoom)                                                                 # of the plan as saved (the server looks the film up by it); the glides follow from the plan
    d = final_dir(folder, key); os.makedirs(d, exist_ok=True); pg = pg or Progress(os.path.join(d, 'progress.json')); W, H = size; kids = []
    try:
        with pg.stage('prepare', 'glides, exposure match, overlay'):
            plan0 = plan; plan, segs, ps, src, caps = _prepare(folder, plan, framing, size, fps, upscale, min_zoom, pg); total = sum(p['frames'] for p in ps); t0 = time.time()
            pg.note(f'{len(ps)} pieces, {total} frames at {W}x{H}, {fps:g} frames a second' + (f', enlarging the shots that need it ({UP.LABELS[UP.normalize(upscale)].lower()})' if UP.normalize(upscale) != 'off' else ''))
        def finished(): return [p for p in ps if os.path.exists(os.path.join(d, p['id'] + '.mov.done'))]
        def status(state, **kw): json.dump(dict(state=state, pid=os.getpid(), key=key, frames_done=sum(p['frames'] for p in finished()), frames_total=total, pieces_done=len(finished()), pieces_total=len(ps), started=t0, **kw), open(os.path.join(d, 'status.json.tmp'), 'w')); os.replace(os.path.join(d, 'status.json.tmp'), os.path.join(d, 'status.json'))
        status('rendering')
        n_run = len(ps) if limit_pieces is None else min(limit_pieces, len(ps)); nw = min(workers or render_workers(size), max(n_run, 1))
        def tick(): status('rendering'); progress and progress(sum(p['frames'] for p in finished()), total)
        if nw > 1:
            import pickle
            from strata360 import oslib
            share = max(1, (os.cpu_count() or 4) // (nw * 2))                                                                                    # each process gets its share of the cores for numpy / OpenCV (32 threads each, six times over, is slower than 5)
            for k in THREAD_VARS: os.environ[k] = str(share)
            cv2.setNumThreads(share)
            af = os.path.join(d, 'worker.pickle'); pickle.dump(dict(folder=folder, plan=plan0, framing=framing, size=size, fps=fps, upscale=upscale, min_zoom=min_zoom, bitrate=bitrate, d=d, limit_pieces=limit_pieces), open(af, 'wb'))
            for i in range(nw - 1):
                env = dict(os.environ, PYTHONPATH=os.path.join(oslib.ROOT_DIR, 'src') + os.pathsep + os.environ.get('PYTHONPATH', ''), **{k: str(share) for k in THREAD_VARS})
                kids.append(guard.popen([sys.executable, '-m', 'strata360.render.final', '--worker', af], env=env, stdout=open(os.path.join(d, f'worker{i + 1}.log'), 'w'), stderr=subprocess.STDOUT)); time.sleep(2)           # staggered: the first claims go to different pieces
            pg.note(f'{nw} processes render pieces at the same time')
        with pg.stage('render', f'piece 0 of {len(ps)}'):
            while True:
                _work(d, ps, segs, src, W, H, fps, bitrate, pg, on_done=tick, limit_pieces=limit_pieces, caps=caps); tick()
                if all(os.path.exists(os.path.join(d, p['id'] + '.mov.done')) for p in ps[:n_run]): break
                if not any(k.poll() is None for k in kids) and not any(os.path.exists(os.path.join(d, p['id'] + '.mov.claim')) for p in ps[:n_run]): raise RuntimeError(f'pieces are missing and no worker is left (see {d}/worker*.log)')
                pg.detail(f'{len(finished())} of {len(ps)} pieces done, waiting for the other workers'); time.sleep(2)
        for k in kids: k.wait()
        if limit_pieces is not None: status('partial'); pg.finish(); return d
        with pg.stage('bookends'): bk = render_bookends(folder, d, size, fps, bitrate, pg)
        lead = bk['intro'][1] if 'intro' in bk else 0.0; tail = bk['outro'][1] if 'outro' in bk else 0.0
        from strata360.render import captions as CP; CP.write_srt([dict(c, t0=c['t0'] + lead, t1=c['t1'] + lead) for c in caps.cues], os.path.join(d, 'film.srt'))                  # the subtitles as a file too, beside the film (after the opening)
        with pg.stage('timemap'):
            from strata360.render import timemap; timemap.write(plan, fps, d)                                                         # which footage is on screen at every frame (timemap.json and .csv beside the film)
        status('assembling')
        with pg.stage('audio'):
            audio = os.path.join(d, 'audio.wav'); sound = build_audio(folder, plan, audio, total / fps, loudness=loudness_target(folder))          # the film's sound, to its loudness target
            if lead or tail:                                                                                                                     # the opening and the ending are silent for now: the film's sound is moved after the opening
                padded = os.path.join(d, 'audio_full.wav'); ms = int(round(lead * 1000)); r = subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', audio, '-af', f'adelay={ms}:all=1,apad=pad_dur={tail:.3f}', padded], capture_output=True, text=True)
                if r.returncode: raise RuntimeError(r.stderr[-300:])
                audio = padded
        with pg.stage('assemble'):
            lst = os.path.join(d, 'pieces.txt'); open(lst, 'w').write(''.join(f"file '{m}'\n" for m in [bk[w][0] for w in ('intro',) if w in bk] + [os.path.join(d, p['id'] + '.mov') for p in ps] + [bk[w][0] for w in ('outro',) if w in bk])); film = out or os.path.join(d, 'film.mp4')
            r = subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'concat', '-safe', '0', '-i', lst, '-i', audio, '-map', '0:v', '-map', '1:a', '-c:v', 'copy', '-c:a', 'aac', '-b:a', '256k', '-shortest', '-movflags', '+faststart', film], capture_output=True, text=True)
            if r.returncode: status('error', error=r.stderr[-300:]); raise RuntimeError(r.stderr[-300:])
        status('done', finished=time.time(), film=film, sound=sound); pg.finish(); return film
    except BaseException as e:
        if pg.state == 'running': pg.fail(e)
        raise
    finally:
        for k in kids:
            if k.poll() is None: k.kill()


def main():
    import argparse
    from strata360.edit import framing as FR, project as PJ
    ap = argparse.ArgumentParser(); ap.add_argument('folder', nargs='?'); ap.add_argument('--size', default='3840x2160'); ap.add_argument('--fps', type=float, default=0.0, help='frames a second; 0 (the default) is the footage\'s own rate'); ap.add_argument('--half-rate', action='store_true', help='half the rate: every other source frame (faster)'); ap.add_argument('--bitrate', default='100M')
    ap.add_argument('--workers', type=int, default=None, help='processes rendering pieces at once (default: STRATA_RENDER_WORKERS, else by cores and memory; 1 on a Mac)'); ap.add_argument('--worker', help=argparse.SUPPRESS); ap.add_argument('--pieces', type=int, help='render only the first N pieces (a trial; nothing is assembled)'); ap.add_argument('--out'); ap.add_argument('--upscale-min-zoom', type=float, default=None, help=f'enlarge a shot only if more than {UP.MIN_SECONDS:g} s of it need at least this zoom (default {UP.MIN_ZOOM:g})'); ap.add_argument('--upscale', nargs='?', const='full', default='off', choices=list(UP.MODES), help='enlarge shots that hold too few pixels with the local model (slow): to the output size (full, the default when given), or to 1080p / 1440p and then resample'); a = ap.parse_args()
    if a.worker: worker_main(a.worker); return
    from strata360 import oslib; oslib.lower_priority(19)
    plan = PJ.load(a.folder).get('plan')
    if not plan: sys.exit('no plan yet')
    W, H = map(int, a.size.split('x')); fr = FR.resolve(a.folder, plan, head=True); fps = resolve_fps(a.folder, plan, a.fps, a.half_rate)
    print(render_final(a.folder, plan, fr, (W, H), fps, a.bitrate, a.pieces, a.out, progress=lambda i, n: print(f'\r{i}/{n} frames', end='', flush=True), upscale=a.upscale, min_zoom=a.upscale_min_zoom, workers=a.workers))


if __name__ == '__main__': main()
