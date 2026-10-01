"""Clip thumbnails, in two passes.

quick  (`thumb` stage, needs only motion): the steadiest moment in the middle of the clip, straight ahead. Available as soon as the fast stages are done, so the clip list has pictures early.
best   (`thumb_best` stage, after candidates, identity and scenes): the most attractive moment of the best candidate (quality, scenic score, wearer or people in shot, steadiness), looking
       ahead, or behind at the wearer when their face is clearly there. Replaces the quick one (`thumb.jpg` is served in preference to `thumb_quick.jpg`).

Both write a flat, upright 16:9 view (960x540) and a small json saying how it was chosen.

with_overlay  (`thumb_overlay` stage, when there is a race track): the current thumbnail with the race overlay drawn as it will be in the film, at the thumbnail's own moment.
       A new quick or best thumbnail removes it, so it is redone."""
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


def _thumb(osv, d, t, yaw, pitch, hfov):
    """JPEG bytes of the view: cut from the clip's proxy when it exists (seconds), else rendered from the lens streams (slow)."""
    from strata360.analysis import views as V
    proxy = os.path.join(d, 'proxy.mp4')
    if V.proxy_available(proxy): return V.render_thumb_proxy(proxy, osv, t, yaw=yaw, pitch=pitch, hfov=hfov)
    return V.render_thumb(osv, t, yaw=yaw, pitch=pitch, hfov=hfov)


def _drop_overlay(d):
    for n in ('thumb_overlay.jpg', 'thumb_overlay.json'):
        p = os.path.join(d, n)
        if os.path.exists(p): os.remove(p)


def current(d):
    """(file name, info) of the thumbnail the app shows: the best one when there is one, else the quick one; (None, None) without a thumbnail."""
    for n in ('thumb', 'thumb_quick'):
        if os.path.exists(os.path.join(d, n + '.jpg')): return n + '.jpg', _load(d, n + '.json') or {}
    return None, None


def with_overlay(d, cfg, track, tiles=None):
    """Write thumb_overlay.jpg: the current thumbnail with the race overlay at its moment. Without a map key the maps are left out (the numbers and clock are still drawn)."""
    import datetime as dt
    from PIL import Image
    from strata360.overlay import build
    from strata360.overlay.tiles import MissingKey
    name, info = current(d)
    if not name: raise RuntimeError('no thumbnail yet')
    clip = _load(d, 'clip.json'); t_s = float(info.get('t_s', 0.0)); t = dt.datetime.fromisoformat(clip['time']['start_utc'].replace('Z', '+00:00')).timestamp() + t_s
    img = np.asarray(Image.open(os.path.join(d, name)).convert('RGB')).copy(); size = (img.shape[1], img.shape[0]); why = None
    try: ov = build(cfg, track, size, tiles)
    except MissingKey as e: ov = build(cfg, track, size, tiles, maps=False); why = f'maps left out: {e}'
    Image.fromarray(ov.apply(img, t)).save(os.path.join(d, 'thumb_overlay.jpg.part'), 'JPEG', quality=90); os.replace(os.path.join(d, 'thumb_overlay.jpg.part'), os.path.join(d, 'thumb_overlay.jpg'))
    out = dict(source=name, source_mtime=os.path.getmtime(os.path.join(d, name)), t_s=round(t_s, 2), utc=dt.datetime.fromtimestamp(t, dt.timezone.utc).isoformat(), maps=why is None, why=why)
    json.dump(out, open(os.path.join(d, 'thumb_overlay.json'), 'w')); return out


def overlay_fresh(d):
    """Whether thumb_overlay.jpg was made from the thumbnail shown now."""
    o = _load(d, 'thumb_overlay.json'); name, _ = current(d)
    return bool(o and name and o.get('source') == name and os.path.exists(os.path.join(d, 'thumb_overlay.jpg')) and abs(os.path.getmtime(os.path.join(d, name)) - o.get('source_mtime', 0)) < 1e-3)


def quick(osv, d):
    from strata360.analysis import views as V
    mo = _load(d, 'motion.json'); clip = _load(d, 'clip.json'); dur = clip['video']['source_frames'] / clip['video']['nominal_fps']; t = 0.5 * dur
    if mo:
        ts = np.array(mo['series']['t']); steady = np.exp(-np.array(mo['series']['shake_dps']) / 25.0); score = steady - 0.6 * np.abs(ts - 0.5 * dur) / max(dur, 1.0); m = (ts > 0.1 * dur) & (ts < 0.9 * dur)
        if m.any(): t = float(ts[m][np.argmax(score[m])])
    open(os.path.join(d, 'thumb_quick.jpg'), 'wb').write(_thumb(osv, d, t, 0.0, 0.0, AHEAD_HFOV)); _drop_overlay(d)
    info = dict(kind='quick', t_s=round(t, 2), yaw=0.0, fov=AHEAD_HFOV, corner_stretch=round(corner_stretch(AHEAD_HFOV), 2), why='steadiest moment near the middle, looking ahead, wide view'); json.dump(info, open(os.path.join(d, 'thumb_quick.json'), 'w')); return info


def best(osv, d):
    from strata360.analysis import views as V
    cd = _load(d, 'candidates.json'); idn = _load(d, 'identity.json'); sc = _load(d, 'scenes.json'); mo = _load(d, 'motion.json')
    if not cd or not cd['candidates']: return quick(osv, d)
    def interest(c):
        f = c['features']; return 0.5 * c['quality'] + 0.25 * f.get('subject', 0) + 0.25 * f.get('protagonist', 0) + 0.1 * (1 if f.get('speech') else 0) - 0.3 * f.get('chatter', 0)
    c = max(cd['candidates'], key=interest); a, b = c['start_s'], c['end_s']; _drop_overlay(d)
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
        open(os.path.join(d, 'thumb.jpg'), 'wb').write(_thumb(osv, d, t, yaw, pitch, hfov))
        info = dict(kind='best', t_s=round(t, 2), yaw=round(yaw, 1), pitch=round(pitch, 1), fov=round(hfov, 1), corner_stretch=round(corner_stretch(hfov), 2), candidate=c['id'],
                    why=f"best candidate ({c['id'].split('#')[-1]}), looking at you (face recognised, similarity {r['me']['sim']:.2f}); {fwhy}")
    else:
        open(os.path.join(d, 'thumb.jpg'), 'wb').write(_thumb(osv, d, t, 0.0, 0.0, AHEAD_HFOV))
        info = dict(kind='best', t_s=round(t, 2), yaw=0.0, pitch=0.0, fov=AHEAD_HFOV, corner_stretch=round(corner_stretch(AHEAD_HFOV), 2), candidate=c['id'], why=f"best candidate ({c['id'].split('#')[-1]}), most attractive second, looking ahead, wide view")
    json.dump(info, open(os.path.join(d, 'thumb.json'), 'w')); return info
