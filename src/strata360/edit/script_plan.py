"""The film's plan from the script (implementation plan: wiring the script into the film; V1 to V5 for a script-driven cut).

  build(draft, pack, clips, lib, music, voice_s, st=None) -> dict(plan segments, lines, warnings, ...)

The script (edit/script_draft.py) is a list of items played one after another: `clip` (the runner's own lines), `vo` (narration) and `broll` (picture only). Here each item becomes windows of footage, in the
script's order:
  * a `clip` item: the exact span of its first to last line, padded 60 ms before and 120 ms after (as edit/blocks.py), one window up to 20 s (longer is split), played as dialogue;
  * a `vo` item: footage of its clip for as long as the narration takes (its spoken length, from the voice, plus a lead-in and a tail), in windows of 2 to 8 s;
  * a `broll` item: footage of its clip for the seconds the script gives it, in windows of 2 to 8 s.
Narration and b-roll use the clip's free footage (not the dialogue the script plays, not the footage of earlier windows; speech stretches last); when a clip has less than the script asks for, the shortfall is
filled by reusing footage, and said so in `warnings`. Every window is a whole number of beats (cuts fall on beats; a dialogue window is rounded up so it always holds its speech). The techniques are chosen by the
same beam search as the beat planner (chrono.assign_techniques); the plan is saved as an ordinary `edit.plan`, so the timeline, the preview and the final render use it unchanged."""
import hashlib, math
from strata360.edit.script_pack import norm_label

import numpy as np

from strata360.edit import chrono as CH, blocks as BL, optimise as O

LEAD_S = 0.2                 # a narration line starts this long after its window starts
TAIL_S = 0.3                 # and its window runs this long after it ends
MAX_DIALOGUE_S = 20.0        # the longest dialogue technique (dialogue_hold)
MAX_PICTURE_S = CH.MAX_SEG_S
MAX_GAP_S = 45.0             # the longest a gap item plays (script_pack.MAX_GAP_S)
MAX_PHOTO_S = 12.0           # and a photo item (script_pack.MAX_PHOTO_S)


def seg_id(clip, text):
    """A stable name for a narration line: its recording and its voice take stay attached to it across drafts as long as its words do not change."""
    return 'n' + hashlib.sha1(f'{clip}|{text.strip()}'.encode()).hexdigest()[:8]


def estimated_s(text, wpm): return len(text.split()) * 60.0 / wpm


SPLIT_FROM_S = 9.0           # a talking stretch at least this long is cut into several shots (different views of you) when the footage has more than one
SPLIT_TARGET_S = 6.0         # each about this long, the cuts in the pauses between the lines
SPLIT_MIN_S = 3.0


def _pause_spans(ls, a, b):
    """The (start, end) of every pause between consecutive lines (inside [a, b]) that lasts at least 0.25 s."""
    ls = sorted(ls, key=lambda l: l['t0']); return [(round(x['t1'], 3), round(y['t0'], 3)) for x, y in zip(ls, ls[1:]) if y['t0'] - x['t1'] >= 0.25 and a < (x['t1'] + y['t0']) / 2.0 < b]


def snap_cuts(cuts, spans, start, beat_s, end=None, reach=2.5):
    """Move each cut to where the shot before it is a whole number of beats long and the point lies inside a pause: the film's shots are whole beats, so otherwise the shot runs past the cut and the next one repeats the footage (and the two cannot be joined by a glide). The nearest such pause within `reach` s of the cut
    is used (the shots stay at least SPLIT_MIN_S); a cut with none keeps the middle of its pause."""
    out = []; edge = start
    for c in cuts:
        opts = []
        for lo, hi in spans:
            j = max(1, int(math.ceil((lo - edge) / beat_s - 1e-6)))
            while edge + j * beat_s <= hi + 1e-6:
                t = edge + j * beat_s
                if abs(t - c) <= reach and t - edge >= SPLIT_MIN_S - 1e-6 and (end is None or end - t >= SPLIT_MIN_S - 1e-6): opts.append(t)
                j += 1
        t = min(opts, key=lambda x: abs(x - c)) if opts else c; out.append(round(t, 3)); edge = out[-1]
    return out


def _steady_of(fp, p):
    """The `steady` feature of the footage under a dialogue piece, or None."""
    return (getattr(fp.candidate_at(p['start'], p['start'] + p['seconds']), 'features', None) or {}).get('steady')


def join_runs(segs, windows, ps, beat_s):
    """Where a talking stretch was cut into shots inside a pause and the first shot (whole beats) runs a little past the cut, start the second shot where the first ends, so the two are one continuous run of the clip (nothing repeated, and a glide can join them). Only as far as the pause allows: the second shot never starts later than the end of the pause, so no word is lost. Segments are changed in place."""
    for a, b, wa, wb in zip(segs, segs[1:], windows, windows[1:]):
        if wa._piece != wb._piece or a.cand.clip != b.cand.clip: continue
        end = a.clip_start_s + a.beats * beat_s; over = end - b.clip_start_s
        if over <= 1e-6: continue
        hi = next((h for lo, h in ps[wb._piece].get('pause_spans') or [] if lo - 1e-6 <= b.clip_start_s <= h + 1e-6), None)
        move = min(over, max(hi - b.clip_start_s, 0.0)) if hi is not None else min(over, beat_s)                  # a cut in a pause moves no further than the pause; a cut inside speech (busy footage) runs on exactly: the first shot's tail has the words the second would have started with
        if move > 1e-6: wb._start += move; b.clip_start_s = round(wb._start, 3); b.in_s = round(wb._start - b.cand.start_s, 3)


def _pauses(ls, a, b):
    """The middles of the pauses between consecutive lines (inside [a, b]) that last at least 0.25 s: where a cut inside a talking stretch costs no words."""
    ls = sorted(ls, key=lambda l: l['t0']); return [round((x['t1'] + y['t0']) / 2.0, 3) for x, y in zip(ls, ls[1:]) if y['t0'] - x['t1'] >= 0.25 and a < (x['t1'] + y['t0']) / 2.0 < b]


def split_points(start, seconds, pauses, target=SPLIT_TARGET_S, floor=SPLIT_MIN_S, free=False):
    """Where to cut a talking stretch [start, start + seconds] into shots of about `target` s: the pauses nearest to each multiple of the target, no shot under `floor`; [] when it is short or has no usable pause. With `free` (busy footage: quick cuts) a cut may also fall inside speech, half a second grid, a pause still preferred: the picture cuts and the clip's sound runs on."""
    if seconds < SPLIT_FROM_S or not (pauses or free): return []
    grid = [round(start + 0.5 * i, 3) for i in range(1, int(seconds / 0.5))] if free else []; cuts = []; last = start
    for k in range(1, int(seconds // target) + 1):
        want = start + k * target; ok = [x for x in list(pauses) + grid if x - last >= floor and start + seconds - x >= floor]
        if not ok: break
        c = min(ok, key=lambda x: abs(x - want) + (0.0 if x in pauses else 0.8))                                          # a pause when there is one near, else anywhere (the picture cuts, the clip's sound runs on)
        if c > last: cuts.append(c); last = c
    return cuts


def pieces(draft, pack, voice_s, wpm):
    """The script as pieces in order: [{n, kind, clip, label, seconds, ...}]. `voice_s` maps the item number to how long the narration takes to speak (missing: estimated from the words)."""
    by_label = {c['label']: c for c in pack['clips']}; lines = {l['id']: l for c in pack['clips'] for l in c['lines']}; out = []; warn = []
    for n, it in enumerate(draft['items']):
        c = by_label.get(norm_label(it.get('clip', '')))
        if c is None: warn.append(f"item {n + 1}: no clip {it.get('clip')}; skipped"); continue
        if it.get('type') == 'photo' and not c.get('photo'): warn.append(f"item {n + 1}: {c['label']} is not a photo; skipped"); continue
        base = dict(n=n, clip=c['clip'], label=c['label'], duration_s=c['duration_s'])
        if c.get('synthetic'):                                                                          # a generated clip: its whole length, picture only; narration may run over it
            if it['type'] == 'clip': warn.append(f"item {n + 1}: {c['label']} has no words; skipped"); continue
            text = (it.get('text') or '').strip() if it['type'] == 'vo' else ''; d = voice_s.get(n); est = d is None; d = estimated_s(text, wpm) if est else d
            if it['type'] == 'gap' and c.get('photo'): warn.append(f"item {n + 1}: {c['label']} is a photo, not a gap; skipped"); continue
            if it['type'] == 'photo': sec = min(max(float(it.get('seconds') or c['duration_s']), CH.MIN_SEG_S), MAX_PHOTO_S)           # a photo item names its own length (the move is made to it)
            elif it['type'] == 'gap': sec = min(max(float(it.get('seconds') or c['duration_s']), CH.MIN_SEG_S), MAX_GAP_S)             # a gap item names its own length (the clip is made to it)
            else: sec = c['duration_s'] if it['type'] == 'vo' else min(max(float(it.get('seconds') or c['duration_s']), CH.MIN_SEG_S), c['duration_s'])
            piece = (dict(base, kind='synthetic', role='broll' if it['type'] in ('gap', 'photo') else it['type'], gap_kind=it.get('kind') if it['type'] == 'gap' else None, photo=bool(c.get('photo')), text=text, speak_s=d if text else 0.0, estimated=est and bool(text), seconds=max(sec, LEAD_S + d + TAIL_S if text else 0.0), seg=seg_id(c['clip'], text) if text else None))
            out.append(gap_choice(piece, c.get('settings') or {}, LEAD_S + d + TAIL_S if text else 0.0)); continue                 # (the length you gave the gap: exactly or at least)
        if it['type'] == 'clip':
            ls = [lines[i] for i in it.get('lines') or [] if i in lines]
            if not ls: warn.append(f'item {n + 1}: no transcript lines; skipped'); continue
            a = max(min(l['t0'] for l in ls) - BL.PAD_BEFORE_S, 0.0); b = min(max(l['t1'] for l in ls) + BL.PAD_AFTER_S, c['duration_s'])
            out.append(dict(base, kind='clip', start=a, seconds=b - a, view=it.get('view'), pauses=_pauses(ls, a, b), pause_spans=_pause_spans(ls, a, b)))
        elif it['type'] == 'vo':
            text = (it.get('text') or '').strip(); d = voice_s.get(n); est = d is None; d = estimated_s(text, wpm) if est else d
            out.append(dict(base, kind='vo', text=text, speak_s=d, estimated=est, seconds=LEAD_S + d + TAIL_S, seg=seg_id(c['clip'], text)))
        elif it['type'] == 'broll': out.append(dict(base, kind='broll', seconds=float(it.get('seconds') or 0), view=it.get('view')))
    return out, warn


def free_seconds(fp):
    """How many seconds of the clip nobody has taken and the script does not play (overlapping parts counted once)."""
    total = 0.0; end = -1e9
    for a, b in sorted((x, y) for _, x, y in fp.free(True)):
        a = max(a, end); total += max(b - a, 0.0); end = max(end, b)
    return total


def cap_broll(ps, foot, warn):
    """Before the film is fitted to the music: each b-roll is asked for no more than its clip has UNUSED (after the dialogue the script plays and the pieces before it), shortened to that, and left out when under the shortest window, so footage is never shown twice (its sound would be heard twice).
    `duration_s` is set to what is left, which `flex` then uses as the longest the piece may be stretched to. `ps` is changed; the time lost is made up by the fit and by `auto_gaps` / `auto_broll`."""
    used = {}; keep = []
    for p in ps:
        if p['kind'] in ('broll', 'vo') and p['clip'] in foot:
            avail = max(free_seconds(foot[p['clip']]) - used.get(p['clip'], 0.0), 0.0)
            if p['kind'] == 'broll':
                if avail < CH.MIN_SEG_S - 1e-6: warn.append(f"clip {p['label']}: no unused footage left for b-roll; left out"); continue
                if p['seconds'] > avail + 0.04: warn.append(f"clip {p['label']}: only {avail:.1f} s of unused footage for {p['seconds']:.1f} s of b-roll; shortened"); p['seconds'] = round(avail - 0.01, 2)
                p['duration_s'] = min(float(p.get('duration_s') or 1e9), avail)
            used[p['clip']] = used.get(p['clip'], 0.0) + min(p['seconds'], avail)
        keep.append(p)
    ps[:] = keep


def auto_broll(ps, pack, foot, music, target_s, warn, per_clip_s=(3.0, 6.0)):
    """When the film is still shorter than the music by more than a bar, fill the difference with b-roll from clips the script does not use, best footage first, each in its place in the race, one short piece per clip, until the music is filled (to within half a bar). Only unused footage is taken. Returns the labels added;
    `ps` is changed (pieces without an item number: they are not in the script)."""
    beat_s = music.beat_s; band = music.bar_beats; total = sum(est_beats(p, beat_s) for p in ps); target = int(round(target_s / beat_s))
    if target - total <= band: return []
    used = {p['label'] for p in ps}; start = {c['label']: c['start_utc'] for c in pack['clips']}; short_s = (target - total) * beat_s; added = []
    cand = []
    for c in pack['clips']:
        if c.get('synthetic') or c['label'] in used or c['clip'] not in foot: continue
        fp = foot[c['clip']]; avail = free_seconds(fp)
        if avail >= per_clip_s[0]: cand.append((max((x.quality for x in fp.cands), default=0.0), c, avail))
    for q, c, avail in sorted(cand, key=lambda x: -x[0]):
        left = target - total
        if left <= band // 2: break
        sec = round(min(per_clip_s[1], avail - 0.01, max(left * beat_s, per_clip_s[0])), 2)
        piece = dict(n=None, clip=c['clip'], label=c['label'], duration_s=avail, kind='broll', view=None, seconds=sec, auto=True)
        at = next((j for j, p in enumerate(ps) if start.get(p['label'], '') > c['start_utc']), len(ps)); ps.insert(at, piece); total += est_beats(piece, beat_s); added.append(c['label'])
    if added: warn.append(f"the film is {short_s:.0f} s short of the music: added b-roll from clips the script does not use ({', '.join(added)}), unused footage only")
    return added


def usable_s(cands):
    """How many seconds of the clip the candidates cover together (overlaps counted once)."""
    total = 0.0; end = -1e9
    for a, b in sorted((c.start_s, c.end_s) for c in cands):
        a = max(a, end); total += max(b - a, 0.0); end = max(end, b)
    return total


class Footage:
    """The usable footage of one clip: `reserved` is the dialogue the script plays (narration keeps off it), `occ` what earlier windows have taken."""
    def __init__(self, clip, cands):
        self.id = clip['id']; self.duration = float(clip['duration_s']); self.cands = cands; self.face = clip.get('face_view'); self.face_clear = float(clip.get('face_clear', 0.5)); self.occ = []; self.reserved = []; self.speech = [(c.start_s, c.end_s) for c in cands if getattr(c, 'kind', '') == 'speech']

    def candidate_at(self, a, b):
        """The candidate to attach to a dialogue window [a, b]: the one that overlaps it most, a speech stretch winning a tie; None when nothing overlaps."""
        best = None; bs = 0.0
        for c in self.cands:
            ov = min(b, c.end_s) - max(a, c.start_s)
            if ov <= 0: continue
            score = ov + (0.5 if getattr(c, 'kind', '') == 'speech' else 0.0) + 0.01 * c.quality
            if score > bs: best, bs = c, score
        return best

    def face_share(self, a, b):
        """The share of the seconds in [a, b] with a clear view of the wearer's face (analysis/face_view.py), or None when the clip has not been analysed (then nothing is held against the close view)."""
        if not self.face: return None
        s = [sc for t, sc in self.face if a - 0.5 <= t <= b + 0.5]
        return None if not s else sum(1 for sc in s if sc >= self.face_clear) / len(s)

    def views_ok(self, a, b):
        """Whether the footage under [a, b] has a close or a far view of you (K6): there is something to cut between."""
        c = self.candidate_at(a, b); f = (getattr(c, 'features', None) or {}) if c is not None else {}
        return max(f.get('you_close', 0.0), f.get('you_far', 0.0)) >= 0.5

    def free(self, speech_ok):
        """[(candidate, start, end)] of footage nobody has taken and the script does not play, best candidates first; speech stretches only when `speech_ok`."""
        out = []
        for c in sorted(self.cands, key=lambda c: -(c.quality + 0.002 * (c.end_s - c.start_s))):
            if getattr(c, 'kind', '') == 'speech' and not speech_ok: continue
            for x, y in CH.free_parts(c, self.occ + self.reserved + ([] if speech_ok else self.speech)):
                if y - x > 1e-6: out.append((c, x, y))
        return out


def _sizes(seconds, cap, floor):
    """Equal parts of `seconds`, none above `cap`, none below `floor` (a total under the floor is one part of the floor)."""
    if seconds <= floor: return [floor]
    n = int(math.ceil(seconds / cap - 1e-9)); return [seconds / n] * n


def take(fp, seconds, warn, label, cap=MAX_PICTURE_S):
    """Windows [(cand, start, length)] for `seconds` of picture from a clip's footage: the best free parts first, then speech stretches. Footage is NEVER shown twice (its sound would be heard twice): when there is not enough unused footage the window is shorter, and when there is none at all it is left out (warnings say so;
    the time is made up elsewhere, see `cap_broll` and `auto_broll`)."""
    wins = []; prev_end = None
    for size in _sizes(seconds, cap, CH.MIN_SEG_S):
        picked = None
        for speech_ok, tag in ((False, 'free'), (True, 'speech')):
            parts = fp.free(speech_ok)
            ok = [p for p in parts if p[2] - p[1] >= size - 1e-6]
            if ok:
                touch = [p for p in ok if prev_end is not None and p[1] - 1e-6 <= prev_end < p[2] - size + 1e-6]
                c, x, y = touch[0] if touch else ok[0]; start = prev_end if touch else x + (y - x - size) / 2
                picked = (c, start, size, tag); break
        if picked is None:                                                                      # nothing as long as asked: the longest unused stretch there is, shortened (never footage that is used already)
            parts = [p for p in fp.free(True) if p[2] - p[1] >= CH.MIN_SEG_S - 1e-6]
            if not parts: warn.append(f'clip {label}: no unused footage left for {size:.1f} s of picture; left out'); continue
            c, x, y = max(parts, key=lambda p: p[2] - p[1]); picked = (c, x, min(size, y - x), 'short')
        c, start, length, tag = picked
        if tag == 'short': warn.append(f'clip {label}: only {length:.1f} s of unused footage for {size:.1f} s of picture; shortened')
        fp.occ.append((start, start + length)); wins.append((c, start, length)); prev_end = start + length
    return wins


def dialogue_windows(fp, start, seconds, warn, label, cap=MAX_DIALOGUE_S, cuts=()):
    """Windows [(cand, start, length)] for a dialogue span: one up to 20 s, else equal contiguous parts, each at least 2 s (a short span is extended after its end, or before it at the end of the clip). `cuts` (times inside the span, in
    the pauses between lines) split it into shots there instead, so a long talking stretch is not one picture."""
    seconds = max(seconds, CH.MIN_SEG_S); start = max(min(start, fp.duration - seconds), 0.0); out = []
    edges = [start] + [c for c in cuts if start < c < start + seconds] + [start + seconds]
    if len(edges) > 2:
        for a, b in zip(edges, edges[1:]):
            n = max(int(math.ceil((b - a) / cap - 1e-9)), 1); size = (b - a) / n                                  # a shot between two cuts is never longer than a window may be: it is cut into equal parts
            for k in range(n):
                x = a + k * size; c = fp.candidate_at(x, x + size)
                if c is None: warn.append(f'clip {label}: no candidate under the dialogue at {x:.1f} s'); continue
                fp.occ.append((x, x + size)); out.append((c, x, size))
        return out
    n = int(math.ceil(seconds / cap - 1e-9)); size = seconds / n
    for k in range(n):
        a = start + k * size; c = fp.candidate_at(a, a + size)
        if c is None: warn.append(f'clip {label}: no candidate under the dialogue at {a:.1f} s'); continue
        fp.occ.append((a, a + size)); out.append((c, a, size))
    return out


def _has_technique(w, c, lib, music, d):
    """Does any technique fit this window (length, bars, dialogue, the footage's features)? When none does the window is marked forced, so the planner still gives it a plain shot, as for a clip with nothing usable."""
    for t in lib.values():
        if w.speech and not t.dialogue_ok: continue
        if t.id == 'dialogue_hold' and not w.speech: continue
        if not (t.dmin - 1e-9 <= d <= t.dmax + 1e-9): continue
        if t.beats == 'bar' and w.beats % music.bar_beats: continue
        if O.fit(c, t) is not None: return True
    return False


def est_beats(p, beat_s):
    """About how many beats a piece takes in the film (its windows are whole beats: b-roll rounds, the rest round up)."""
    return max(1, int(round(p['seconds'] / beat_s)) if p['kind'] == 'broll' else int(math.ceil(p['seconds'] / beat_s - 1e-9)))


GAP_MIN_S = 3.0              # a generated clip is shortened to this at the least to fit the music


def gap_choice(p, lim, need=0.0):
    """Apply what you chose for a gap's length to its piece: `set` makes it exactly that long (or as long as the narration over it needs, if longer) and fixed, `min` at least that long, never shortened below it to fit the music."""
    if lim.get('mode') == 'set': p['seconds'] = max(float(lim['seconds']), need); p['fixed'] = True
    elif lim.get('mode') == 'min': p['seconds'] = max(p['seconds'], float(lim['seconds'])); p['min_s'] = float(lim['seconds'])
    return p


def flex(p):
    """(shortest, longest) seconds a piece may be stretched to in order to fit the music, or None when its length is fixed: camera b-roll 2 s up to double (or 6 s more), but not longer than its clip; a generated clip (picture only, not under narration) 3 s up to one and a half times (45 s at most)."""
    if p['kind'] == 'broll': return 2.0, max(min(max(p['seconds'] * 2.0, p['seconds'] + 6.0), float(p.get('duration_s') or 1e9) - 0.2), p['seconds'])           # never past the clip's own length: more would show the same footage twice
    if p['kind'] == 'synthetic' and p.get('role') == 'broll':
        if p.get('fixed'): return None                                                                  # a length you set stays
        lo = max(GAP_MIN_S, p.get('min_s') or 0.0); top = MAX_PHOTO_S if p.get('photo') else MAX_GAP_S; return min(lo, p['seconds']), min(top, max(p['seconds'] * 1.5, p['seconds'] + 3.0, lo))                       # (a photo is not shown longer than MAX_PHOTO_S)
    return None


def fit_pass(ps, music, target_s, start=0):
    """Bring the film's length to the music's (D7): when the pieces add up to more than `target_s` plus a bar, shorten the flexible pieces (flex(): b-roll and generated clips), and when to less than it minus a bar, lengthen them; the voice and the
    runner's words keep their lengths; only the pieces from index `start` on are changed. Returns dict(target_s, before_s, after_s)."""
    beat_s = music.beat_s; band = music.bar_beats; target = int(round(target_s / beat_s)); total = sum(est_beats(p, beat_s) for p in ps); before = total; free = [p for p in ps[start:] if flex(p)]; diff = total - target
    if abs(diff) > band and free:
        sign = -1 if diff > 0 else 1; need = abs(diff) - band // 2                                                          # bring it to within half a bar of the music
        room = {id(p): int(((p['seconds'] - flex(p)[0]) if sign < 0 else (flex(p)[1] - p['seconds'])) / beat_s + 1e-9) for p in free}
        while need > 0:
            active = [p for p in free if room[id(p)] > 0]
            if not active: break
            share = max(1, need // len(active))                                                                           # an even share each round, so no single piece takes it all
            for p in active:
                d = min(share, room[id(p)], need); p['seconds'] += sign * d * beat_s; room[id(p)] -= d; need -= d; total += sign * d
                if need <= 0: break
    return dict(target_s=round(target_s, 2), before_s=round(before * beat_s, 2), after_s=round(total * beat_s, 2))


def fit_and_anchor(ps, draft, music, target_s, warn):
    """Fit the film to the music and place the anchors, in the order that leaves the film nearest the music: (A) anchors first, then only the flexible pieces from the last anchored one on are fitted (its own length too: its start does not move), so no anchor moves; (B) everything fitted first, then the
    anchors (which stretch b-roll before them). Both are tried on copies of the lengths; the better is kept. Returns (the fit report or None, the anchors report); warnings go into `warn`."""
    if not target_s: return None, anchor_pass(ps, draft, music, warn)
    beat_s = music.beat_s; total = lambda: sum(est_beats(p, beat_s) for p in ps); target = target_s / beat_s; keep = [p['seconds'] for p in ps]; res = []
    for order in ('anchors_first', 'fit_first'):
        for p, x in zip(ps, keep): p['seconds'] = x
        w = []
        if order == 'anchors_first':
            anc = anchor_pass(ps, draft, music, w); last = max((k for k, p in enumerate(ps) if p.get('n') is not None and isinstance(draft['items'][p['n']].get('anchor'), dict)), default=-1); fit = fit_pass(ps, music, target_s, start=max(last, 0))                                   # (the anchored piece itself may change: its start does not move)
        else: fit = fit_pass(ps, music, target_s); anc = anchor_pass(ps, draft, music, w)
        res.append((abs(total() - target), order == 'fit_first', [p['seconds'] for p in ps], fit, anc, w))
    best = min(res, key=lambda r: r[:2])
    for p, x in zip(ps, best[2]): p['seconds'] = x
    warn.extend(best[5]); fit = dict(best[3], after_s=round(total() * beat_s, 2)); return fit, best[4]


def auto_gaps(ps, pack, music, target_s, warn, min_race_s=3600.0, seconds=(3.0, 8.0)):
    """When the film is still shorter than the music by more than a bar, add the gaps of an hour or more that the script left out, longest first, as short 2D map clips in their place in the race, until the music is filled (to within
    half a bar). Each is about a fiftieth of its time in the film, between 3 and 8 s. Returns the labels added; `ps` is changed (pieces without an item number: they are not in the script)."""
    beat_s = music.beat_s; band = music.bar_beats; total = sum(est_beats(p, beat_s) for p in ps); target = int(round(target_s / beat_s)); used = {p['label'] for p in ps}
    if target - total <= band: return []
    start = {c['label']: c['start_utc'] for c in pack['clips']}; added = []; short_s = (target - total) * beat_s
    for c in sorted((c for c in pack['clips'] if c.get('synthetic') and c.get('race_s', 0) >= min_race_s and c['label'] not in used), key=lambda c: -c['race_s']):
        left = target - total
        if left <= band // 2: break
        sec = min(max(c['race_s'] / 3600.0 * 0.5 + 3.0, seconds[0]), seconds[1], max(left * beat_s, seconds[0]))
        piece = gap_choice(dict(n=None, clip=c['clip'], label=c['label'], duration_s=c['duration_s'], kind='synthetic', role='broll', gap_kind=None, text='', speak_s=0.0, estimated=False, seconds=round(sec, 2), seg=None, auto=True), c.get('settings') or {})
        at = next((j for j, p in enumerate(ps) if start.get(p['label'], '') > c['start_utc']), len(ps)); ps.insert(at, piece); total += est_beats(piece, beat_s); added.append(c['label'])
    if added: warn.append(f"the script is {short_s:.0f} s short of the music: added the unfilled gap clip(s) {', '.join(added)} (2D maps, in their place in the race)")
    return added


def force_gaps(ps, pack, warn):
    """The gaps and photos you marked `must` (the Gaps page, the photo cards) that the script left out, added as picture-only generated clips in their place in the race, at the length you gave (else the default for the gap). Returns the labels added; `ps` is changed."""
    used = {p['label'] for p in ps}; must = [c for c in pack['clips'] if c.get('synthetic') and (c.get('settings') or {}).get('must') and c['label'] not in used]
    if not must: return []
    start = {c['label']: c['start_utc'] for c in pack['clips']}; added = []
    for c in sorted(must, key=lambda c: c['start_utc']):
        piece = gap_choice(dict(n=None, clip=c['clip'], label=c['label'], duration_s=c['duration_s'], kind='synthetic', role='broll', gap_kind=None, photo=bool(c.get('photo')), text='', speak_s=0.0, estimated=False, seconds=round(min(max(c['duration_s'], 3.0), MAX_PHOTO_S if c.get('photo') else MAX_GAP_S), 2), seg=None, auto=True), c.get('settings') or {})
        at = next((j for j, p in enumerate(ps) if start.get(p['label'], '') > c['start_utc']), len(ps)); ps.insert(at, piece); added.append(c['label'])
    if added: warn.append(f"added the gap or photo clip(s) {', '.join(added)} because you marked them to use")
    return added


def anchor_pass(ps, draft, music, warn):
    """Move the script's anchored items to the music: for each item with `anchor: {film_s}` the wanted start is the nearest BAR LINE to that time, and the b-roll pieces just before it (back to the previous anchored item) are lengthened or
    shortened, in whole beats, to bring it there (b-roll is the only picture that can stretch: the voice, the runner's words and the generated clips have fixed lengths). What cannot be moved is reported. Changes `seconds` of b-roll pieces; returns [{item, anchor_s, target_s, moved_s, left_s}]."""
    beat_s = music.beat_s; bar = music.bar_beats; items = draft['items']; out = []; floor = 0
    for k, p in enumerate(ps):
        anc = items[p['n']].get('anchor') if p.get('n') is not None else None
        if not (isinstance(anc, dict) and isinstance(anc.get('film_s'), (int, float))): continue
        starts = [0]
        for q in ps[:-1]: starts.append(starts[-1] + est_beats(q, beat_s))
        target = int(round(anc['film_s'] / (bar * beat_s))) * bar; left = target - starts[k]; first = left
        for j in range(k - 1, floor - 1, -1):
            if left == 0: break
            q = ps[j]
            if q['kind'] != 'broll': continue
            new = min(max(q['seconds'] + left * beat_s, 2.0), flex(q)[1]); done = int(round((new - q['seconds']) / beat_s)); q['seconds'] = q['seconds'] + done * beat_s; left -= done
        out.append(dict(item=p['n'] + 1, anchor_s=float(anc['film_s']), target_s=round(target * beat_s, 2), moved_s=round((first - left) * beat_s, 2), left_s=round(left * beat_s, 2)))
        if left: warn.append(f"item {p['n'] + 1}: anchored at {anc['film_s']:.0f} s, the nearest bar is {target * beat_s:.0f} s, and there is no b-roll before it to stretch by the last {abs(left) * beat_s:.1f} s: it starts {abs(left) * beat_s:.1f} s {'early' if left > 0 else 'late'}")
        floor = k
    return out


def over_singing(lines, spans, share=0.3):
    """The narration lines (each {text, film_start_s, speak_s}) that are mostly over singing: [{text, a, b, sung_s}]."""
    out = []
    for l in lines:
        a = l['film_start_s'] + LEAD_S; b = a + l['speak_s']; sung = sum(max(0.0, min(b, y) - max(a, x)) for x, y in spans)
        if l['speak_s'] > 0 and sung > share * l['speak_s']: out.append(dict(text=l['text'], a=round(a, 1), b=round(b, 1), sung_s=round(sung, 1)))
    return out


def build(draft, pack, clips, lib, music, voice_s=None, wpm=150.0, st=None, seed=1, target_s=None):
    """The plan for a script. `clips` are the planner's clip dicts (project.load_clips), `music` an O.Music (its `beats` is replaced by what the script needs). Returns
    dict(segs=[chrono.Seg in film order], items=[(piece index, role)], pieces, lines=[narration lines for the voice-over], beats, warnings)."""
    voice_s = voice_s or {}; st = st or CH.Settings(seed=seed); rng = np.random.default_rng(st.seed); beat_s = music.beat_s; warn = []
    clips = sorted(clips, key=lambda c: c['start_utc']); index = {c['id']: i for i, c in enumerate(clips)}
    foot = {c['id']: Footage(c, CH.clip_candidates(c)) for c in clips}
    ps, w0 = pieces(draft, pack, voice_s, wpm); warn += w0; ps = [p for p in ps if p['clip'] in foot or p['kind'] == 'synthetic']
    for p in ps:                                                                                    # the dialogue the script plays is not footage for narration or b-roll
        if p['kind'] == 'clip' and p['clip'] in foot: foot[p['clip']].reserved.append((p['start'], p['start'] + p['seconds']))
    force_gaps(ps, pack, warn)                                                                      # the gaps you marked must-use that the script left out
    cap_broll(ps, foot, warn)                                                                       # b-roll is asked for no more than the clip has unused (flex() then never stretches it past that either)
    fit, anchors = fit_and_anchor(ps, draft, music, target_s, warn)
    auto = auto_gaps(ps, pack, music, target_s, warn) if target_s else []
    more = auto_broll(ps, pack, foot, music, target_s, warn) if target_s else []
    if auto or more: fit['after_s'] = round(sum(est_beats(p, beat_s) for p in ps) * beat_s, 2); anchors = anchor_pass(ps, draft, music, [])           # (the gaps added ahead of an anchored item shift it: placed again)
    cap_p = int(MAX_PICTURE_S / beat_s + 1e-9) * beat_s; cap_d = int(MAX_DIALOGUE_S / beat_s + 1e-9) * beat_s          # the longest window in WHOLE beats: rounding a window up to beats must never take it past what a technique allows
    windows = []; roles = []; first_window = {}
    for k, p in enumerate(ps):
        if p['kind'] == 'synthetic': continue                                                       # placed after the footage windows are planned (below)
        fp = foot[p['clip']]
        wins = dialogue_windows(fp, p['start'], p['seconds'], warn, p['label'], cap_d, cuts=snap_cuts(split_points(p['start'], p['seconds'], p.get('pauses') or [], target=SPLIT_TARGET_S * (0.5 + 0.5 * CH.calm(_steady_of(fp, p))), free=CH.calm(_steady_of(fp, p)) < 0.7), p.get('pause_spans') or [], p['start'], beat_s, end=p['start'] + p['seconds']) if fp.views_ok(p['start'], p['start'] + p['seconds']) else ()) if p['kind'] == 'clip' else take(fp, p['seconds'], warn, p['label'], cap_p)
        if p['kind'] == 'vo' and wins:                                                                  # the narration must have picture for as long as it is spoken
            short = p['seconds'] - sum(w[2] for w in wins)
            if short > 1e-6:
                c0, s0, l0 = wins[-1]; grow = min(short, max(cap_p - l0, 0.0)); wins[-1] = (c0, s0, l0 + grow)
                warn.append(f"item {p['n'] + 1}: the narration needs {p['seconds']:.1f} s but clip {p['label']} has {p['seconds'] - short:.1f} s of footage for it; the last frame is held" + (f" for {short - grow:.1f} s more than a window allows" if short - grow > 1e-6 else '') + ' (choices: shorten the line, move it to a longer clip, or let the hold stand)')
        for c, start, length in wins:
            speech = p['kind'] == 'clip'; beats = max(1, int(math.ceil(length / beat_s - 1e-9))) if p['kind'] != 'broll' else max(1, int(round(length / beat_s)))
            dur = beats * beat_s; start = max(min(start, fp.duration - dur), 0.0)
            w = CH.Window(index[p['clip']], c, start - c.start_s, beats, c.quality, getattr(c, 'forced', False), speech=speech); w._piece = k; w._start = start; w.view = p.get('view'); w.face = fp.face_share(start, start + dur); w.forced = w.forced or not _has_technique(w, c, lib, music, dur)
            windows.append(w); roles.append(p['kind']); first_window.setdefault(k, len(windows) - 1)
    if not windows and not any(p['kind'] == 'synthetic' for p in ps): raise O.Infeasible('the script has no windows: no item could be matched to footage')
    B = sum(w.beats for w in windows); music = O.Music(bpm=music.bpm, beats=B, bar_beats=music.bar_beats, sections=music.sections)
    segs = CH.assign_techniques(windows, clips, lib, music, st, rng, warn, B=B) if windows else []
    for sg, w in zip(segs, windows): sg.clip_start_s = round(w._start, 3); sg.in_s = round(w._start - sg.cand.start_s, 3)
    join_runs(segs, windows, ps, beat_s)
    for sg, w in zip(segs, windows):                                                                                  # the part of each dialogue window that is the lines the script wants (the rest of the window, from rounding up to whole beats or from lengthening it, is not their sound)
        p = ps[w._piece]
        if p['kind'] == 'clip': sg.parts['voice_span'] = [round(max(p['start'] - sg.clip_start_s, 0.0), 3), round(min(p['start'] + p['seconds'] - sg.clip_start_s, sg.beats * beat_s), 3)]
    syn = {k: max(1, int(math.ceil(p['seconds'] / beat_s - 1e-9))) for k, p in enumerate(ps) if p['kind'] == 'synthetic'}; before = {}; run = 0              # beats of generated clips ahead of each piece
    for k in range(len(ps)): before[k] = run; run += syn.get(k, 0)
    for sg, w in zip(segs, windows): sg.start += before[w._piece]
    lines = []; starts = [sg.start * beat_s for sg in segs]; synthetic = []
    place = 0                                                                                                           # the generated clips in film order: each starts where the piece before it ends
    for k, p in enumerate(ps):
        n_k = syn[k] if k in syn else sum(sg.beats for sg, w in zip(segs, windows) if w._piece == k)
        if k in syn:
            synthetic.append(dict(piece=k, start_beat=place, beats=syn[k], clip=p['clip'], label=p['label'], seconds=round(syn[k] * beat_s, 3), role=p['role'], item=p['n']))      # the clip is made as long as its window (whole beats): played as it is, nothing held or slowed
            if p['text']: lines.append(dict(seg=p['seg'], text=p['text'], clip=p['clip'], item=p['n'], film_start_s=round(place * beat_s, 3), seconds=round(syn[k] * beat_s, 3), speak_s=round(p['speak_s'], 3), estimated=p['estimated']))
        place += n_k
    for k, p in enumerate(ps):
        if p['kind'] == 'vo' and k in first_window: lines.append(dict(seg=p['seg'], text=p['text'], clip=p['clip'], item=p['n'], film_start_s=round(starts[first_window[k]], 3), seconds=round(sum(w.beats for w in windows if w._piece == k) * beat_s, 3), speak_s=round(p['speak_s'], 3), estimated=p['estimated']))
    lines.sort(key=lambda l: l['film_start_s'])
    start_of = {}                                                                                     # where each piece really starts in the film (seconds)
    for k in range(len(ps)):
        if k in syn: start_of[k] = next(x['start_beat'] for x in synthetic if x['piece'] == k) * beat_s
        elif k in first_window: start_of[k] = segs[first_window[k]].start * beat_s
    for a in anchors:
        k = next((k for k, p in enumerate(ps) if p.get('n') is not None and p['n'] + 1 == a['item']), None); a['start_s'] = round(start_of[k], 2) if k in start_of else None
        if a['start_s'] is not None and abs(a['start_s'] - a['anchor_s']) > music.bar_beats * beat_s: warn.append(f"item {a['item']}: anchored at {a['anchor_s']:.0f} s, starts at {a['start_s']:.0f} s")
    spans = (((pack.get('music') or {}).get('lyrics')) or {}).get('vocal_spans') or []; sung = over_singing(lines, spans)
    if fit:
        fit['final_s'] = round((B + run) * beat_s, 2); fit['over_s'] = round(fit['final_s'] - target_s, 2)
        if abs(fit['over_s']) > music.bar_beats * beat_s: warn.append(f"the film is {abs(fit['over_s']):.0f} s {'longer' if fit['over_s'] > 0 else 'shorter'} than the music ({fit['final_s']:.0f} s against {target_s:.0f} s) and the b-roll cannot absorb it: " + ('shorten narration, your own words or a gap clip' if fit['over_s'] > 0 else 'add picture or narration') + (' (the anchors fix where some items start)' if anchors else ''))
    return dict(segs=segs, roles=roles, piece_of=[w._piece for w in windows], pieces=ps, lines=lines, beats=B + run, synthetic=synthetic, anchors=anchors, over_singing=sung, fit=fit, auto_gaps=auto, warnings=warn)
