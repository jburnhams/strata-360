"""Transitions between the windows of the plan: one per cut, chosen by rule (and overridable per window in the GUI).

  cut       nothing: the next shot simply starts (the default, and always inside one clip: adjacent selections of a clip differ by technique, not by effect)
  dissolve  a cross-fade centred on the cut: time has passed, or the mood changes
  dip       through black: a long gap in the day (hours later) or a new day
  whip      a fast pan away and in, with motion blur, hidden cut in the middle: between two energetic shots on a bar line

A transition is centred on the cut and lasts `beats` beats of the music (so it sits on the beat): the outgoing shot runs on for half of it past the end of its window and the incoming one starts
half of it before its window (both use the footage next to the window; at the ends of a clip the first/last frame is held). The film keeps its length; the first half of the incoming window and the
last half of the outgoing one are shown inside the blend. Rules: the transition must fit (at most half of either neighbouring window), whips are rare (at most 15% of the cuts, never two in a row) and
two non-cut transitions never follow each other directly."""
import datetime as dt

TYPES = ('cut', 'dissolve', 'dip', 'whip')
LENGTH = {'dissolve': 1, 'dip': 2, 'whip': 1}            # beats
WHIP_SHARE = 0.15


def _t(s): return dt.datetime.fromisoformat(s.replace('Z', '+00:00'))


def choose(segs, beat_s, bar_beats=4, forced=None, seed_energy=None):
    """segs: plan segment dicts in film order (clip, utc_start, utc_end, dur_s, start_beat, beats, energy?). forced: {window id: type} overrides. Sets seg['transition'] = dict(type, beats, dur_s, why)
    for every segment (the first one is always a cut-in). Returns segs."""
    forced = forced or {}; prev_type = 'cut'; whips = 0; n = max(len(segs) - 1, 1)
    for k, g in enumerate(segs):
        tr = dict(type='cut', beats=0, dur_s=0.0, why='the first shot' if k == 0 else 'the same clip: a new view, not an effect')
        if k > 0:
            p = segs[k - 1]; gap = (_t(g['utc_start']) - _t(p['utc_end'])).total_seconds() if g['clip'] != p['clip'] else 0.0
            room = 0.5 * min(p['dur_s'], g['dur_s']); want = None; why = tr['why']
            if g['id'] in forced: want, why = forced[g['id']], 'your choice'
            elif g['clip'] != p['clip']:
                if gap > 6 * 3600: want, why = 'dip', f'{gap / 3600:.0f} h later'
                elif gap > 1200: want, why = 'dissolve', f'{gap / 60:.0f} min later'
                elif g.get('energy_hi') and p.get('energy_hi') and g['start_beat'] % bar_beats == 0 and whips < WHIP_SHARE * n: want, why = 'whip', 'two energetic shots, on the bar'
            if want in (None, 'cut'): want = 'cut'
            else:
                beats = LENGTH[want]
                if g['id'] not in forced and (prev_type != 'cut' or want == 'whip' and prev_type == 'whip'): want, why = 'cut', 'the previous cut already has an effect'
                elif beats * beat_s > room + 1e-9:
                    beats = int(room / beat_s + 1e-9)
                    if beats < 1: want, why = 'cut', 'the shots are too short for an effect'
            if want != 'cut': tr = dict(type=want, beats=LENGTH[want] if beats >= LENGTH[want] else beats, dur_s=round((LENGTH[want] if beats >= LENGTH[want] else beats) * beat_s, 3), why=why); whips += want == 'whip'
            else: tr['why'] = why
        g['transition'] = tr; prev_type = tr['type']
    return segs
