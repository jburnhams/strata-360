"""Self-calibrating scale for the VLM's scenery scores (implementation plan K1): a winter ultra scores 5 and 6 nearly everywhere, a sunny race would reach 8 and 9, so shots are ranked on a
0 to 10 scale fitted to the range of THIS project's scores. The raw score stays beside it: absolute judgements (a bad moment, comparing races) use the raw one.

fit(raw) -> dict(lo, hi, ...): the 10th and 95th percentile of all the project's scores, widened around the median to at least `min_spread` raw points, so a uniformly mediocre race is not stretched into 0..10.
apply(scale, raw) -> 0..10 (linear between lo and hi, clipped)."""
import numpy as np

LO_PCT, HI_PCT, MIN_SPREAD = 10.0, 95.0, 2.0


def fit(raw, lo_pct=LO_PCT, hi_pct=HI_PCT, min_spread=MIN_SPREAD):
    v = np.asarray([x for x in raw if x is not None and np.isfinite(x)], float)
    if len(v) == 0: return dict(lo=0.0, hi=10.0, n=0, widened=False, lo_pct=lo_pct, hi_pct=hi_pct)                    # nothing to fit: the identity scale
    lo, hi = float(np.percentile(v, lo_pct)), float(np.percentile(v, hi_pct)); widened = hi - lo < min_spread
    if widened: mid = float(np.median(v)); lo, hi = mid - min_spread / 2, mid + min_spread / 2
    return dict(lo=round(lo, 3), hi=round(hi, 3), n=int(len(v)), widened=bool(widened), lo_pct=lo_pct, hi_pct=hi_pct)


def apply(scale, raw):
    a = np.asarray(raw, float); out = np.clip((a - scale['lo']) / max(scale['hi'] - scale['lo'], 1e-9), 0.0, 1.0) * 10.0
    return float(out) if a.ndim == 0 else out


def front_scores(scenes):
    """The raw scenery scores (1 to 10, people ignored) of the front views in one clip's scenes.json (`scenery`, scenes stage v3); [] for an older file or none."""
    return [float(i['scenery']) for i in (scenes or {}).get('items') or [] if i.get('view') == 'front' and isinstance(i.get('scenery'), (int, float))]


def project_scale(clips_dir):
    """The scale of a whole project: fitted to the front scenery scores of every clip's scenes.json under `clips_dir` (the race dir's `clips`). The identity scale (0 to 10) when there are none, so a project that has not run scenes v3 is unchanged."""
    import json, os
    raw = []
    try: names = sorted(os.listdir(clips_dir))
    except OSError: names = []
    for n in names:
        try: raw += front_scores(json.load(open(os.path.join(clips_dir, n, 'scenes.json'))))
        except (OSError, ValueError): pass
    return fit(raw)


def look(scenes, scale):
    """{ahead, behind, clarity_ahead, clarity_behind}: a clip's picture quality from its scenes.json: the mean scenery of the front and of the rear views on the project's 0..10 scale, and the mean clarity (1 to 5); None where there is nothing."""
    out = {}
    for view, key in (('front', 'ahead'), ('rear', 'behind')):
        v = [float(i['scenery']) for i in (scenes or {}).get('items') or [] if i.get('view') == view and isinstance(i.get('scenery'), (int, float))]
        c = [float(i['clarity']) for i in (scenes or {}).get('items') or [] if i.get('view') == view and isinstance(i.get('clarity'), (int, float))]
        out[key] = round(float(apply(scale, np.mean(v))), 1) if v else None; out['clarity_' + key] = round(float(np.mean(c)), 1) if c else None
    return out if any(x is not None for x in out.values()) else None
