"""Pan transitions: instead of a hard cut between two shots of the SAME clip that follow each other in time, the camera glides from where the first shot ends to where the second begins (the first half of the glide is the end of the first shot, the second half the start of the second, so the footage is exactly what a hard cut there would show; only the camera moves through the cut).

A glide is allowed only when it is gentle and keeps the people in shot:
  * the shots are consecutive in the clip (the second starts within 0.6 s of where the first ends) and both are world-frame cameras (the views of you, a person, scenery, free views; not the runner-heading follow or the body-frame framings);
  * the move is small (at most 55 degrees of yaw, 20 of pitch, 65 of field of view: a mid to far or mid to close change of view of you is a gentle pull out or push in) and slow (at most 80 degrees a second of yaw and 80 of field of view; it takes 0.6 to 1.2 s, never more than 0.4 of either shot), and big enough to matter (a cut between nearly the same pose is not a cut);
  * the subject of the first shot (you, a person) stays in view for the WHOLE glide, and the subject of the second from the middle of it on: in view means inside 0.42 of the half field of view of the camera pose at that moment.
Anything else stays a hard cut. The pans are worked out when the film is rendered, from the plan and the framing (`apply_pans`), so the saved plan is unchanged; set STRATA_NO_PANS=1 to turn them off."""
import math, os

import numpy as np

MAX_YAW, MAX_PITCH, MAX_FOV = 55.0, 20.0, 65.0
MAX_SPEED = 80.0                # degrees a second of yaw at its fastest
MAX_ZOOM_RATE = 80.0            # degrees of field of view a second
MIN_MOVE = 6.0
LOOK = 0.42
MIN_S, MAX_S, SHARE = 0.6, 1.2, 0.4
CONTIGUOUS_S = 0.6          # the second shot starts within this many seconds of where the first ends (windows are whole beats, so a cut inside a talking stretch overlaps by a few tenths)
ASPECT = 16 / 9
SAMPLES = 9


def wrap(a): return (np.asarray(a, float) + 180.0) % 360.0 - 180.0


def smooth(u): return u * u * (3 - 2 * u)


def vfov(fov): return math.degrees(2 * math.atan(math.tan(math.radians(fov) / 2) / ASPECT))


def is_globe(kf): return any('disc' in k for k in kf)


def pose_at(kf, t):
    """(yaw, pitch, fov, z) of a keyframe list at window time t (held before the first and after the last keyframe; yaw as written, continuous). `z` is how much of the view the frame shows, on the globe's scale (1 / disc radius; a flat view of field of view f has z = f in radians / 2 pi), so a globe shot and a flat one can be glided between;
    a globe key has no field of view of its own (it is the equivalent one)."""
    ts = [k['t'] for k in kf]; fovs = [k['fov'] if 'fov' in k else math.degrees(2 * math.pi * k['disc'] ** -1.0) for k in kf]; zs = [1.0 / k['disc'] if 'disc' in k else math.radians(k['fov']) / (2 * math.pi) for k in kf]
    return (float(np.interp(t, ts, [k['yaw'] for k in kf])), float(np.interp(t, ts, [k['pitch'] for k in kf])), float(np.interp(t, ts, fovs)), float(np.interp(t, ts, zs)))


def subject_at(track, t):
    """(yaw, pitch) of the subject at window time t from a track [{t, yaw, pitch}] (held at the ends; yaw interpolated the short way)."""
    ts = [x['t'] for x in track]; y = np.degrees(np.unwrap(np.radians([x['yaw'] for x in track])))
    return float(np.interp(t, ts, y)), float(np.interp(t, ts, [x['pitch'] for x in track]))


GLOBE_MAX_YAW, GLOBE_MAX_PITCH, GLOBE_S = 180.0, 100.0, 1.4      # looking straight down a turn of yaw is only a spin of the picture, so any is allowed; the camera lifts up to the horizon while the globe opens (or closes)


def globe_plan(da, db, dyaw, dp, path_a, path_b):
    """The glide between a globe (little planet) shot and a flat one: the whole sphere widens (or closes) to the flat view while the camera turns. Nothing to keep in view: the globe shows everything and the flat end is the shot itself."""
    if abs(dyaw) > GLOBE_MAX_YAW or abs(dp) > GLOBE_MAX_PITCH: return None, f'too big a turn for a globe ({abs(dyaw):.0f} degrees of yaw, {abs(dp):.0f} of pitch)'
    D = min(GLOBE_S, SHARE * min(da, db))
    if D < MIN_S - 1e-9: return None, 'the shots are too short for a glide'
    return dict(type='pan', beats=0, dur_s=round(D, 3), globe=True, why='a glide between the globe and the flat view', a_dur=da, a_kf=path_a['keyframes'], b_kf=path_b['keyframes']), None


def plan(seg_a, seg_b, path_a, path_b, look=None):
    """(transition dict, None) when a glide from the end of shot a to the start of shot b is allowed, else (None, the reason). `look(yaw, pitch, hfov, clip_time)` (optional) scores what a view shows (0 to about 1, edit/view_quality.py); the glide is refused when its middle looks much worse than its ends (mostly sky or flat ground)."""
    if path_a.get('ref') != 'world' or path_b.get('ref') != 'world': return None, 'not both world-frame cameras'
    if seg_a['clip'] != seg_b['clip'] or abs(seg_b['clip_start_s'] - (seg_a['clip_start_s'] + seg_a['dur_s'])) > CONTIGUOUS_S: return None, 'the shots are not consecutive in the clip'
    globe = is_globe(path_a['keyframes']) or is_globe(path_b['keyframes'])
    da, db = float(seg_a['dur_s']), float(seg_b['dur_s']); A, B = pose_at(path_a['keyframes'], da), pose_at(path_b['keyframes'], 0.0); dyaw = float(wrap(B[0] - A[0])); dp = B[1] - A[1]; df = B[2] - A[2]
    if globe:
        res, why = globe_plan(da, db, dyaw, dp, path_a, path_b)
        if res is None: return res, why
        return judge(res, seg_a, path_a, path_b, look)
    if abs(dyaw) > MAX_YAW or abs(dp) > MAX_PITCH or abs(df) > MAX_FOV: return None, f'too big a move ({abs(dyaw):.0f} degrees of yaw, {abs(dp):.0f} of pitch, {abs(df):.0f} of field of view)'
    if abs(dyaw) + abs(dp) + abs(df) / 3.0 < MIN_MOVE: return None, 'the two shots already look the same way'
    D = min(max(MIN_S + abs(dyaw) / MAX_YAW * (MAX_S - MIN_S), MIN_S + abs(df) / MAX_FOV * (MAX_S - MIN_S), MIN_S), MAX_S, SHARE * min(da, db))
    if D < MIN_S - 1e-9: return None, 'the shots are too short for a glide'
    if 1.5 * abs(dyaw) / D > MAX_SPEED or 1.5 * abs(df) / D > MAX_ZOOM_RATE: return None, 'the move would be too fast'
    for who, path, upto in (('first', path_a, 0.0), ('second', path_b, 0.5)):
        track = path.get('track')
        if path.get('subject') not in ('you', 'person'): continue
        if not track: return None, f'the {who} shot has no track of its subject to keep in view'
        for i in range(SAMPLES):
            u = i / (SAMPLES - 1)
            if u < upto: continue
            ta, tb = da - D / 2 + u * D, -D / 2 + u * D; pa, pb = pose_at(path_a['keyframes'], ta), pose_at(path_b['keyframes'], max(tb, 0.0)); s = smooth(u)
            py, pp, pf = pa[0] + s * float(wrap(pb[0] - pa[0])), pa[1] + s * (pb[1] - pa[1]), pa[2] + s * (pb[2] - pa[2])
            sy, sp = subject_at(track, ta if who == 'first' else max(tb, 0.0))
            if abs(float(wrap(sy - py))) > LOOK * pf or abs(sp - pp) > LOOK * vfov(pf): return None, f'the {who} shot\'s {path["subject"]} would leave the frame'
    return judge(dict(type='pan', beats=0, dur_s=round(D, 3), why=f'a glide of {abs(dyaw):.0f} degrees keeping the subject in view', a_dur=da, a_kf=path_a['keyframes'], b_kf=path_b['keyframes']), seg_a, path_a, path_b, look)


LOOK_SAMPLES = 7
LOOK_MEAN, LOOK_MIN = 0.6, 0.3      # the middle of a glide must score at least this share of the worse end on average, and no sample below the second share of it (a glide through mostly sky is refused)


def judge(res, seg_a, path_a, path_b, look):
    """Check what the glide shows on the way: the view at samples through it is scored (`look`) and must not be much worse than the two ends. Returns (transition with its `look` score, None) or (None, the reason)."""
    if look is None: return res, None
    da, D = res['a_dur'], res['dur_s']; t0 = seg_a['clip_start_s']; A, B = pose_at(path_a['keyframes'], da), pose_at(path_b['keyframes'], 0.0); rows = []
    for i in range(LOOK_SAMPLES):
        u = i / (LOOK_SAMPLES - 1); s = smooth(u); ta = da - D / 2 + u * D; pa = pose_at(path_a['keyframes'], ta); pb = pose_at(path_b['keyframes'], max(-D / 2 + u * D, 0.0)); y = pa[0] + s * float(wrap(pb[0] - pa[0])); pitch = pa[1] + s * (pb[1] - pa[1])
        z = pa[3] + s * (pb[3] - pa[3]) if res.get('globe') else None; hfov = min(math.degrees(2 * math.pi * z), 130.0) if z is not None else pa[2] + s * (pb[2] - pa[2])
        rows.append(look(y, pitch, hfov, t0 + ta))
    if any(r is None for r in rows): return res, None
    ends = min(rows[0], rows[-1]); mid = rows[1:-1]
    if ends > 0 and (float(np.mean(mid)) < LOOK_MEAN * ends or min(mid) < LOOK_MIN * ends): return None, f'the glide would show mostly poor views (score {np.mean(mid):.2f} against {ends:.2f} at its ends)'
    return dict(res, look=round(float(np.mean(rows)), 3)), None


def looker(folder):
    """A `look(seg, yaw, pitch, hfov, clip_time)` for `apply_pans`: the score of a view of a clip from its quality grid (None when the clip has none)."""
    from strata360.pipeline import config
    from strata360.analysis import quality_grid as QG
    from strata360.edit import view_quality as VQ
    cache = {}
    def look(seg, yaw, pitch, hfov, t):
        c = seg['clip']
        if c not in cache: cache[c] = QG.load(os.path.join(config.race_dir(folder), 'clips', c))
        g = cache[c]
        return None if g is None else VQ.view_score(g, round(t * g['hz']), yaw, pitch, hfov, 16 / 9)['score']
    return look


def apply_pans(segs, framing, enabled=None, scorer=None):
    """Copies of the plan's windows in which each hard cut inside one clip that can be a glide is one (`transition` type 'pan'), with the report [(window id, glide or reason)]. Cuts the user fixed (`your choice`) and cuts with an effect are left as they are."""
    if enabled is None: enabled = not os.environ.get('STRATA_NO_PANS')
    out = [dict(g, transition=dict(g.get('transition') or {})) for g in segs]; report = []
    if not enabled: return out, report
    for k in range(1, len(out)):
        tr = out[k]['transition']; g, p = out[k], out[k - 1]
        if tr.get('type', 'cut') != 'cut' or not str(tr.get('why', '')).startswith('the same clip') or g.get('synthetic') or p.get('synthetic'): continue
        a, b = framing.get(p['id']), framing.get(g['id'])
        if not a or not b: continue
        res, why = plan(p, g, a, b, (lambda y, pi, f, t: scorer(p, y, pi, f, t)) if scorer else None); report.append((g['id'], res['why'] if res else why))
        if res: out[k]['transition'] = res
    return out, report
