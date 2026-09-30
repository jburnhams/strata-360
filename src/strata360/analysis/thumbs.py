"""Clip thumbnails, in two passes.

quick  (`thumb` stage, needs only motion): the steadiest moment in the middle of the clip, straight ahead. Available as soon as the fast stages are done, so the clip list has pictures early.
best   (`thumb_best` stage, after candidates, identity and scenes): the most attractive moment of the best candidate (quality, scenic score, wearer or people in shot, steadiness), looking
       ahead, or behind at the wearer when their face is clearly there. Replaces the quick one (`thumb.jpg` is served in preference to `thumb_quick.jpg`).

Both write a flat, upright 16:9 view (960x540) and a small json saying how it was chosen."""
import json, os
import numpy as np


def _load(d, n):
    p = os.path.join(d, n)
    return json.load(open(p)) if os.path.exists(p) else None


def quick(osv, d):
    from strata360.analysis import views as V
    mo = _load(d, 'motion.json'); clip = _load(d, 'clip.json'); dur = clip['video']['source_frames'] / clip['video']['nominal_fps']; t = 0.5 * dur
    if mo:
        ts = np.array(mo['series']['t']); steady = np.exp(-np.array(mo['series']['shake_dps']) / 25.0); score = steady - 0.6 * np.abs(ts - 0.5 * dur) / max(dur, 1.0); m = (ts > 0.1 * dur) & (ts < 0.9 * dur)
        if m.any(): t = float(ts[m][np.argmax(score[m])])
    open(os.path.join(d, 'thumb_quick.jpg'), 'wb').write(V.render_thumb(osv, t, yaw=0.0, hfov=95.0))
    info = dict(kind='quick', t_s=round(t, 2), yaw=0.0, why='steadiest moment near the middle, looking ahead'); json.dump(info, open(os.path.join(d, 'thumb_quick.json'), 'w')); return info


def best(osv, d):
    from strata360.analysis import views as V
    cd = _load(d, 'candidates.json'); idn = _load(d, 'identity.json'); sc = _load(d, 'scenes.json'); mo = _load(d, 'motion.json')
    if not cd or not cd['candidates']: return quick(osv, d)
    def interest(c):
        f = c['features']; return 0.5 * c['quality'] + 0.25 * f.get('subject', 0) + 0.25 * f.get('protagonist', 0) + 0.1 * (1 if f.get('speech') else 0) - 0.3 * f.get('chatter', 0)
    c = max(cd['candidates'], key=interest); a, b = c['start_s'], c['end_s']
    ts = np.arange(a + 0.5, b, 0.5) if b - a > 1 else np.array([0.5 * (a + b)]); score = np.zeros(len(ts)); why = []
    if mo: score += np.interp(ts, mo['series']['t'], np.exp(-np.array(mo['series']['shake_dps']) / 25.0))
    yaw_pref = np.zeros(len(ts))
    if sc:
        fr = [i for i in sc['items'] if i['ok'] and i['view'] == 'front' and isinstance(i.get('scenic'), (int, float))]
        if fr: score += 0.8 * np.interp(ts, [i['t_s'] for i in fr], [float(i['scenic']) for i in fr])
    if idn and idn['samples']:
        me = [(r['t_s'], 1.0 if (r['me'] and r['me']['how'] == 'face') else 0.0) for r in idn['samples']]; m = np.interp(ts, [x[0] for x in me], [x[1] for x in me]); score += 0.6 * m; yaw_pref = m
    k = int(np.argmax(score)); t = float(ts[k]); yaw = 180.0 if yaw_pref[k] > 0.6 else 0.0
    open(os.path.join(d, 'thumb.jpg'), 'wb').write(V.render_thumb(osv, t, yaw=yaw, pitch=-8.0 if yaw == 180.0 else 0.0, hfov=85.0 if yaw == 180.0 else 95.0))
    info = dict(kind='best', t_s=round(t, 2), yaw=yaw, candidate=c['id'], why=f"best candidate ({c['id'].split('#')[-1]}), most attractive second" + (', the wearer clearly in view' if yaw == 180.0 else ', looking ahead'))
    json.dump(info, open(os.path.join(d, 'thumb.json'), 'w')); return info
