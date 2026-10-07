"""Framing: for every window of the plan, where the camera looks and how it moves.

The plan says which part of which clip and which technique (hold, push in, pan ...). This adds the subject: who or what the technique is aimed at, from the analysis of the clip.

  the candidate's view   a stretch chosen for other people in view is framed on them, one chosen for you on you
  speech in the window   the speaker: another person while another voice talks, you (the wearer) while you talk
  tight techniques       (push in, dialogue hold): another person if one is in view, else you
  everything else        straight ahead (the runner's heading), unless another person is in view most of the time
  selfie hold            you (the wearer), or straight behind the runner when you are not found
  globe / spin / follow  no subject (planets look down, follow runner follows the heading)

A subject is followed by edit/aim.py: the camera holds while the subject stays near the centre, pans slowly when it drifts and moves once, fast, when it goes far; the pitch puts the head near the top of the frame. Output is the dict
CameraPath.from_json takes: world frame, yaw in degrees, keyframes every tenth of a second (window-relative seconds), plus `subject` and `why` for the GUI.
Nothing here needs the video: only identity.json / speakers.json / motion.json of the clip (analysis/views.py samples)."""
import json, os
import numpy as np
from scipy.ndimage import gaussian_filter1d
from strata360.pipeline import config
from strata360.edit import techniques as TQ, aim as AIM, attention as AT, clip_views as CV, scenery as SC, view_quality as VQ

FOLLOW = {'person_hold', 'hold_wide', 'dialogue_hold', 'push_in', 'pull_out', 'selfie_hold', 'selfie_close', 'selfie_far'}          # techniques that keep their subject in frame as it moves
NO_SUBJECT = {'follow_runner', 'planet_fill', 'planet_globe', 'planet_fill_zoom_out', 'globe_shrink', 'tunnel_up', 'spin_roll'}
TIGHT = {'push_in', 'dialogue_hold'}
YOU_VIEWS = {'selfie_hold', 'selfie_close', 'selfie_far'}      # the three views of you (mid, close, far)
STEP_S = 0.1
TRACK_STEP_S = 0.04          # the You views are tracked at this step (25 Hz)


def _coverage(samples, t0, t1):
    """Fraction of the window's seconds that have a sample within 1.5 s."""
    if not samples: return 0.0
    ts = np.array([s['t'] for s in samples]); grid = np.arange(t0, t1 + 1e-9, 1.0) if t1 > t0 else np.array([t0])
    return float(np.mean([np.min(np.abs(ts - g)) <= 1.5 for g in grid]))


def _track(samples, t0, t1):
    """(times, yaw unwrapped radians, pitch radians) of the samples in and around the window."""
    s = [x for x in samples if t0 - 2.0 <= x['t'] <= t1 + 2.0]
    h = []; last = None
    for x in s:                                                                          # the box height (degrees), carried over where the person was found by the face only
        last = x.get('height') or last; h.append(last)
    h = [v if v else next((u for u in h if u), 45.0) for v in h]
    hd = np.array([x['head'] if x.get('head') is not None else np.nan for x in s], float)                         # the pitch of the top of the head where it is known
    if np.isnan(hd).all(): hd = None
    else: hd = np.where(np.isnan(hd), np.nan, hd)
    return np.array([x['t'] for x in s]), np.unwrap(np.radians([x['yaw'] for x in s])), np.radians([x['pitch'] for x in s]), np.array(h, float), hd


HEAD_FAST_W = {'selfie_hold': 0.7, 'selfie_far': 0.5}          # how much of the head's fast motion the mid and far views follow (the close view aims at the head itself)


def _head_provider(d, samples, compute):
    """head(t0, t1) -> (t, yaw, pitch) of the head found at every proxy frame of the stretch (analysis/head_track.py: YOLO pose on stabilised crops), or None. Kept in `<clip>/youhead/`; `compute` says whether a stretch that is not kept yet may be worked out (about 20 s per 6 s of film, in .venv-vision): the render entry points say yes, planning only reads what is kept."""
    info = _proxy_info(d); samples = sorted(samples or [], key=lambda x: x['t'])
    if info is None or not samples or os.environ.get('STRATA_YOU_HEAD') == '0': return None
    import hashlib
    st = os.stat(info[0]); folder = os.path.join(d, 'youhead')
    def head(t0, t1):
        near = [x for x in samples if t0 - 3.0 <= x['t'] <= t1 + 3.0]
        if not near: return None
        key = hashlib.sha1(json.dumps([st.st_mtime_ns, st.st_size, round(t0, 2), round(t1, 2), [[x['t'], round(x['yaw'], 1), round(x['pitch'], 1)] for x in near]]).encode()).hexdigest()[:16]; path = os.path.join(folder, key + '.npz')
        if os.path.exists(path):
            with np.load(path) as z: return z['t'], z['yaw'], z['pitch']
        if not compute: return None
        from strata360.analysis import head_track as HT
        nt = np.array([x['t'] for x in near]); ny = np.degrees(np.unwrap(np.radians([x['yaw'] for x in near]))); npi = np.array([x['pitch'] for x in near])
        r = HT.head_positions(info[0], info[1], t0, t1, lambda t: (float(np.interp(t, nt, ny)) % 360.0, float(np.interp(t, nt, npi))))
        if r is None: return None
        os.makedirs(folder, exist_ok=True); np.savez(path + '.tmp.npz', t=r[0], yaw=r[1], pitch=r[2]); os.replace(path + '.tmp.npz', path); return r[0], r[1], r[2]
    return head


def _proxy_info(d):
    """(proxy path, its frame list, a folder for cached tracks) of a clip, or None without a proxy."""
    p = os.path.join(d, 'proxy.mp4'); j = os.path.join(d, 'proxy.json')
    try: return (p, json.load(open(j))['frames'], os.path.join(d, 'youtrack')) if os.path.exists(p) and os.path.exists(j) else None
    except (OSError, ValueError, KeyError): return None


def you_track(samples, stab, abs_t, base_s=3.0, floor_s=0.6, dev_deg=4.0, proxy=None):
    """Where you are, at every time of `abs_t`, as (yaw, pitch) in radians in the world frame, or None. The detections come about once a second, far too seldom to follow a runner, but the camera is on a stick in your hand, so you are nearly FIXED in the camera's own (body) frame while the camera
    swings: each detection is turned into the body frame (with the camera's orientation of that moment, `stab`: 50 Hz), those are smoothed in time, and the smoothed body direction is turned back into the world with the orientation of every frame. The smoothing follows the motion: where you move about in the
    body frame (the detections around a sample disagree by `dev_deg` or more) the window shortens, down to `floor_s`; where you are steady it is `base_s` long. NaN where no detection is within 2.5 s."""
    from strata360.render.camera import direction
    s = sorted((x for x in samples), key=lambda x: x['t'])
    if len(s) < 2 or stab is None: return None
    ts = np.array([x['t'] for x in s]); vb = np.array([stab(x['t']) @ direction(np.radians(x['yaw']), np.radians(x['pitch'])) for x in s]); n = len(s)
    ang = lambda a, b: np.degrees(np.arccos(np.clip(np.sum(a * b, axis=-1), -1.0, 1.0)))
    dev = np.zeros(n); dev[1:-1] = ang(vb[:-2], vb[2:]) if n > 2 else 0.0
    if n > 2: dev[0], dev[-1] = dev[1], dev[-2]
    sig = np.clip(base_s / (1.0 + dev / dev_deg), floor_s, base_s); abs_t = np.asarray(abs_t, float)
    w = np.exp(-0.5 * ((abs_t[:, None] - ts[None, :]) / sig[None, :]) ** 2) / sig[None, :]; near = np.min(np.abs(abs_t[:, None] - ts[None, :]), axis=1) <= 2.5
    v = w @ vb; norm = np.linalg.norm(v, axis=1); ok = near & (norm > 1e-9); yaw = np.full(len(abs_t), np.nan); pitch = np.full(len(abs_t), np.nan)
    for i in np.flatnonzero(ok):
        d = stab(abs_t[i]).T @ (v[i] / norm[i]); yaw[i] = np.arctan2(d[0], d[1]); pitch[i] = np.arcsin(np.clip(d[2], -1.0, 1.0))
    if proxy is not None:                                                                                    # between the detections you are followed through the proxy video, frame by frame (analysis/subject_track.py): the body-frame estimate above, which cannot see your motion between detections, fills where there is no track
        from strata360.analysis import subject_track as ST
        try: tr = ST.window_track(proxy[0], proxy[1], float(abs_t[0]), float(abs_t[-1]), samples, cache_dir=proxy[2])
        except (OSError, ValueError, RuntimeError): tr = None
        if tr is not None:
            tt, ty, tp = tr; okk = np.isfinite(ty) & np.isfinite(tp)
            if okk.sum() >= 2:
                uy = np.degrees(np.unwrap(np.radians(ty[okk]))); inside = (abs_t >= tt[okk][0]) & (abs_t <= tt[okk][-1])
                dy = np.radians(np.interp(abs_t, tt[okk], uy)); dp = np.radians(np.interp(abs_t, tt[okk], tp[okk]))
                ref = np.where(np.isfinite(yaw), yaw, dy); dy = dy + 2 * np.pi * np.round((ref - dy) / (2 * np.pi))                       # onto the same turn as the estimate
                yaw = np.where(inside, dy, yaw); pitch = np.where(inside, dp, pitch)
    return yaw, pitch


def _face(samples, key, abs_t):
    """`key` of the you samples (the pitch of the face centre, or its yaw offset) at the times, interpolated between samples that have it; NaN where there is none within 2 s."""
    s = [(x['t'], x[key]) for x in samples if x.get(key) is not None]
    if not s: return np.full(len(abs_t), np.nan)
    ts = np.array([a for a, _ in s]); v = np.interp(abs_t, ts, [b for _, b in s]); far = np.array([np.min(np.abs(ts - t)) > 2.0 for t in abs_t]); v[far] = np.nan; return v


def _head(abs_t, ts, hd):
    """The pitch of the top of the head (degrees) at the times, interpolated between the samples where it is known; NaN where there is none within 2 s."""
    if hd is None or not np.isfinite(hd).any(): return np.full(len(abs_t), np.nan)
    ok = np.isfinite(hd); v = np.interp(abs_t, ts[ok], hd[ok]); far = np.array([np.min(np.abs(ts[ok] - t)) > 2.0 for t in abs_t]); v[far] = np.nan; return v


def _speaker(segs, t0, t1):
    w = {}
    for s in segs:
        o = min(t1, s['t1']) - max(t0, s['t0'])
        if o > 0 and s.get('label') in ('wearer', 'other'): w[s['label']] = w.get(s['label'], 0.0) + o
    if not w: return None
    k = max(w, key=w.get); return k if w[k] >= 0.3 * (t1 - t0) else None


def clip_data(folder, clip, head=False):
    from strata360.analysis import views
    d = os.path.join(config.race_dir(folder), 'clips', clip); cj = json.load(open(os.path.join(d, 'clip.json'))); osv = cj['source_files']['osv']
    sp = os.path.join(d, 'speakers.json')
    from strata360.analysis.exposure import load_quality
    out = dict(person=views.person_samples(d, osv), you=views.focus_samples(d, osv), heading=views.heading_fn(d, osv), speakers=json.load(open(sp))['segments'] if os.path.exists(sp) else [], quality=load_quality(d), views=CV.load(d, osv), stab=views.stab_fn(osv), proxy=_proxy_info(d) if os.environ.get('STRATA_YOU_KLT') == '1' else None, head=_head_provider(d, views.focus_samples(d, osv), head))          # the frame-by-frame tracker (analysis/subject_track.py) is opt-in: on 0021 it did not predict a held-out detection better than a straight line (the detections' box and face centres are themselves inexact)
    try: out['cameras'] = json.load(open(os.path.join(d, 'cameras.json'))).get('cameras') or []          # the clip's ranked cameras (edit/cameras.py): scenery and free views take their aim from them
    except (OSError, ValueError): out['cameras'] = []
    return out


def choose_subject(g, tech, data):
    """(subject, why) for one plan segment g with the technique object tech."""
    t0 = g['clip_start_s']; t1 = t0 + g['dur_s']
    if tech.id in NO_SUBJECT: return 'none', 'this technique has its own framing'
    cp, cy = _coverage(data['person'], t0, t1), _coverage(data['you'], t0, t1); who = _speaker(data['speakers'], t0, t1)
    if tech.id in YOU_VIEWS:
        what = {'selfie_hold': 'you, the wearer', 'selfie_close': 'you, close on the face', 'selfie_far': 'you, ultra wide: the whole body and the surroundings'}[tech.id]
        return (('you', what) if cy >= 0.3 else ('none', 'you are not found in this window: behind the runner'))
    if tech.id == 'person_hold': return (('person', 'another person, kept in view (the clip\'s person camera)') if cp >= 0.3 else ('heading', 'no other person is found in this window: straight ahead'))
    kind = g.get('kind')                                                                 # the candidate the window was cut from says how it is meant to be seen
    if kind == 'person' and cp >= 0.3: return 'person', 'this stretch was chosen for the people in view'
    if kind == 'you' and cy >= 0.3: return 'you', 'this stretch was chosen for you in view'
    if who == 'other' and cp >= 0.3: return 'person', 'another person is speaking'
    if who == 'wearer' and cy >= 0.3: return 'you', 'you are speaking'
    if tech.id in TIGHT:
        if cp >= 0.3: return 'person', 'a close framing on another person'
        if cy >= 0.3: return 'you', 'a close framing on you'
    elif cp >= 0.5: return 'person', 'another person is in view'
    return 'heading', 'straight ahead'


FREE_PITCHES = (-10.0, 0.0, 10.0)
FREE_HFOVS = (80.0, 100.0)


def scenery_path(g, T, t0, rng, v):
    """The scenery camera (edit/scenery.py) for the window: the best people-free view, panning slowly or cutting within its budget. None when the clip has no quality grid."""
    if not v or v.get('grid') is None: return None
    st = SC.Settings(); path = SC.track(v['grid'], t0, t0 + T, v['heading'], v['prior'], v['boxes'], st, rng); kf = SC.keyframes(path, T, st.pitch, st.hfov, t0=t0); cuts = len(path['jumps'])
    why = 'the best-looking scenery with nobody in view' + (f': {cuts} cut{"s" if cuts != 1 else ""} to a better direction' if cuts else ', held or panned slowly')
    return dict(ref='world', keyframes=kf, subject='scenery', why=why)


CAMERA_SLACK_S = 0.3         # a window may run this far outside a camera's stretch (windows are whole beats) and still take its aim


def camera_path(cams, kind, t0, T):
    """The aim of the best camera of `kind` ('scenery' or 'free') in the clip's camera list (edit/cameras.py) whose stretch holds the window of `T` seconds from clip second `t0`, cut to the window (times from 0, jumps kept, ends interpolated); None when no
    camera of that kind covers it, and the framing makes its own."""
    best = None
    for c in cams or []:
        kf = (c.get('aim') or {}).get('keyframes')
        if c.get('kind') == kind and kf and c['start_s'] - CAMERA_SLACK_S <= t0 and t0 + T <= c['end_s'] + CAMERA_SLACK_S and (best is None or c['score'] > best['score']): best = c
    if best is None: return None
    base = float(best['aim'].get('t0', best['start_s'])); kf = best['aim']['keyframes']; ts = np.array([base + k['t'] for k in kf]); a, b = t0, t0 + T
    def at(t): return {key: float(np.interp(t, ts, [k[key] for k in kf])) for key in ('yaw', 'pitch', 'fov')}
    pts = [(a, at(a))] + [(float(t), dict(yaw=k['yaw'], pitch=k['pitch'], fov=k['fov'])) for t, k in zip(ts, kf) if a < t < b] + [(b, at(b))]
    out = [dict(t=round(t - a, 3), yaw=round(v['yaw'], 2), pitch=round(v['pitch'], 2), fov=round(v['fov'], 1), ease='linear') for t, v in pts]
    return dict(ref='world', keyframes=out, subject=kind, why=f"camera {best['id']} of the clip's list (score {best['score']:.2f}): {best.get('why', '')}")


PAN_MIN_S = 3.0              # a free view of at least this long may pan between two poses
PAN_MAX_DEG = 60.0           # by at most this much yaw: a drift, not a sweep
PAN_KEEP = 0.85              # and only when both ends look at least this good compared with the best fixed view


def _best_pose(grid, a, b, rng, k=3, v=None):
    """The (score, yaw, pitch, hfov) of the view that looks best over [a, b], one of the top `k` picked at random (the seeded variety). With `v` (clip_views.load's dict) the look is weighted by the scenes stage's rating of that direction at the middle of the window,
    as the scenery camera does, so a close brick wall (all fine detail) does not beat a better-rated direction."""
    prior, heading = (v or {}).get('prior'), (v or {}).get('heading'); mid = (a + b) / 2.0
    def weight(yaw): return 1.0 if prior is None or heading is None else SC.Settings.prior_floor + (1 - SC.Settings.prior_floor) * prior(mid, float(SC.wrap(yaw - heading(mid))))
    best = [(VQ.window_score(grid, a, b, yaw, pitch, hfov, 16 / 9, step=1.0)['score'] * weight(yaw), yaw, pitch, hfov) for yaw in range(-180, 180, 15) for pitch in FREE_PITCHES for hfov in FREE_HFOVS]
    best.sort(reverse=True); return best[int(rng.integers(0, min(k, len(best))))]


def free_path(g, T, t0, rng, v):
    """A free camera (edit/view_quality.py): a fixed pose, the view that looks best over the whole window, or, in a window of 3 s or more, a slow pan from the best pose at its start to the best pose at its end when those are different (15 to 60 degrees apart) and
    each looks nearly as good as the fixed one; one of the top few at random (the seeded variety). People are not avoided. None without a quality grid."""
    if not v or v.get('grid') is None: return None
    grid = v['grid']; sc, yaw, pitch, hfov = _best_pose(grid, t0, t0 + T, rng, v=v); kf = lambda t, y, p, f: dict(t=round(float(t), 3), yaw=float(y), pitch=float(p), fov=float(f), ease='linear')
    if T >= PAN_MIN_S:
        win = min(1.5, T / 3.0); s0, y0, p0, f0 = _best_pose(grid, t0, t0 + win, rng, 1, v); s1, y1, p1, f1 = _best_pose(grid, t0 + T - win, t0 + T, rng, 1, v); d = abs(float(CV.wrap(y1 - y0)))
        if 15.0 <= d <= PAN_MAX_DEG and min(s0, s1) >= PAN_KEEP * sc:
            return dict(ref='world', keyframes=[kf(0.0, y0, p0, f0), kf(T, y0 + float(CV.wrap(y1 - y0)), p1, f1)], subject='free', why=f'a slow pan of {d:.0f} degrees between the best pose at the start and at the end (score {min(s0, s1):.2f})')
    return dict(ref='world', keyframes=[kf(0.0, yaw, pitch, hfov), kf(T, yaw, pitch, hfov)], subject='free', why=f'a fixed view chosen for its detail and exposure (score {sc:.2f})')


def cam_path(cam, t0, T, step=0.2):
    """The framing of a window of a point camera (edit/pointcam.py): its path over the clip's seconds `cam['t']` read from `t0` for `T` seconds, in the world frame (a pan between shots can glide to or from it like any other)."""
    times = np.arange(0.0, T + 1e-9, step); abs_t = t0 + times
    yaw, pitch, fov = (np.interp(abs_t, cam['t'], cam[k]) for k in ('yaw', 'pitch', 'fov'))
    kf = [dict(t=round(float(t), 3), yaw=round(float(y), 2), pitch=round(float(p), 2), fov=round(float(f), 1), ease='linear') for t, y, p, f in zip(times, yaw, pitch, fov)]
    return dict(ref='world', keyframes=kf, subject='camera', why=f"point camera {cam['id']}" + (f" ({cam['name']})" if cam.get('name') else '') + f": keeps the place in frame, {cam['min_dist_m']:.0f} m from the path at the closest")


def resolve_segment(g, lib, data):
    """The framing of one plan segment: dict(subject, why, path). Deterministic for the same plan and analysis (the window's variant seed drives the technique's choices)."""
    tid = g['technique']; tech = lib.get(tid) or (lib['hold_wide'] if tid.startswith('cam:') else lib[tid])                                   # (a point camera taken away since the plan was made: a plain wide shot)
    T = float(g['dur_s']); t0 = float(g['clip_start_s'])
    if tech.cam is not None: return cam_path(tech.cam, t0, T)
    subject, why = choose_subject(g, tech, data)
    rng = np.random.default_rng(int(g.get('variant_seed') or 0)); heading = data['heading']
    if tech.id in ('scenery', 'free_view'):
        made = camera_path(data.get('cameras'), 'scenery' if tech.id == 'scenery' else 'free', t0, T) or (scenery_path if tech.id == 'scenery' else free_path)(g, T, t0, rng, data.get('views'))
        if made is not None: return made
        why = 'there is no quality grid for this clip yet (the quality stage): looking straight ahead'; subject = 'heading'
    if subject in ('person', 'you'):
        ts, yw, pt, hh, hd = _track(data[subject], t0, t0 + T)
        tracking = subject == 'you' and tech.id in YOU_VIEWS and data.get('stab') is not None and len(ts) >= 2 and os.environ.get('STRATA_YOU_TRACK') != '0'          # follow you at the frame rate through the camera's own motion (you_track)
        times = np.arange(0.0, T + 1e-9, TRACK_STEP_S if tracking else STEP_S); abs_t = t0 + times
        if len(ts) >= 2: y = np.interp(abs_t, ts, yw); p = np.interp(abs_t, ts, pt); h = np.interp(abs_t, ts, hh); hdd = _head(abs_t, ts, hd)
        elif len(ts) == 1: y = np.full(len(times), yw[0]); p = np.full(len(times), pt[0]); h = np.full(len(times), hh[0]); hdd = _head(abs_t, ts, hd)
        else: subject = 'heading'
        y_plain = y.copy() if subject != 'heading' else None
        if subject == 'you' and tech.id == 'selfie_close':                                                  # sideways too: the centre of the face, not the middle of the body
            fdy = _face(data[subject], 'face_dyaw', abs_t); y = y + np.radians(np.where(np.isfinite(fdy), fdy, 0.0))
    if subject not in ('person', 'you'):
        look = heading(t0 + T / 2) if tech.id not in NO_SUBJECT else heading(t0); att = None
        if subject == 'heading' and tech.id not in NO_SUBJECT and data.get('quality') is not None:       # straight ahead, unless somewhere nearby clearly has more detail, contrast and colour (and the lens there is not the foggy one)
            att = AT.best_yaw_offset(data['quality'], t0, t0 + T, float(look)); look = float(look) + att['offset_deg']
        path = TQ.instantiate(tech, T, rng, look_yaw=float(look)); path['subject'] = subject; path['why'] = why + (f"; turned {att['offset_deg']:+.0f} deg: {att['why']}" if att and att['offset_deg'] else ''); return path
    look = float(np.degrees(y[0])); path = TQ.instantiate(tech, T, rng, look_yaw=look)
    if subject == 'you' and tech.id in YOU_VIEWS:                                                         # the views of you look where you ARE (world frame), not straight behind the runner: you are often to one side, and a close view would miss you
        fov = path['keyframes'][0]['fov']; path = dict(ref='world', keyframes=[dict(t=0.0, yaw=look, pitch=0.0, fov=fov), dict(t=round(T, 3), yaw=look, pitch=0.0, fov=fov)])
    if tech.id in FOLLOW:                                                   # the technique's own move (fov, slow drift) stays; the subject is followed: held while still, panned slowly when it drifts, one quick move when it goes far
        from strata360.render.camera import CameraPath
        ev = CameraPath(path['keyframes'], path.get('ref', 'world')).evaluate(times)
        ty = np.degrees(y); aimer = (lambda pi, hi, vf, hd: AIM.aim_face(pi, hi, hd)) if tech.id == 'selfie_close' else AIM.aim_pitch
        tp = np.array([aimer(float(np.degrees(p[i])), float(h[i]), AIM.vfov_deg(float(ev['fov'][i])), None if np.isnan(hdd[i]) else float(hdd[i])) for i in range(len(times))])
        if tech.id == 'dialogue_hold' and subject == 'you':                                                 # a talking shot is about the face, not the top of the head (the head-top aim above leaves the face at the bottom of the frame when you look down): the centre of the face, a little above the middle
            fp = _face(data[subject], 'face', abs_t); tp = np.where(np.isfinite(fp), fp - AIM.TALK_FACE_HIGH * np.array([AIM.vfov_deg(float(f)) for f in ev['fov']]), tp)
        if tech.id == 'selfie_close':                                                                    # the close view puts the CENTRE OF THE FACE (between the eyes and the nose) in the middle of the frame, where the detector found it; the head-top estimate is only the fallback
            fp = _face(data[subject], 'face', abs_t); tp = np.where(np.isfinite(fp), fp, tp)
        trk = you_track(data[subject], data.get('stab'), abs_t, proxy=data.get('proxy')) if tracking else None; tracked = False
        if trk is not None and np.isfinite(trk[0]).any():                                                      # tracked: you stay put in the frame while the camera swings; the head-room (or the face centre) is added as the slow offset it is
            yd, pd = trk; okt = np.isfinite(yd); yd = np.where(okt, yd, np.interp(times, times[okt], np.unwrap(yd[okt]))); pd = np.where(okt, pd, np.interp(times, times[okt], pd[okt]))
            fy = np.degrees(np.unwrap(yd)) + (np.degrees(y) - np.degrees(y_plain)); fp = np.degrees(pd) + (tp - np.degrees(p))
            fy, fp = gaussian_filter1d(fy, 0.12 / TRACK_STEP_S, mode='nearest'), gaussian_filter1d(fp, 0.12 / TRACK_STEP_S, mode='nearest'); tracked = True
            hd = data['head'](t0 - 0.5, t0 + T + 0.5) if data.get('head') else None                                    # the head found directly at the frame rate: a close view aims at it (eyes and nose in the middle); the others follow its FAST motion only (the calm aim above stays)
            if hd is not None:
                from strata360.analysis import head_track as HT
                hy, hp = HT.fill(hd[0], hd[1], hd[2]); okh = np.isfinite(hy) & np.isfinite(hp)
                if okh.sum() >= 10:
                    uy = np.degrees(np.unwrap(np.radians(hy[okh]))); iy = np.interp(abs_t, hd[0][okh], uy); ip = np.interp(abs_t, hd[0][okh], hp[okh]); cov = (abs_t >= hd[0][okh][0]) & (abs_t <= hd[0][okh][-1])
                    iy = iy + 360.0 * np.round((fy - iy) / 360.0)                                                      # onto the same turn as the calm aim
                    if tech.id == 'selfie_close': ny, npi = gaussian_filter1d(iy, 0.05 / TRACK_STEP_S, mode='nearest'), gaussian_filter1d(ip, 0.05 / TRACK_STEP_S, mode='nearest')          # 0.05 s: the head's own bobbing at running cadence (about 3 Hz) is followed
                    else:
                        w = HEAD_FAST_W.get(tech.id, 0.5); ny = fy + w * (iy - gaussian_filter1d(iy, 0.6 / TRACK_STEP_S, mode='nearest')); npi = fp + w * (ip - gaussian_filter1d(ip, 0.6 / TRACK_STEP_S, mode='nearest'))
                    fy = np.where(cov, ny, fy); fp = np.where(cov, npi, fp)            # a little: the detections' own noise
        else:
            fy, fp = AIM.follow(times, ty, tp, scale=min(1.0, float(np.mean(ev['fov'])) / 85.0))                                # a narrower view has a narrower dead band
            fy = np.degrees(np.unwrap(np.radians(fy)))
        kf = [dict(t=round(float(tt), 3), yaw=round(float(fy[i] if tracked else np.degrees(ev['yaw'][i]) + fy[i] - fy[0]), 2), pitch=round(float(np.clip(fp[i], -60, 60)), 2), fov=round(float(ev['fov'][i]), 1), ease='linear')
              for i, tt in enumerate(times)]
        path = dict(ref='world', keyframes=kf)
    path['subject'] = subject; path['why'] = why
    if subject in ('person', 'you'): path['track'] = [dict(t=round(float(t_), 3), yaw=round(float(np.degrees(y_)), 2), pitch=round(float(np.degrees(p_)), 2)) for t_, y_, p_ in zip(times, y, p)]       # where the subject is, for the pan transitions (edit/pans.py)
    return path


def resolve(folder, plan, lib=None, head=False):
    """Framing for every segment of a saved plan: {segment id: dict(subject, why, path)}."""
    lib = lib or TQ.with_cams(TQ.load(), folder); cache = {}; out = {}
    for g in plan['segments']:
        if g.get('synthetic'): continue                                                                 # a generated clip has no camera to frame
        if g['clip'] not in cache: cache[g['clip']] = clip_data(folder, g['clip'], head)
        out[g['id']] = resolve_segment(g, lib, cache[g['clip']])
    return out
