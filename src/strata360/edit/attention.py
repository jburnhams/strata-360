"""Where on the sphere there is something worth looking at, from the clip's view-quality maps (analysis/exposure.py `quality_for`, once a second): used to nudge a "straight ahead" framing toward the part of
the view with more detail, contrast and colour, and away from a fogged or wet lens.

For a window [t0, t1] the maps of that stretch are averaged; every cell scores by how its detail, contrast and colour rank among the covered cells of the frame (0..1); cells served mostly by a lens that holds
clearly less detail than the other (a fogged or wet lens) are discounted. A view is the cells inside the camera's field of view around a candidate direction; the best direction within `MAX_OFFSET_DEG` of the
heading wins, with a small pull toward the heading so the view only moves when it gains something clear (`MIN_GAIN`). Yaw only: the vertical aim stays the technique's.
Maps are in the stabilised world frame: columns lon -180..+180, rows from north to south, as the camera paths."""
import numpy as np

MAX_OFFSET_DEG = 60.0
HEADING_PULL = 0.15            # score lost at the largest offset, so a tie stays on the heading
MIN_GAIN = 0.06                # the best view must beat the heading's by this much (0..1 scores) to be worth moving to
HFOV_DEG = 90.0; PITCH_BAND = (-30.0, 20.0)        # the view's window: this wide, between these latitudes
BAD_LENS_FACTOR = 0.6; LENS_DEFICIT = 0.3           # a cell mostly seen by the lens with less than this share of the detail is scored x factor


def _rank(a, ok):
    """Rank of each covered cell among the covered cells (0..1); NaN stays NaN."""
    out = np.full(a.shape, np.nan, np.float32); v = a[ok]
    if v.size: out[ok] = (np.argsort(np.argsort(v)).astype(np.float32) / max(v.size - 1, 1))
    return out


def score_map(vq, t0, t1):
    """The (rows, cols) attention score (0..1, NaN where uncovered) averaged over the maps with t0 - 1 <= t <= t1 + 1 (the nearest map when none is in range), and the lens detail share (master, 0..1)."""
    t = vq['t']; sel = (t >= t0 - 1.0) & (t <= t1 + 1.0)
    if not sel.any(): sel = np.zeros(len(t), bool); sel[int(np.argmin(np.abs(t - 0.5 * (t0 + t1))))] = True
    sc = []
    for i in np.flatnonzero(sel):
        det, con, chr_ = (vq[k][i].astype(np.float32) for k in ('detail', 'contrast', 'chroma')); ok = np.isfinite(det) & np.isfinite(con) & np.isfinite(chr_)
        s = 0.5 * _rank(det, ok) + 0.3 * _rank(con, ok) + 0.2 * _rank(chr_, ok); share = vq['share'][i].astype(np.float32); lens = float(vq['lens_detail_share_master'][i])
        if np.isfinite(lens) and abs(lens - 0.5) > LENS_DEFICIT / 2:                  # one lens holds clearly less detail: discount the cells it mostly supplies
            bad_master = lens < 0.5; mostly = share > 0.65 if bad_master else share < 0.35; s = np.where(mostly, s * BAD_LENS_FACTOR, s)
        sc.append(s)
    lens_share = np.nanmedian(vq['lens_detail_share_master'][sel]) if np.isfinite(vq['lens_detail_share_master'][sel]).any() else float('nan')
    return np.nanmean(np.stack(sc), axis=0), float(lens_share)


def best_yaw_offset(vq, t0, t1, heading_deg):
    """dict(offset_deg, gain, why): how far from the heading (degrees, positive right) the view with the most to look at is, and by how much it beats looking along the heading. offset_deg is 0 unless the gain is clear."""
    S, lens_share = score_map(vq, t0, t1); gh, gw = S.shape; cell = 360.0 / gw
    rows = [r for r in range(gh) if PITCH_BAND[0] <= 90.0 - (r + 0.5) * 180.0 / gh <= PITCH_BAND[1]]; half = int(round(HFOV_DEG / 2 / cell)); c0 = int(round(((heading_deg + 180.0) % 360.0) / cell - 0.5))
    def view(k):
        cols = [(c0 + k + j) % gw for j in range(-half, half + 1)]; return float(np.nanmean(S[np.ix_(rows, cols)]))
    ks = range(-int(MAX_OFFSET_DEG / cell), int(MAX_OFFSET_DEG / cell) + 1); base = view(0); scores = {k: view(k) - HEADING_PULL * abs(k) * cell / MAX_OFFSET_DEG for k in ks}
    k = max(scores, key=scores.get); gain = view(k) - base
    if k == 0 or not np.isfinite(gain) or gain < MIN_GAIN: return dict(offset_deg=0.0, gain=0.0 if not np.isfinite(gain) else round(max(gain, 0.0), 3), why='straight ahead is as good as anywhere')
    return dict(offset_deg=round(k * cell, 1), gain=round(gain, 3), why=f'more detail and colour {abs(k) * cell:.0f} deg to the {"right" if k > 0 else "left"}' + (' (and away from the foggier lens)' if np.isfinite(lens_share) and abs(lens_share - 0.5) > LENS_DEFICIT / 2 else ''))


def clarity_samples(vq, pitches=(-20.0, 0.0, 20.0)):
    """The clearest view over time for the player's "Clarity" mode: once per quality map {t, yaw (world degrees 0..360), pitch, score}: the direction, anywhere on the sphere, whose field of view holds the most
    detail, contrast and colour (the score map of `score_map` over t +- 1 s, so one map does not make the view jump about; a foggy lens's cells are discounted), at a pitch of -20, 0 or +20 degrees."""
    out = []; gh, gw = vq['detail'].shape[1:]; cell = 360.0 / gw; half = int(round(HFOV_DEG / 2 / cell))
    for t in vq['t']:
        S, _ = score_map(vq, float(t), float(t)); best = None
        for p in pitches:
            rows = [r for r in range(gh) if abs(90.0 - (r + 0.5) * 180.0 / gh - p) <= 25.0]
            for c in range(gw):
                v = float(np.nanmean(S[np.ix_(rows, [(c + j) % gw for j in range(-half, half + 1)])]))
                if np.isfinite(v) and (best is None or v > best[0]): best = (v, c, p)
        if best: out.append(dict(t=round(float(t), 2), yaw=round(((best[1] + 0.5) * cell) % 360.0, 1), pitch=best[2], score=round(best[0], 3)))
    return out
