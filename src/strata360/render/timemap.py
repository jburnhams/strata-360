"""The time map of a film (implementation plan A2): which footage is on screen at every frame, written next to the final film as `timemap.json` and `timemap.csv`.

Per WINDOW of the plan: its first and last film frame, the clip and the source seconds it plays, and the UTC at its in and out points (a generated clip has no clip and no UTC of its own; its race time is in `race_utc`, when the plan carries one).
Per TRANSITION region (a dissolve, dip or whip is centred on the cut): the film frames it covers and both windows' source seconds and UTC at its two ends, since both pictures are on screen. The layout is render/film.layout's, so the frames are the ones the
renderer cuts the film into. `utc_at(timemap, frame)` answers "what time of the race is on screen at film frame f" (the incoming window after the middle of a transition)."""
import csv, datetime as dt, json, os

from strata360.render.film import layout
from strata360.render.final import ffmpeg_rate

COLUMNS = ['kind', 'index', 'film_in', 'film_out', 'clip', 'source_in_s', 'source_out_s', 'utc_in', 'utc_out', 'with_index', 'with_clip']


def _utc(s, add=0.0):
    if not s: return None
    t = dt.datetime.fromisoformat(s.replace('Z', '+00:00')) + dt.timedelta(seconds=add); return t.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'


def build(plan, fps):
    """The time map of `plan` rendered at `fps`: dict(fps, frames, windows, transitions)."""
    segs = plan['segments']; starts, n, half = layout(segs, fps); wins = []; trs = []
    for k, g in enumerate(segs):
        s0 = float(g.get('clip_start_s') or 0.0); dur = float(g['dur_s']); u0 = g.get('utc_start')
        wins.append(dict(index=k, id=g.get('id'), film_in=starts[k], film_out=starts[k] + n[k], clip=None if g.get('synthetic') else g.get('clip'), synthetic=bool(g.get('synthetic')), source_in_s=round(s0, 3), source_out_s=round(s0 + dur, 3), utc_in=u0, utc_out=g.get('utc_end') or _utc(u0, dur)))
    for k in range(1, len(segs)):
        h = half[k]
        if not h: continue
        a, b = wins[k - 1], wins[k]; cut = starts[k]; ha = h / fps; sa = float(segs[k - 1].get('clip_start_s') or 0.0) + (cut - starts[k - 1]) / fps; sb = float(segs[k].get('clip_start_s') or 0.0)
        trs.append(dict(index=k, type=segs[k]['transition']['type'], film_in=cut - h, film_out=cut + h, outgoing=dict(index=k - 1, clip=a['clip'], source_in_s=round(sa - ha, 3), source_out_s=round(sa + ha, 3), utc_in=_utc(a['utc_in'], sa - ha - a['source_in_s']) if a['utc_in'] else None, utc_out=_utc(a['utc_in'], sa + ha - a['source_in_s']) if a['utc_in'] else None),
                        incoming=dict(index=k, clip=b['clip'], source_in_s=round(sb - ha, 3), source_out_s=round(sb + ha, 3), utc_in=_utc(b['utc_in'], -ha) if b['utc_in'] else None, utc_out=_utc(b['utc_in'], ha) if b['utc_in'] else None)))
    return dict(fps=float(fps), fps_rational=ffmpeg_rate(fps), frames=starts[-1] + n[-1] if segs else 0, windows=wins, transitions=trs)


def utc_at(tm, frame):
    """The UTC (ISO string) on screen at film frame `frame`, or None where the window has none (a generated clip); inside a transition the outgoing window's before its middle, the incoming one's after."""
    for w in tm['windows']:
        if w['film_in'] <= frame < w['film_out']:
            if not w['utc_in']: return None
            return _utc(w['utc_in'], (frame - w['film_in']) / tm['fps'])
    return None


def write(plan, fps, directory):
    """Write timemap.json and timemap.csv into `directory`; returns the map."""
    tm = build(plan, fps); os.makedirs(directory, exist_ok=True); json.dump(tm, open(os.path.join(directory, 'timemap.json'), 'w'), indent=1)
    with open(os.path.join(directory, 'timemap.csv'), 'w', newline='') as f:
        w = csv.writer(f); w.writerow(COLUMNS)
        for x in tm['windows']: w.writerow(['window', x['index'], x['film_in'], x['film_out'], x['clip'] or '', x['source_in_s'], x['source_out_s'], x['utc_in'] or '', x['utc_out'] or '', '', ''])
        for t in tm['transitions']:
            for side, other in (('outgoing', 'incoming'), ('incoming', 'outgoing')):
                x = t[side]; w.writerow([t['type'] + '-' + side, x['index'], t['film_in'], t['film_out'], x['clip'] or '', x['source_in_s'], x['source_out_s'], x['utc_in'] or '', x['utc_out'] or '', t[other]['index'], t[other]['clip'] or ''])
    return tm
