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
