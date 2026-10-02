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


def seg_id(clip, text):
    """A stable name for a narration line: its recording and its voice take stay attached to it across drafts as long as its words do not change."""
    return 'n' + hashlib.sha1(f'{clip}|{text.strip()}'.encode()).hexdigest()[:8]


def estimated_s(text, wpm): return len(text.split()) * 60.0 / wpm


def pieces(draft, pack, voice_s, wpm):
    """The script as pieces in order: [{n, kind, clip, label, seconds, ...}]. `voice_s` maps the item number to how long the narration takes to speak (missing: estimated from the words)."""
    by_label = {c['label']: c for c in pack['clips']}; lines = {l['id']: l for c in pack['clips'] for l in c['lines']}; out = []; warn = []
    for n, it in enumerate(draft['items']):
        c = by_label.get(norm_label(it.get('clip', '')))
        if c is None: warn.append(f"item {n + 1}: no clip {it.get('clip')}; skipped"); continue
        base = dict(n=n, clip=c['clip'], label=c['label'], duration_s=c['duration_s'])
        if c.get('synthetic'):                                                                          # a generated clip: its whole length, picture only; narration may run over it
            if it['type'] == 'clip': warn.append(f"item {n + 1}: {c['label']} has no words; skipped"); continue
            text = (it.get('text') or '').strip() if it['type'] == 'vo' else ''; d = voice_s.get(n); est = d is None; d = estimated_s(text, wpm) if est else d
            if it['type'] == 'gap': sec = min(max(float(it.get('seconds') or c['duration_s']), CH.MIN_SEG_S), MAX_GAP_S)             # a gap item names its own length (the clip is made to it)
            else: sec = c['duration_s'] if it['type'] == 'vo' else min(max(float(it.get('seconds') or c['duration_s']), CH.MIN_SEG_S), c['duration_s'])
            out.append(dict(base, kind='synthetic', role='broll' if it['type'] == 'gap' else it['type'], gap_kind=it.get('kind') if it['type'] == 'gap' else None, text=text, speak_s=d if text else 0.0, estimated=est and bool(text), seconds=max(sec, LEAD_S + d + TAIL_S if text else 0.0), seg=seg_id(c['clip'], text) if text else None)); continue
        if it['type'] == 'clip':
            ls = [lines[i] for i in it.get('lines') or [] if i in lines]
            if not ls: warn.append(f'item {n + 1}: no transcript lines; skipped'); continue
            a = max(min(l['t0'] for l in ls) - BL.PAD_BEFORE_S, 0.0); b = min(max(l['t1'] for l in ls) + BL.PAD_AFTER_S, c['duration_s'])
            out.append(dict(base, kind='clip', start=a, seconds=b - a))
        elif it['type'] == 'vo':
            text = (it.get('text') or '').strip(); d = voice_s.get(n); est = d is None; d = estimated_s(text, wpm) if est else d
            out.append(dict(base, kind='vo', text=text, speak_s=d, estimated=est, seconds=LEAD_S + d + TAIL_S, seg=seg_id(c['clip'], text)))
        elif it['type'] == 'broll': out.append(dict(base, kind='broll', seconds=float(it.get('seconds') or 0)))
    return out, warn


class Footage:
    """The usable footage of one clip: `reserved` is the dialogue the script plays (narration keeps off it), `occ` what earlier windows have taken."""
    def __init__(self, clip, cands):
        self.id = clip['id']; self.duration = float(clip['duration_s']); self.cands = cands; self.occ = []; self.reserved = []; self.speech = [(c.start_s, c.end_s) for c in cands if getattr(c, 'kind', '') == 'speech']

    def candidate_at(self, a, b):
        """The candidate to attach to a dialogue window [a, b]: the one that overlaps it most, a speech stretch winning a tie; None when nothing overlaps."""
        best = None; bs = 0.0
        for c in self.cands:
            ov = min(b, c.end_s) - max(a, c.start_s)
            if ov <= 0: continue
            score = ov + (0.5 if getattr(c, 'kind', '') == 'speech' else 0.0) + 0.01 * c.quality
            if score > bs: best, bs = c, score
        return best

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
    """Windows [(cand, start, length)] for `seconds` of picture from a clip's footage: the best free parts first, then speech stretches, then reused footage (with a warning)."""
    wins = []; prev_end = None
    for size in _sizes(seconds, cap, CH.MIN_SEG_S):
        picked = None
        for speech_ok, tag in ((False, 'free'), (True, 'speech'), (None, 'reused')):
            parts = fp.free(speech_ok) if speech_ok is not None else [(c, c.start_s, c.end_s) for c in fp.cands]
            ok = [p for p in parts if p[2] - p[1] >= size - 1e-6]
            if ok:
                touch = [p for p in ok if prev_end is not None and p[1] - 1e-6 <= prev_end < p[2] - size + 1e-6]
                c, x, y = touch[0] if touch else ok[0]; start = prev_end if touch else x + (y - x - size) / 2
                picked = (c, start, size, tag); break
        if picked is None:                                                                      # nothing as long as asked: the longest stretch there is, shortened
            parts = fp.free(True) or [(c, c.start_s, c.end_s) for c in fp.cands]
            if not parts: warn.append(f'clip {label}: no footage at all for {size:.1f} s of picture'); continue
            c, x, y = max(parts, key=lambda p: p[2] - p[1]); picked = (c, x, min(size, y - x), 'short')
        c, start, length, tag = picked
        if tag in ('reused', 'short'): warn.append(f'clip {label}: not enough free footage for {size:.1f} s of picture ({tag}); footage is shown again or shortened')
        fp.occ.append((start, start + length)); wins.append((c, start, length)); prev_end = start + length
    return wins


def dialogue_windows(fp, start, seconds, warn, label, cap=MAX_DIALOGUE_S):
    """Windows [(cand, start, length)] for a dialogue span: one up to 20 s, else equal contiguous parts, each at least 2 s (a short span is extended after its end, or before it at the end of the clip)."""
    seconds = max(seconds, CH.MIN_SEG_S); start = max(min(start, fp.duration - seconds), 0.0); out = []; n = int(math.ceil(seconds / cap - 1e-9)); size = seconds / n
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


def anchor_pass(ps, draft, music, warn):
    """Move the script's anchored items to the music: for each item with `anchor: {film_s}` the wanted start is the nearest BAR LINE to that time, and the b-roll pieces just before it (back to the previous anchored item) are lengthened or
    shortened, in whole beats, to bring it there (b-roll is the only picture that can stretch: the voice, the runner's words and the generated clips have fixed lengths). What cannot be moved is reported. Changes `seconds` of b-roll pieces; returns [{item, anchor_s, target_s, moved_s, left_s}]."""
    beat_s = music.beat_s; bar = music.bar_beats; items = draft['items']; out = []; floor = 0
    for k, p in enumerate(ps):
        anc = items[p['n']].get('anchor')
        if not (isinstance(anc, dict) and isinstance(anc.get('film_s'), (int, float))): continue
        starts = [0]
        for q in ps[:-1]: starts.append(starts[-1] + est_beats(q, beat_s))
        target = int(round(anc['film_s'] / (bar * beat_s))) * bar; left = target - starts[k]; first = left
        for j in range(k - 1, floor - 1, -1):
            if left == 0: break
            q = ps[j]
            if q['kind'] != 'broll': continue
            new = min(max(q['seconds'] + left * beat_s, 2.0), max(q['seconds'] * 2.0, q['seconds'] + 6.0)); done = int(round((new - q['seconds']) / beat_s)); q['seconds'] = q['seconds'] + done * beat_s; left -= done
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


def build(draft, pack, clips, lib, music, voice_s=None, wpm=150.0, st=None, seed=1):
    """The plan for a script. `clips` are the planner's clip dicts (project.load_clips), `music` an O.Music (its `beats` is replaced by what the script needs). Returns
    dict(segs=[chrono.Seg in film order], items=[(piece index, role)], pieces, lines=[narration lines for the voice-over], beats, warnings)."""
    voice_s = voice_s or {}; st = st or CH.Settings(seed=seed); rng = np.random.default_rng(st.seed); beat_s = music.beat_s; warn = []
    clips = sorted(clips, key=lambda c: c['start_utc']); index = {c['id']: i for i, c in enumerate(clips)}
    foot = {c['id']: Footage(c, CH.clip_candidates(c)) for c in clips}
    ps, w0 = pieces(draft, pack, voice_s, wpm); warn += w0; ps = [p for p in ps if p['clip'] in foot or p['kind'] == 'synthetic']
    anchors = anchor_pass(ps, draft, music, warn)
    for p in ps:                                                                                    # the dialogue the script plays is not footage for narration
        if p['kind'] == 'clip': foot[p['clip']].reserved.append((p['start'], p['start'] + p['seconds']))
    cap_p = int(MAX_PICTURE_S / beat_s + 1e-9) * beat_s; cap_d = int(MAX_DIALOGUE_S / beat_s + 1e-9) * beat_s          # the longest window in WHOLE beats: rounding a window up to beats must never take it past what a technique allows
    windows = []; roles = []; first_window = {}
    for k, p in enumerate(ps):
        if p['kind'] == 'synthetic': continue                                                       # placed after the footage windows are planned (below)
        fp = foot[p['clip']]
        wins = dialogue_windows(fp, p['start'], p['seconds'], warn, p['label'], cap_d) if p['kind'] == 'clip' else take(fp, p['seconds'], warn, p['label'], cap_p)
        if p['kind'] == 'vo' and wins:                                                                  # the narration must have picture for as long as it is spoken
            short = p['seconds'] - sum(w[2] for w in wins)
            if short > 1e-6:
                c0, s0, l0 = wins[-1]; grow = min(short, max(cap_p - l0, 0.0)); wins[-1] = (c0, s0, l0 + grow)
                warn.append(f"item {p['n'] + 1}: the narration needs {p['seconds']:.1f} s but clip {p['label']} has {p['seconds'] - short:.1f} s of footage for it; the last frame is held" + (f" for {short - grow:.1f} s more than a window allows" if short - grow > 1e-6 else '') + ' (choices: shorten the line, move it to a longer clip, or let the hold stand)')
        for c, start, length in wins:
            speech = p['kind'] == 'clip'; beats = max(1, int(math.ceil(length / beat_s - 1e-9))) if p['kind'] != 'broll' else max(1, int(round(length / beat_s)))
            dur = beats * beat_s; start = max(min(start, fp.duration - dur), 0.0)
            w = CH.Window(index[p['clip']], c, start - c.start_s, beats, c.quality, getattr(c, 'forced', False), speech=speech); w._piece = k; w._start = start; w.forced = w.forced or not _has_technique(w, c, lib, music, dur)
            windows.append(w); roles.append(p['kind']); first_window.setdefault(k, len(windows) - 1)
    if not windows and not any(p['kind'] == 'synthetic' for p in ps): raise O.Infeasible('the script has no windows: no item could be matched to footage')
    B = sum(w.beats for w in windows); music = O.Music(bpm=music.bpm, beats=B, bar_beats=music.bar_beats, sections=music.sections)
    segs = CH.assign_techniques(windows, clips, lib, music, st, rng, warn, B=B) if windows else []
    for sg, w in zip(segs, windows): sg.clip_start_s = round(w._start, 3); sg.in_s = round(w._start - sg.cand.start_s, 3)
    syn = {k: max(1, int(math.ceil(p['seconds'] / beat_s - 1e-9))) for k, p in enumerate(ps) if p['kind'] == 'synthetic'}; before = {}; run = 0              # beats of generated clips ahead of each piece
    for k in range(len(ps)): before[k] = run; run += syn.get(k, 0)
    for sg, w in zip(segs, windows): sg.start += before[w._piece]
    lines = []; starts = [sg.start * beat_s for sg in segs]; synthetic = []
    place = 0                                                                                                           # the generated clips in film order: each starts where the piece before it ends
    for k, p in enumerate(ps):
        n_k = syn[k] if k in syn else sum(sg.beats for sg, w in zip(segs, windows) if w._piece == k)
        if k in syn:
            synthetic.append(dict(piece=k, start_beat=place, beats=syn[k], clip=p['clip'], label=p['label'], seconds=round(p['seconds'], 3), role=p['role'], item=p['n']))
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
        k = next((k for k, p in enumerate(ps) if p['n'] + 1 == a['item']), None); a['start_s'] = round(start_of[k], 2) if k in start_of else None
        if a['start_s'] is not None and abs(a['start_s'] - a['anchor_s']) > music.bar_beats * beat_s: warn.append(f"item {a['item']}: anchored at {a['anchor_s']:.0f} s, starts at {a['start_s']:.0f} s")
    spans = (((pack.get('music') or {}).get('lyrics')) or {}).get('vocal_spans') or []; sung = over_singing(lines, spans)
    for x in sung: warn.append(f"narration at {x['a']:.0f}-{x['b']:.0f} s is over singing for {x['sung_s']:.0f} s: \"{x['text'][:50]}\"; the music is turned down under it")
    return dict(segs=segs, roles=roles, piece_of=[w._piece for w in windows], pieces=ps, lines=lines, beats=B + run, synthetic=synthetic, anchors=anchors, over_singing=sung, warnings=warn)
