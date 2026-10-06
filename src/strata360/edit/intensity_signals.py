"""The signals for the intensity curve (G1, docs/ai-music.md 4.1), gathered from a project's film plan and what was found in the footage, in film time.

  gather(folder) -> dict(length_s, signals=[{name, t, v, weight}], marks=[(film s, level, span)], speech=[(t0, t1)], used=[names]) or None when there is no plan
  signals_from(segments, motion, events, series, step_s=1.0) -> the same, from loaded data (pure; what the tests use)

Per plan segment, sampled every step_s of film time: the wearer's motion energy (`motion.json`, clip time), cheering, shouting, laughter and crowd in the clip's sound (`audio_events.json`), pace (faster is more intense), climb (steeper is more intense, either way) and heart rate from the race track (UTC), and the technique's own energy (the plan's `energy`). A signal the project lacks is left out and listed in `used` only if present. Story weight: the film's start and finish are marked full. Speech: segments that carry the runner's own speech or a voice-over line (the music is sparser under them)."""
import datetime as dt, json, os
import numpy as np

CROWD = ('cheering', 'shouting', 'laughter', 'crowd'); WEIGHTS = dict(motion=1.0, crowd=2.0, pace=1.0, climb=1.0, heart=1.0, technique=1.0)


def _utc(s):
    try: return dt.datetime.fromisoformat(s.replace('Z', '+00:00')).timestamp()
    except (ValueError, AttributeError): return None


def _crowd(doc, t0, t1):
    from strata360.analysis import sound_events as SE
    c = SE.scores_between(doc, t0, t1); return max([c.get(k, 0.0) for k in CROWD] or [0.0]) if c else float('nan')


def signals_from(segments, motion=None, events=None, series=None, step_s=1.0):
    """segments: the plan's segments in film order. motion(clip) -> motion.json dict | None; events(clip) -> audio_events.json dict | None; series: object with .at(utc seconds array) -> dict of arrays, or None."""
    acc = {k: ([], []) for k in WEIGHTS}; speech = []; length = 0.0
    for sg in segments:
        t0 = float(sg['film_start_s']); d = float(sg['dur_s']); length = max(length, t0 + d)
        if sg.get('speech') or sg.get('role') == 'vo': speech.append((t0, t0 + d))
        ts = t0 + np.arange(step_s / 2, d, step_s) if d > step_s else np.array([t0 + d / 2]); rel = ts - t0 + float(sg.get('clip_start_s') or 0.0)
        acc['technique'][0].extend(ts); acc['technique'][1].extend([float(sg.get('energy', 0.5))] * len(ts))
        m = motion(sg['clip']) if motion and sg.get('clip') and not sg.get('synthetic') else None
        if m and m.get('series', {}).get('t'): acc['motion'][0].extend(ts); acc['motion'][1].extend(np.interp(rel, m['series']['t'], m['series']['acc_energy'], right=np.nan))
        ev = events(sg['clip']) if events and sg.get('clip') and not sg.get('synthetic') else None
        if ev and ev.get('windows'): acc['crowd'][0].extend(ts); acc['crowd'][1].extend([_crowd(ev, r - step_s / 2, r + step_s / 2) for r in rel])
        u0 = _utc(sg.get('utc_start', ''))
        if series is not None and u0 is not None:
            a = series.at(u0 + (ts - t0))
            with np.errstate(invalid='ignore'):
                for name, v in (('pace', np.where(np.asarray(a['pace_s_km'], float) > 0, 1.0 / np.asarray(a['pace_s_km'], float), np.nan)), ('climb', np.abs(np.asarray(a['slope_pct'], float))), ('heart', np.asarray(a['hr'], float))):
                    acc[name][0].extend(ts); acc[name][1].extend(v)
    sigs = []
    for name, (t, v) in acc.items():
        v = np.asarray(v, float); ok = np.isfinite(v)
        if ok.sum() >= 2 and np.ptp(v[ok]) > 1e-9: sigs.append(dict(name=name, t=np.asarray(t, float)[ok].tolist(), v=v[ok].tolist(), weight=WEIGHTS[name]))
    return dict(length_s=round(length, 3), signals=sigs, marks=[(0.0, 1.0, 0.0), (length, 1.0, 0.0)] if length else [], speech=speech, used=[s['name'] for s in sigs])


def gather(folder):
    from strata360.edit import project as PJ
    from strata360.pipeline import config
    plan = PJ.load(folder).get('plan'); segs = (plan or {}).get('segments') or []
    if not segs: return None
    rd = config.race_dir(folder); cache = {}

    def load(clip, name):
        k = (clip, name)
        if k not in cache:
            try: cache[k] = json.load(open(os.path.join(rd, 'clips', clip, name)))
            except (OSError, ValueError): cache[k] = None
        return cache[k]
    series = None
    try:
        from strata360.overlay import _series
        p = config.track_path(folder, config.load(folder) if os.path.exists(os.path.join(rd, 'race.json')) else None)
        if p: series = _series(p, os.path.getmtime(p))
    except Exception: series = None                                     # no track, or one the overlay cannot read: the other signals still count
    return signals_from(segs, lambda c: load(c, 'motion.json'), lambda c: load(c, 'audio_events.json'), series)


_CACHE = {}


def cached(folder):
    """gather(folder), kept until the film plan file changes (the studio asks on every poll)."""
    from strata360.edit import project as PJ
    try: key = os.path.getmtime(PJ._path(folder))
    except OSError: return None
    hit = _CACHE.get(folder)
    if not hit or hit[0] != key: _CACHE[folder] = hit = (key, gather(folder))
    return hit[1]
