"""The edit technique library (README 16.1): loading, validation, and turning a technique into a camera path.

`instantiate(technique, duration_s, rng, look_yaw)` returns the JSON dict that `strata360.render.camera.CameraPath` and the renderer accept
(keyframes with yaw, pitch, roll, fov, dist, disc). Variants (direction, turns, background) come from the seeded generator, so a seed
reproduces an edit exactly."""
import json, os
from dataclasses import dataclass, field

HERE = os.path.dirname(os.path.abspath(__file__))
CLOSE_FOV = 58.0              # the views of you: close (a face zoom, pulled back a little from 50 so the face has room), mid (selfie_hold, 85) and far (ultra wide)
FAR_FOV = 130.0
FEATURES = {'steady', 'clear_nadir', 'open_ground', 'canopy', 'subject', 'speech', 'protagonist', 'low_obstruction', 'resolution', 'you_close', 'you_far', 'scenery_ok', 'free_ok'}


@dataclass
class Technique:
    id: str; family: str; dur: tuple; energy: float; hero: bool; max_share: float; cooldown: int; max_consecutive: int; max_uses: int
    beats: str; dialogue_ok: bool; scale: str; needs: dict = field(default_factory=dict)
    cam: dict = None                      # a point camera (edit/pointcam.py): the clip it is on and its path over the clip's seconds; the technique is only for windows inside that stretch

    @property
    def dmin(self): return self.dur[0]
    @property
    def dideal(self): return self.dur[1]
    @property
    def dmax(self): return self.dur[2]


def load(path=None):
    d = json.load(open(path or os.path.join(HERE, 'techniques.json')))
    out = {}
    for t in d['techniques']:
        t = dict(t); t['dur'] = tuple(t['dur']); t['needs'] = {k: tuple(v) for k, v in t.get('needs', {}).items()}
        out[t['id']] = Technique(**t)
    validate(out)
    return out


CAM_MIN_S, CAM_IDEAL_S, CAM_MAX_S = 2.0, 5.0, 16.0       # how long a window of a point camera may be (the stretch itself is the other limit)


def with_cams(lib, folder):
    """The library plus a technique `cam:C1` for each point camera on a clip that is offered as possible (edit/pointcam_clip.cutins): the planner may cut to it in a window that lies inside the stretch the camera covers, and the framing gives the window the camera's path.
    The library itself is not changed; a project with no cameras (or none that work) gets it back as it is."""
    from strata360.edit import pointcam_clip as PCL
    try: cams = PCL.cutins(folder)
    except (OSError, ValueError, KeyError): return lib
    out = dict(lib)
    for c in cams:
        span = c['t1'] - c['t0']
        if span < CAM_MIN_S: continue
        tid = f"cam:{c['id']}"; out[tid] = Technique(id=tid, family='pointcam', dur=(CAM_MIN_S, min(CAM_IDEAL_S, span), min(CAM_MAX_S, span)), energy=0.5, hero=False, max_share=0.3, cooldown=0, max_consecutive=1, max_uses=2, beats='beat', dialogue_ok=False, scale='medium', needs={}, cam=c)
    return out


def validate(lib):
    """Every record must be complete and consistent (README P5-24)."""
    for t in lib.values():
        assert len(t.dur) == 3 and 0 < t.dur[0] <= t.dur[1] <= t.dur[2], (t.id, 'duration range')
        assert 0.0 <= t.energy <= 1.0 and 0 < t.max_share <= 1.0 and t.cooldown >= 0 and t.max_consecutive >= 1 and t.max_uses >= 1, t.id
        assert t.beats in ('beat', 'bar') and t.scale in ('wide', 'medium', 'tight'), t.id
        for f, (w, thr) in t.needs.items():
            assert f in FEATURES and w > 0 and (thr is None or 0 <= thr <= 1), (t.id, f)
        if t.hero: assert t.cooldown >= 3 and t.max_share <= 0.2, (t.id, 'hero effects must be rare')
        if t.dialogue_ok: assert not t.hero, (t.id, 'no showy effects on dialogue')
    return True


def _sign(rng): return 1 if rng.random() < 0.5 else -1


def instantiate(t, dur, rng, look_yaw=0.0):
    """Camera path (dict for CameraPath.from_json) for technique `t` lasting `dur` seconds. `look_yaw` is where a steady framing looks (world frame)."""
    k = lambda time, **kw: dict(t=round(time, 3), **kw)
    T = float(dur); s = _sign(rng); fam = t.id
    if fam == 'hold_wide': return dict(ref='world', keyframes=[k(0, yaw=look_yaw, pitch=0, fov=100), k(T, yaw=look_yaw, pitch=0, fov=100)])
    if fam == 'selfie_hold': return dict(ref='body', keyframes=[k(0, yaw=180, pitch=0, fov=85), k(T, yaw=180, pitch=0, fov=85)])
    if fam in ('scenery', 'free_view'): return dict(ref='world', keyframes=[k(0, yaw=look_yaw, pitch=0, fov=100), k(T, yaw=look_yaw, pitch=0, fov=100)])      # (the framing replaces this with the camera the scenery engine or the view search found)
    if fam == 'selfie_close': return dict(ref='body', keyframes=[k(0, yaw=180, pitch=0, fov=CLOSE_FOV), k(T, yaw=180, pitch=0, fov=CLOSE_FOV)])        # you, the face: a zoom centred on the head
    if fam == 'selfie_far': return dict(ref='body', keyframes=[k(0, yaw=180, pitch=0, fov=FAR_FOV), k(T, yaw=180, pitch=0, fov=FAR_FOV)])           # you, ultra wide: the whole body and the surroundings
    if fam == 'follow_runner': return dict(ref='heading', heading=dict(tau_s=2.0), keyframes=[k(0, yaw=0, pitch=-3, fov=95), k(T, yaw=0, pitch=-3, fov=95)])
    if fam == 'pan_reveal':
        a = rng.uniform(40, 90) * s; return dict(ref='world', keyframes=[k(0, yaw=look_yaw - a / 2, pitch=2, fov=92), k(T, yaw=look_yaw + a / 2, pitch=2, fov=92)])
    if fam == 'whip_pan': return dict(ref='world', keyframes=[k(0, yaw=look_yaw, pitch=0, fov=100, ease='smooth'), k(T, yaw=look_yaw + s * 140, pitch=0, fov=100)])
    if fam == 'push_in': return dict(ref='world', keyframes=[k(0, yaw=look_yaw, pitch=0, fov=100), k(T, yaw=look_yaw, pitch=0, fov=65)])
    if fam == 'pull_out': return dict(ref='world', keyframes=[k(0, yaw=look_yaw, pitch=0, fov=65), k(T, yaw=look_yaw, pitch=0, fov=100)])
    if fam == 'look_around': return dict(ref='world', keyframes=[k(0, yaw=look_yaw, pitch=0, fov=100), k(T, yaw=look_yaw + s * 180, pitch=0, fov=100)])
    if fam == 'spin_roll': return dict(ref='world', keyframes=[k(0, yaw=look_yaw, pitch=0, roll=0, fov=100, ease='smooth'), k(T, yaw=look_yaw, pitch=0, roll=s * 360.0, fov=100)])     # one full turn of image roll
    if fam == 'planet_fill':
        turns = float(rng.choice([0.5, 1.0, 1.5])); return dict(ref='world', keyframes=[k(0, yaw=look_yaw, pitch=-90, fov=260, dist=1.0), k(T, yaw=look_yaw + s * 360 * turns, pitch=-90, fov=260, dist=1.0)])
    if fam == 'planet_globe':
        bg = 'blur' if rng.random() < 0.6 else [round(float(x), 2) for x in (0.06, 0.07, 0.14)]
        return dict(ref='world', bg=bg, keyframes=[k(0, yaw=look_yaw, pitch=-90, disc=3.2), k(min(T * 0.45, 1.6), yaw=look_yaw + s * 120, pitch=-90, disc=0.46), k(T, yaw=look_yaw + s * 300, pitch=-90, disc=0.46)])
    if fam == 'planet_fill_zoom_out': return dict(ref='world', keyframes=[k(0, yaw=look_yaw, pitch=-90, fov=260, dist=1.0), k(T, yaw=look_yaw + s * 120, pitch=-8, fov=95, dist=0.0)])
    if fam == 'globe_shrink': return dict(ref='world', bg='blur', keyframes=[k(0, yaw=look_yaw, pitch=-90, disc=3.2), k(T, yaw=look_yaw + s * 90, pitch=-90, disc=0.46)])
    if fam == 'tunnel_up': turns = float(rng.choice([0.5, 1.0])); return dict(ref='world', keyframes=[k(0, yaw=look_yaw, pitch=90, fov=260, dist=1.0), k(T, yaw=look_yaw + s * 360 * turns, pitch=90, fov=260, dist=1.0)])
    if fam == 'person_hold': return dict(ref='world', keyframes=[k(0, yaw=look_yaw, pitch=0, fov=75), k(T, yaw=look_yaw, pitch=0, fov=75)])        # another person: the framing aims it at them
    if fam == 'dialogue_hold': return dict(ref='world', keyframes=[k(0, yaw=look_yaw, pitch=0, fov=70), k(T, yaw=look_yaw, pitch=0, fov=68)])
    raise KeyError(t.id)
