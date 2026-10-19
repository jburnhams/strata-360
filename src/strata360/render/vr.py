"""The 360 version of the film: the same edit rendered as an equirectangular video, for YouTube 360 or a headset, with the race overlay and the text pinned in front of the viewer.

The plan, the windows, the sound, the subtitles and the time map are the final film's (render/final.py); what changes is the picture of every frame:

  footage      the whole sphere from the two lenses (render/proxy.py `EquirectRenderer`: the same calibration, stabilisation, seam and parallax as the flat film), upright and with a level horizon,
               turned so that the direction the flat shot looks at is straight ahead (the centre of the frame, where a 360 player starts). `orient`:
                 'shot'    one direction for the whole window (the circular mean of the shot's view): the world keeps still within a shot and turns only at a cut (the comfortable default in a headset)
                 'follow'  the direction frame by frame (pans and heading-follow turn the world round the viewer)
               the shot's pitch, roll, field of view, little planets and globes are flat-film framing: they are not used, the viewer looks where they like.
  generated    maps, flyovers, photos and street view are flat pictures: shown on a screen in front of the viewer (the panel below) over a dark sphere.
  transitions  dissolves and dips blend whole spheres as in the flat film; whips and glides (camera moves through a cut) are hard cuts here.
  overlay      the flat film's overlay, subtitles, word-art cards and titles are drawn on a flat 16:9 panel `fov` degrees wide, centred straight ahead and `pitch` degrees up, and that panel is pinned
               onto the sphere (only the pixels the drawing changed are replaced, so the scene behind stays sharp). In the headset it sits ahead like a screen; turning away leaves it behind.

The output is HEVC 10-bit like the flat film, 2:1 (3840x1920 by default; 5760x2880 and 7680x3840 for a sharper headset), with the spherical metadata (render/spherical.py) that YouTube and players need.
  <project>/final/<key>/film-360.mp4   the result (the key includes the 360 settings, so the flat film and the 360 one never share pieces)"""
import datetime as dt, hashlib, json, math, os, subprocess
import cv2
import numpy as np
from strata360.pipeline import config, guard
from strata360.render import camera as cam, final as FN, flat, grade as GR, seam as SM, synthetic as SYN

FOV = 80.0                      # the panel's width in degrees: the overlay's corners stay inside a headset's or a 360 player's view (about 90 to 100 degrees)
PITCH = 0.0
ORIENTS = ('shot', 'follow')
SIZES = ('3840x1920', '5760x2880', '7680x3840')
BACKDROP = 0.05                 # the sphere behind a generated clip's screen: a dark grey (BT.709 code value, 0..1)
FLAT_TYPES = ('whip', 'pan')    # transitions that move a flat camera: cuts in 360


def options(fov=FOV, pitch=PITCH, orient='shot', source='osv'):
    """The 360 settings render/final.py passes round (and pickles for its worker processes)."""
    if orient not in ORIENTS: raise ValueError(f'orient must be one of {", ".join(ORIENTS)}')
    if not 20.0 <= float(fov) <= 150.0: raise ValueError('the panel must be 20 to 150 degrees wide')
    return dict(fov=float(fov), pitch=float(pitch), orient=orient, source=source)


def signature(opts):
    """The 360 part of the final film's key."""
    return '360:' + json.dumps({k: opts[k] for k in ('fov', 'pitch', 'orient')}, sort_keys=True)


def check_size(W, H):
    if W != 2 * H or W % 2 or H % 2: raise ValueError(f'a 360 film is 2:1 with even sides ({W}x{H} is not): for example {", ".join(SIZES)}')


def rot_z(psi):
    """World direction = rot_z(psi) @ sphere direction: the sphere's centre (+Y) looks at world yaw `psi` (yaw positive to the right, render/camera.py)."""
    c, s = math.cos(psi), math.sin(psi); return np.array([[c, s, 0.0], [-s, c, 0.0], [0.0, 0.0, 1.0]])


def view_yaw(P, Ms):
    """World yaw (radians) of a flat camera path's view, frame by frame: P from CameraPath.evaluate, Ms the stabilisation matrices (d_body = M d_world; only a body-fixed path needs them)."""
    if P['ref'] != 'body': return np.asarray(P['yaw'], float)
    out = []
    for i, M in enumerate(Ms):
        d = M.T @ cam.direction(P['yaw'][i], P['pitch'][i]); out.append(math.atan2(d[0], d[1]))
    return np.array(out)


def circular_mean(a):
    a = np.asarray(a, float); return float(math.atan2(np.sin(a).mean(), np.cos(a).mean())) if len(a) else 0.0


class Panel:
    """A flat 16:9 picture pinned on the equirectangular sphere (W x H, centre column = straight ahead): `fov` degrees wide, its centre `pitch` degrees above the horizon.
    `size` is the panel's own picture size, as many pixels across its centre as the sphere has there (so drawing on it costs about what the sphere can show)."""
    def __init__(self, W, H, fov=FOV, pitch=PITCH, aspect=16 / 9):
        self.W, self.H, self.fov, self.pitch = W, H, float(fov), float(pitch); self.t = math.tan(math.radians(self.fov) / 2)
        pw = max(int(round(self.t * W / math.pi)), 16); pw += pw % 2; ph = max(int(round(pw / aspect)), 8); ph += ph % 2; self.size = (pw, ph)
        p = math.radians(self.pitch); self.f = np.array([0.0, math.cos(p), math.sin(p)]); self.r = np.array([1.0, 0.0, 0.0]); self.u = np.cross(self.r, self.f)
        x = ((np.arange(pw) + 0.5) - pw / 2) / (pw / 2) * self.t; y = (ph / 2 - (np.arange(ph) + 0.5)) / (pw / 2) * self.t; X, Y = np.meshgrid(x, y)
        d = self.f[None, None] + X[..., None] * self.r + Y[..., None] * self.u; d /= np.linalg.norm(d, axis=-1, keepdims=True)
        lon = np.arctan2(d[..., 0], d[..., 1]); lat = np.arcsin(np.clip(d[..., 2], -1, 1))
        self.fx = ((lon / (2 * np.pi) + 0.5) * W - 0.5).astype(np.float32); self.fy = ((0.5 - lat / np.pi) * H - 0.5).astype(np.float32)          # panel pixel -> sphere pixel
        self.x0, self.x1 = max(int(math.floor(self.fx.min())) - 2, 0), min(int(math.ceil(self.fx.max())) + 3, W); self.y0, self.y1 = max(int(math.floor(self.fy.min())) - 2, 0), min(int(math.ceil(self.fy.max())) + 3, H)
        xs = np.arange(self.x0, self.x1) + 0.5; ys = np.arange(self.y0, self.y1) + 0.5; LX, LY = np.meshgrid((xs / W - 0.5) * 2 * np.pi, (0.5 - ys / H) * np.pi)
        e = np.stack([np.sin(LX) * np.cos(LY), np.cos(LX) * np.cos(LY), np.sin(LY)], -1); a = e @ self.f
        with np.errstate(divide='ignore', invalid='ignore'):
            bx = (e @ self.r) / a / self.t * (pw / 2) + pw / 2 - 0.5; by = ph / 2 - (e @ self.u) / a / self.t * (pw / 2) - 0.5
        bad = a <= 1e-3; self.bx = np.where(bad, -10.0, bx).astype(np.float32); self.by = np.where(bad, -10.0, by).astype(np.float32)        # sphere pixel -> panel pixel (behind the viewer: off the panel)
        self._full = None

    def view(self, eq):
        """The panel's part of the sphere `eq`, as a flat picture of `size` (what a flat camera there would see)."""
        return cv2.remap(eq, self.fx, self.fy, cv2.INTER_LINEAR, borderMode=cv2.BORDER_WRAP)

    def place(self, eq, img, alpha):
        """`eq` with the flat picture `img` (the panel's size) laid on its patch of the sphere, weighted by `alpha` (float32, the panel's size, 0..1). Returns a new picture."""
        sub = cv2.remap(img, self.bx, self.by, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT); a = cv2.remap(alpha, self.bx, self.by, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0)[..., None]
        out = eq.copy(); reg = out[self.y0:self.y1, self.x0:self.x1].astype(np.float32)
        out[self.y0:self.y1, self.x0:self.x1] = np.clip(reg * (1 - a) + sub.astype(np.float32) * a + 0.5, 0, np.iinfo(eq.dtype).max).astype(eq.dtype); return out

    def pin(self, eq, draw):
        """`draw(flat) -> flat` (the overlay, a subtitle, a title) made on the panel's view of the sphere and pinned back: only the pixels the drawing changed (and a one-pixel rim) are replaced."""
        v = self.view(eq); d = draw(v.copy())
        if d is None: return eq
        changed = np.any(d != v, axis=-1)
        if not changed.any(): return eq
        alpha = cv2.dilate(changed.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(np.float32); return self.place(eq, d, alpha)

    def screen(self, img, dtype=np.uint16):
        """A flat picture (a generated clip) on the whole panel over the dark sphere."""
        top = np.iinfo(dtype).max; eq = np.full((self.H, self.W, 3), int(BACKDROP * top), dtype)
        if self._full is None: self._full = np.ones(self.size[::-1], np.float32)
        if img.shape[:2] != self.size[::-1]: img = cv2.resize(img, self.size, interpolation=cv2.INTER_AREA)
        return self.place(eq, img.astype(dtype), self._full)


class Pinned:
    """The film's subtitle track (render/captions.py `Captions`, made at the panel's size) drawn on the panel: `apply(eq, frame)` as encode_piece's `post` wants, `cues` for the .srt."""
    def __init__(self, panel, caps): self.panel, self.caps, self.cues = panel, caps, caps.cues

    def apply(self, eq, frame): return self.panel.pin(eq, lambda v: self.caps.apply(v, frame))


class VRSource(FN.FinalSource):
    """Frames of the planned windows as whole spheres (uint16 RGB code values, W x H equirectangular), with the overlay pinned on the panel. `overlay` is made at the panel's size."""
    def __init__(self, folder, segs, framing, W, H, fps, panel, orient='shot', overlay=None, gains=None, progress=None, source='osv'):
        super().__init__(folder, segs, framing, W, H, fps, interp='cubic', overlay=overlay, gains=gains, progress=progress, source=source); self.panel, self.orient = panel, orient; self._psi = {}

    def _clip(self, clip):
        if clip not in self.info:
            from strata360.osv.telemetry import read_frames, video_pts
            from strata360.render.proxy import EquirectRenderer
            cd = os.path.join(config.race_dir(self.folder), 'clips', clip); cj = json.load(open(os.path.join(cd, 'clip.json'))); osv = config.source(cj['source_files']['osv'], cd)
            R = EquirectRenderer(osv, self.W, self.H, self.interp); self.info[clip] = dict(boxes=self._boxes(clip, osv), osv=osv, src_fps=float(cj['video']['nominal_fps']), n=int(cj['video']['source_frames']), R=R, T=read_frames(osv), pts=np.asarray(video_pts(osv, 0), float))
        return self.info[clip]

    def synthetic_path(self, sg):
        """A generated clip at the flat film's size (the one the flat final render makes and keeps), not at the sphere's: it is shown on the panel."""
        W, H = self.W, self.H; self.W, self.H = flat_size(self.folder, sg, self.fps)
        try: return super().synthetic_path(sg)
        finally: self.W, self.H = W, H

    def _stab(self, ci, t_abs):
        ks = np.minimum(flat.frame_at(ci['pts'], t_abs), ci['n'] - 1); quat = ci['T']['quat']
        return ks, [ci['R'].stab_matrix(quat[min(int(j), len(quat) - 1)]) for j in ks]

    def directions(self, sg, path, times, Ms):
        """The world yaw at the sphere's centre for each of `times` (window seconds) of window `sg`."""
        if self.orient == 'follow': return view_yaw(path.evaluate(times, Ms, self.fps), Ms)
        if sg['id'] not in self._psi:                                                                  # one direction for the whole window, whichever part of it (or its handles) is asked for
            n = max(int(round(float(sg.get('dur_s') or 0.0) * self.fps)), 1); tw = np.arange(n) / self.fps; ci = self._clip(sg['clip']); _, Mw = self._stab(ci, np.maximum(sg['clip_start_s'] + tw, 0.0))
            self._psi[sg['id']] = circular_mean(view_yaw(path.evaluate(tw, Mw, self.fps), Mw))
        return np.full(len(times), self._psi[sg['id']])

    def _pin(self, eq, utc):
        if self.overlay is None: return eq
        with self.pg.timed('overlay'): return self.panel.pin(eq, lambda v: self.overlay.apply(v, utc))

    def frames(self, k, a0, a1, yaw_extra=None, pose_extra=None):
        """As FinalSource.frames; `yaw_extra` and `pose_extra` (the flat camera's whip and glide) are not used: those transitions are cuts in 360."""
        sg = self.segs[k]; m = a1 - a0
        if m <= 0: return
        if sg.get('synthetic') and self.film_synthetic: sg = self.pointcam_footage(sg) or sg
        if sg.get('synthetic'):
            pw, ph = self.panel.size
            for i, img in enumerate(SYN.frames(self.synthetic_path(sg), sg['clip_start_s'], a0, a1, self.fps, pw, ph, 'rgb', np.uint16)):
                if self.overlay is not None: img = self.overlay.apply(img.copy(), SYN.race_time(sg, a0 + i, self.fps))
                yield self.panel.screen(img)
            return
        if self.source == 'proxy': yield from self._proxy_spheres(sg, a0, a1); return
        gain = self.gains.get(sg['id']); ci = self._clip(sg['clip']); R = ci['R']; R.carve_seam = True; R.parallax = True; R.seam = None; R.warp = None
        path = cam.CameraPath.from_dict(self.framing[sg['id']]); times = np.arange(a0, a1) / self.fps; t_abs = np.maximum(sg['clip_start_s'] + times, 0.0)
        ks, Ms = self._stab(ci, t_abs); psi = self.directions(sg, path, times, Ms); pts = ci['pts']
        utc0 = dt.datetime.fromisoformat(sg['utc_start'].replace('Z', '+00:00')).timestamp() if self.overlay is not None else 0.0
        first = int(ks[0]); ss = max(float(pts[first]) - 0.002, 0.0); nat = FN.GPU.native_decode(); dm, ds = flat.decoder(ci['osv'], 1, ss=ss, native=nat), flat.decoder(ci['osv'], 0, ss=ss, native=nat); k_dec = first - 1; last_seam = None; cur_m = cur_s = None
        try:
            for i in range(m):
                while k_dec < ks[i]:
                    with self.pg.timed('decode'): a, b = flat.read_frame(dm, nat), flat.read_frame(ds, nat)
                    if a is None or b is None: break                                                  # past the end of the clip: the last frame is held
                    cur_m, cur_s = a, b; k_dec += 1
                if cur_m is None: raise RuntimeError(f"could not read {ci['osv']} at {t_abs[i]:.2f} s")
                if k_dec != last_seam:
                    with self.pg.timed('seam'): R.update_seam(cur_m, cur_s, people=SM.people_in_layout(ci['boxes'](float(t_abs[i])), lambda d, M=Ms[i]: M @ d) if ci['boxes'] else None)
                    last_seam = k_dec
                with self.pg.timed('project'): img = R.render(cur_m, cur_s, Ms[i] @ rot_z(psi[i]), None)
                if gain is not None:
                    with self.pg.timed('grade'): img = GR.apply(img, gain(max(times[i], 0.0)))
                yield self._pin(img, utc0 + times[i])
        finally:
            for p in (dm, ds):
                p.kill(); p.wait()

    def _proxy_spheres(self, sg, a0, a1):
        """A footage window from the clip's proxy (already an upright sphere, render/proxy.py): turned by the window's direction (a turn about the vertical is a sideways shift of the equirect picture). The quick source, for checking the cut in a player."""
        m = a1 - a0; clip = sg['clip']; gain = self.gains.get(sg['id']); utc0 = dt.datetime.fromisoformat(sg['utc_start'].replace('Z', '+00:00')).timestamp() if self.overlay is not None else 0.0; p = FN.proxy_of(self.folder, clip)
        if not p:
            for i in range(m): yield self._pin(SYN.card(self.W, self.H, f'{clip[-9:]}: proxy not made yet', 'rgb', np.uint16), utc0 + (a0 + i) / self.fps)
            return
        path = cam.CameraPath.from_dict(self.framing[sg['id']]); times = np.arange(a0, a1) / self.fps; ci = self._clip(clip); _, Ms = self._stab(ci, np.maximum(sg['clip_start_s'] + times, 0.0)); psi = self.directions(sg, path, times, Ms)
        t_from = sg['clip_start_s'] + a0 / self.fps; skip = int(round(max(-t_from, 0.0) * self.fps)); n = self.W * self.H * 3
        dec = guard.popen(['ffmpeg', '-v', 'error', '-ss', f'{max(t_from, 0.0):.3f}', '-i', p, '-t', f'{(m / self.fps) + 0.2:.3f}', '-an', '-vf', f'scale={self.W}:{self.H}:flags=bicubic', '-r', FN.ffmpeg_rate(self.fps), '-pix_fmt', 'rgb48le', '-f', 'rawvideo', '-'], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        fr = None
        try:
            for i in range(m):
                if i >= skip or fr is None:
                    buf = dec.stdout.read(n * 2)
                    if len(buf) == n * 2: fr = np.frombuffer(buf, np.uint16).reshape(self.H, self.W, 3)
                    elif fr is None: fr = np.zeros((self.H, self.W, 3), np.uint16)
                img = np.roll(fr, -int(round(psi[i] / (2 * np.pi) * self.W)), axis=1)
                if gain is not None: img = GR.apply(img, gain(max(times[i], 0.0)))
                yield self._pin(img, utc0 + times[i])
        finally:
            dec.stdout.close(); dec.terminate(); dec.wait()


def flat_size(folder, sg, fps):
    """The size to take a generated clip at: the flat 4K film's when that clip has been made at 4K, else 1920x1080 (more than the panel holds)."""
    from strata360.edit import synth_render as SR, synthetic as SY
    try:
        doc = next((c for c in SY.load(folder)['clips'] if c['id'] == sg['clip']), None)
        if doc is not None and os.path.exists(SR.film_path(folder, doc, fps, (3840, 2160))): return 3840, 2160
    except (ValueError, OSError): pass
    return 1920, 1080


def as_cuts(segs):
    """The windows with the flat-camera transitions (whip, glide) made hard cuts."""
    return [dict(g, transition=dict(g['transition'], type='cut', dur_s=0.0)) if (g.get('transition') or {}).get('type') in FLAT_TYPES else g for g in segs]


def prepare(folder, plan, framing, size, fps, opts, pg):
    """render/final.py `_prepare` for the 360 film: (plan, segs, pieces, source, captions)."""
    from strata360.edit import pans as PN
    from strata360.overlay import for_project
    from strata360.render import preview as PVW
    from strata360.render.captions import Captions
    W, H = size; check_size(W, H); plan0 = plan; segs = as_cuts(PN.apply_pans(plan['segments'], framing, scorer=PN.looker(folder))[0]); plan = dict(plan, segments=segs)
    panel = Panel(W, H, opts['fov'], opts['pitch']); pw, ph = panel.size
    src = VRSource(folder, segs, framing, W, H, fps, panel, opts['orient'], overlay=for_project(folder, panel.size), gains=GR.gains_for(folder, segs, framing), progress=pg, source=opts.get('source', 'osv'))
    pg.note(f"360: {W}x{H} equirectangular, the overlay on a {opts['fov']:g} degree panel ({pw}x{ph}), one direction {'per shot' if opts['orient'] == 'shot' else 'per frame'}")
    return plan, segs, FN.pieces(segs, fps), src, Pinned(panel, Captions.for_project(folder, plan, pw, ph, fps, key=PVW.plan_key(folder, plan0)))


def render_bookends(folder, d, size, fps, bitrate, pg, opts):
    """The opening and the ending (render/final.py `render_bookends`) as spheres, the title pinned on the panel."""
    from strata360.edit import bookends as BK
    from strata360.render import titles as TT
    W, H = size; out = {}; panel = Panel(W, H, opts['fov'], opts['pitch'])
    for b in BK.for_film(folder):
        c = b['c']; spec = b['spec']; sig = hashlib.sha1(json.dumps([c, spec, size, fps, bitrate, signature(opts)], sort_keys=True, default=str).encode()).hexdigest()[:8]; f = os.path.join(d, f"bookend-{b['where']}-{sig}.mov"); n = int(round(c['dur_s'] * fps))
        if not os.path.exists(f + '.done'):
            pg.detail(f"the {b['where']}: {c['id']}"); g = BK.segment_of(c); src = VRSource(folder, [g], {g['id']: BK.framing_of(folder, c)}, W, H, fps, panel, opts['orient'], progress=pg, source=opts.get('source', 'osv')); tt = TT.Title(spec, *panel.size, c['dur_s']) if spec else None
            FN.encode_piece(f, W, H, fps, bitrate, lambda emit: [emit(img) for img in src.frames(0, 0, n)], pg, post=(lambda im, i: panel.pin(im, lambda v: tt.apply(v, i / fps))) if tt else None)
        out[b['where']] = (f, n / fps)
    return out
