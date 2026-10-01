"""Framing: for every window of the plan, where the camera looks and how it moves.

The plan says which part of which clip and which technique (hold, push in, pan ...). This adds the subject: who or what the technique is aimed at, from the analysis of the clip.

  the candidate's view   a stretch chosen for other people in view is framed on them, one chosen for you on you
  speech in the window   the speaker: another person while another voice talks, you (the wearer) while you talk
  tight techniques       (push in, dialogue hold): another person if one is in view, else you
  everything else        straight ahead (the runner's heading), unless another person is in view most of the time
  selfie hold            you (the wearer), or straight behind the runner when you are not found
  globe / spin / follow  no subject (planets look down, follow runner follows the heading)

A subject is followed: the camera path gets the subject's yaw over time added (smoothed), so a person walking across the view stays framed. Output is the dict
CameraPath.from_json takes: world frame, yaw in degrees, keyframes every half second (window-relative seconds), plus `subject` and `why` for the GUI.
Nothing here needs the video: only identity.json / speakers.json / motion.json of the clip (analysis/views.py samples)."""
import json, os
import numpy as np
from scipy.ndimage import gaussian_filter1d
from strata360.pipeline import config
from strata360.edit import techniques as TQ

FOLLOW = {'hold_wide', 'dialogue_hold', 'push_in', 'pull_out', 'selfie_hold'}          # techniques that keep their subject in frame as it moves
NO_SUBJECT = {'follow_runner', 'planet_fill', 'planet_globe', 'planet_fill_zoom_out', 'globe_shrink', 'tunnel_up', 'spin_roll'}
TIGHT = {'push_in', 'dialogue_hold'}
STEP_S = 0.5


def _coverage(samples, t0, t1):
    """Fraction of the window's seconds that have a sample within 1.5 s."""
    if not samples: return 0.0
    ts = np.array([s['t'] for s in samples]); grid = np.arange(t0, t1 + 1e-9, 1.0) if t1 > t0 else np.array([t0])
    return float(np.mean([np.min(np.abs(ts - g)) <= 1.5 for g in grid]))


def _track(samples, t0, t1):
    """(times, yaw unwrapped radians, pitch radians) of the samples in and around the window."""
    s = [x for x in samples if t0 - 2.0 <= x['t'] <= t1 + 2.0]
    return np.array([x['t'] for x in s]), np.unwrap(np.radians([x['yaw'] for x in s])), np.radians([x['pitch'] for x in s])


def _speaker(segs, t0, t1):
    w = {}
    for s in segs:
        o = min(t1, s['t1']) - max(t0, s['t0'])
        if o > 0 and s.get('label') in ('wearer', 'other'): w[s['label']] = w.get(s['label'], 0.0) + o
    if not w: return None
    k = max(w, key=w.get); return k if w[k] >= 0.3 * (t1 - t0) else None


def clip_data(folder, clip):
    from strata360.analysis import views
    d = os.path.join(config.race_dir(folder), 'clips', clip); cj = json.load(open(os.path.join(d, 'clip.json'))); osv = cj['source_files']['osv']
    sp = os.path.join(d, 'speakers.json')
    return dict(person=views.person_samples(d, osv), you=views.focus_samples(d, osv), heading=views.heading_fn(d, osv), speakers=json.load(open(sp))['segments'] if os.path.exists(sp) else [])


def choose_subject(g, tech, data):
    """(subject, why) for one plan segment g with the technique object tech."""
    t0 = g['clip_start_s']; t1 = t0 + g['dur_s']
    if tech.id in NO_SUBJECT: return 'none', 'this technique has its own framing'
    cp, cy = _coverage(data['person'], t0, t1), _coverage(data['you'], t0, t1); who = _speaker(data['speakers'], t0, t1)
    if tech.id == 'selfie_hold': return ('you', 'you, the wearer') if cy >= 0.3 else ('none', 'you are not found in this window: behind the runner')
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


def resolve_segment(g, lib, data):
    """The framing of one plan segment: dict(subject, why, path). Deterministic for the same plan and analysis (the window's variant seed drives the technique's choices)."""
    tech = lib[g['technique']]; subject, why = choose_subject(g, tech, data); T = float(g['dur_s']); t0 = float(g['clip_start_s'])
    rng = np.random.default_rng(int(g.get('variant_seed') or 0)); heading = data['heading']
    if subject in ('person', 'you'):
        ts, yw, pt = _track(data[subject], t0, t0 + T)
        times = np.arange(0.0, T + 1e-9, STEP_S); abs_t = t0 + times
        if len(ts) >= 2: y = np.interp(abs_t, ts, yw); p = np.interp(abs_t, ts, pt)
        elif len(ts) == 1: y = np.full(len(times), yw[0]); p = np.full(len(times), pt[0])
        else: subject = 'heading'
    if subject not in ('person', 'you'):
        look = heading(t0 + T / 2) if tech.id not in NO_SUBJECT else heading(t0)
        path = TQ.instantiate(tech, T, rng, look_yaw=float(look)); path['subject'] = subject; path['why'] = why; return path
    y = gaussian_filter1d(y, 1.0 / STEP_S, mode='nearest'); p = gaussian_filter1d(p, 1.0 / STEP_S, mode='nearest')
    look = float(np.degrees(y[0])); path = TQ.instantiate(tech, T, rng, look_yaw=look)
    if tech.id in FOLLOW:                                                   # the technique's own move (fov, slow drift) stays; the subject's motion is added
        from strata360.render.camera import CameraPath
        ev = CameraPath(path['keyframes'], path.get('ref', 'world')).evaluate(times)
        kf = [dict(t=round(float(tt), 3), yaw=round(float(np.degrees(ev['yaw'][i]) + np.degrees(y[i] - y[0])), 2), pitch=round(float(np.clip(np.degrees(p[i]) * 0.6, -35, 35)), 2), fov=round(float(ev['fov'][i]), 1), ease='linear')
              for i, tt in enumerate(times)]
        path = dict(ref='world', keyframes=kf)
    path['subject'] = subject; path['why'] = why; return path


def resolve(folder, plan, lib=None):
    """Framing for every segment of a saved plan: {segment id: dict(subject, why, path)}."""
    lib = lib or TQ.load(); cache = {}; out = {}
    for g in plan['segments']:
        if g['clip'] not in cache: cache[g['clip']] = clip_data(folder, g['clip'])
        out[g['id']] = resolve_segment(g, lib, cache[g['clip']])
    return out
