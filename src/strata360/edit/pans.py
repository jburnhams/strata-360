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


def pose_at(kf, t):
    """(yaw, pitch, fov) of a keyframe list at window time t (held before the first and after the last keyframe; yaw as written, continuous)."""
    ts = [k['t'] for k in kf]; return tuple(float(np.interp(t, ts, [k[n] for k in kf])) for n in ('yaw', 'pitch', 'fov'))


def subject_at(track, t):
    """(yaw, pitch) of the subject at window time t from a track [{t, yaw, pitch}] (held at the ends; yaw interpolated the short way)."""
    ts = [x['t'] for x in track]; y = np.degrees(np.unwrap(np.radians([x['yaw'] for x in track])))
    return float(np.interp(t, ts, y)), float(np.interp(t, ts, [x['pitch'] for x in track]))


def plan(seg_a, seg_b, path_a, path_b):
    """(transition dict, None) when a glide from the end of shot a to the start of shot b is allowed, else (None, the reason)."""
    if path_a.get('ref') != 'world' or path_b.get('ref') != 'world': return None, 'not both world-frame cameras'
    if seg_a['clip'] != seg_b['clip'] or abs(seg_b['clip_start_s'] - (seg_a['clip_start_s'] + seg_a['dur_s'])) > CONTIGUOUS_S: return None, 'the shots are not consecutive in the clip'
    if any('fov' not in x for x in path_a['keyframes'] + path_b['keyframes']): return None, 'a globe or little-planet shot has no field of view to glide between'
    da, db = float(seg_a['dur_s']), float(seg_b['dur_s']); A, B = pose_at(path_a['keyframes'], da), pose_at(path_b['keyframes'], 0.0); dyaw = float(wrap(B[0] - A[0])); dp = B[1] - A[1]; df = B[2] - A[2]
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
    return dict(type='pan', beats=0, dur_s=round(D, 3), why=f'a glide of {abs(dyaw):.0f} degrees keeping the subject in view', a_dur=da, a_kf=path_a['keyframes'], b_kf=path_b['keyframes']), None


def apply_pans(segs, framing, enabled=None):
    """Copies of the plan's windows in which each hard cut inside one clip that can be a glide is one (`transition` type 'pan'), with the report [(window id, glide or reason)]. Cuts the user fixed (`your choice`) and cuts with an effect are left as they are."""
    if enabled is None: enabled = not os.environ.get('STRATA_NO_PANS')
    out = [dict(g, transition=dict(g.get('transition') or {})) for g in segs]; report = []
    if not enabled: return out, report
    for k in range(1, len(out)):
        tr = out[k]['transition']; g, p = out[k], out[k - 1]
        if tr.get('type', 'cut') != 'cut' or not str(tr.get('why', '')).startswith('the same clip') or g.get('synthetic') or p.get('synthetic'): continue
        a, b = framing.get(p['id']), framing.get(g['id'])
        if not a or not b: continue
        res, why = plan(p, g, a, b); report.append((g['id'], res['why'] if res else why))
        if res: out[k]['transition'] = res
    return out, report
