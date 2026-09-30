"""Clip thumbnails, in two passes.

quick  (`thumb` stage, needs only motion): the steadiest moment in the middle of the clip, straight ahead. Available as soon as the fast stages are done, so the clip list has pictures early.
best   (`thumb_best` stage, after candidates, identity and scenes): the most attractive moment of the best candidate (quality, scenic score, wearer or people in shot, steadiness), looking
       ahead, or behind at the wearer when their face is clearly there. Replaces the quick one (`thumb.jpg` is served in preference to `thumb_quick.jpg`).

Both write a flat, upright 16:9 view (960x540) and a small json saying how it was chosen."""
import json, math, os
import numpy as np

MAX_HFOV = 105.0     # widest horizontal field of view used: a rectilinear picture stretches towards its corners by 1/cos(angle)^2, about 3.2x in the corners at 105 degrees
AHEAD_HFOV = 100.0   # looking ahead: as wide as is comfortable, so the picture is not magnified beyond the source resolution and shows as much as possible
MIN_HFOV = 80.0
ASPECT = 16 / 9


def corner_stretch(hfov):
    """How much a rectilinear picture of this horizontal field of view stretches at its corners (radial, 1 = none)."""
    t = math.tan(math.radians(hfov) / 2) * math.sqrt(1 + (1 / ASPECT) ** 2); return 1 + t * t


def fov_for_person(height_deg, margin=0.85):
    """(hfov, why) for a picture that shows the whole person: their angular height should take at most `margin` of the frame height. Favours a wide view (source resolution, natural look)
    but never wider than MAX_HFOV; if the body would not fit inside that, the widest allowed view is used and the person is centred slightly higher so the head stays in."""
    v = min(height_deg / margin, 170.0); need = math.degrees(2 * math.atan(math.tan(math.radians(v) / 2) * ASPECT))
    if need > MAX_HFOV: return MAX_HFOV, f"body {height_deg:.0f} deg tall would need {need:.0f} deg across: capped at {MAX_HFOV:.0f} to limit distortion (some of the body is cropped)"
    hf = max(need, MIN_HFOV); return hf, f"body {height_deg:.0f} deg tall: {hf:.0f} deg across so the whole body fits with margin" + (f" (never narrower than {MIN_HFOV:.0f})" if hf > need else '')


def _load(d, n):
    p = os.path.join(d, n)
    return json.load(open(p)) if os.path.exists(p) else None


def quick(osv, d):
    from strata360.analysis import views as V
    mo = _load(d, 'motion.json'); clip = _load(d, 'clip.json'); dur = clip['video']['source_frames'] / clip['video']['nominal_fps']; t = 0.5 * dur
    if mo:
        ts = np.array(mo['series']['t']); steady = np.exp(-np.array(mo['series']['shake_dps']) / 25.0); score = steady - 0.6 * np.abs(ts - 0.5 * dur) / max(dur, 1.0); m = (ts > 0.1 * dur) & (ts < 0.9 * dur)
        if m.any(): t = float(ts[m][np.argmax(score[m])])
    open(os.path.join(d, 'thumb_quick.jpg'), 'wb').write(V.render_thumb(osv, t, yaw=0.0, hfov=AHEAD_HFOV))
    info = dict(kind='quick', t_s=round(t, 2), yaw=0.0, fov=AHEAD_HFOV, corner_stretch=round(corner_stretch(AHEAD_HFOV), 2), why='steadiest moment near the middle, looking ahead, wide view'); json.dump(info, open(os.path.join(d, 'thumb_quick.json'), 'w')); return info


def best(osv, d):
    from strata360.analysis import views as V
    cd = _load(d, 'candidates.json'); idn = _load(d, 'identity.json'); sc = _load(d, 'scenes.json'); mo = _load(d, 'motion.json')
    if not cd or not cd['candidates']: return quick(osv, d)
    def interest(c):
        f = c['features']; return 0.5 * c['quality'] + 0.25 * f.get('subject', 0) + 0.25 * f.get('protagonist', 0) + 0.1 * (1 if f.get('speech') else 0) - 0.3 * f.get('chatter', 0)
    c = max(cd['candidates'], key=interest); a, b = c['start_s'], c['end_s']
    ts = np.arange(a + 0.5, b, 0.5) if b - a > 1 else np.array([0.5 * (a + b)])
    # the wearer's face samples inside the candidate (heading-relative direction measured on the same stabilised views): the thumbnail must LOOK AT them, at the sample's own time
    faces = [r for r in (idn['samples'] if idn else []) if r['me'] and r['me']['how'] == 'face' and a <= r['t_s'] <= b]
    ts = np.unique(np.r_[ts, [r['t_s'] for r in faces]]); score = np.zeros(len(ts))
    if mo: score += np.interp(ts, mo['series']['t'], np.exp(-np.array(mo['series']['shake_dps']) / 25.0))
    if sc:
        fr = [i for i in sc['items'] if i['ok'] and i['view'] == 'front' and isinstance(i.get('scenic'), (int, float))]
        if fr: score += 0.8 * np.interp(ts, [i['t_s'] for i in fr], [float(i['scenic']) for i in fr])
    by_t = {round(r['t_s'], 2): r for r in faces}
    for k, t in enumerate(ts):
        r = by_t.get(round(float(t), 2))
        if r: score += np.where(np.arange(len(ts)) == k, 0.6 + 0.3 * float(r['me']['sim'] or 0), 0.0)               # a clearly recognised face beats a merely pretty view
    k = int(np.argmax(score)); t = float(ts[k]); r = by_t.get(round(t, 2))
    if r:
        yaw, pitch = float(r['me']['yaw']), float(r['me']['pitch']); ph = float(r['me'].get('height_deg') or 60.0); hfov, fwhy = fov_for_person(ph)
        if hfov >= MAX_HFOV and ph / 0.85 > 2 * math.degrees(math.atan(math.tan(math.radians(hfov) / 2) / ASPECT)): pitch += 0.12 * ph      # the body does not fit: keep the head in by aiming a little higher
        open(os.path.join(d, 'thumb.jpg'), 'wb').write(V.render_thumb(osv, t, yaw=yaw, pitch=pitch, hfov=hfov))
        info = dict(kind='best', t_s=round(t, 2), yaw=round(yaw, 1), pitch=round(pitch, 1), fov=round(hfov, 1), corner_stretch=round(corner_stretch(hfov), 2), candidate=c['id'],
                    why=f"best candidate ({c['id'].split('#')[-1]}), looking at you (face recognised, similarity {r['me']['sim']:.2f}); {fwhy}")
    else:
        open(os.path.join(d, 'thumb.jpg'), 'wb').write(V.render_thumb(osv, t, yaw=0.0, pitch=0.0, hfov=AHEAD_HFOV))
        info = dict(kind='best', t_s=round(t, 2), yaw=0.0, pitch=0.0, fov=AHEAD_HFOV, corner_stretch=round(corner_stretch(AHEAD_HFOV), 2), candidate=c['id'], why=f"best candidate ({c['id'].split('#')[-1]}), most attractive second, looking ahead, wide view")
    json.dump(info, open(os.path.join(d, 'thumb.json'), 'w')); return info
