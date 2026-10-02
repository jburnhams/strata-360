"""The whole-race script writer (implementation plan V2b): a draft from everything the writer knows about the race, then revisions of that draft as the user marks lines and pins narration.

  write(pack, target_s, wpm, pins=None, draft=None, chat=..., retries=2) -> doc

The writer (an LLM: Gemini 3.1 Pro by default) gets the whole context pack (edit/script_pack.py) and returns a script of items played one after another: `clip` (the runner's own lines, by line id), `vo` (narration, with a
`basis`), `broll` (picture only). Structure is checked in code against the real durations and drives a retry that sends the problems back (length within 3%, shooting order, one run per clip, no more picture than a clip has
usable, every pin honoured); grounding is advisory (edit/script_ground.py) and only becomes warnings. Drafts are kept in <race dir>/script2/ (the last three), pins in script2/pins.json."""
import datetime as dt, json, math, os, re, time

from strata360.edit import script_pack as SP, script_pins as PN, script_ground as GR
from strata360.edit.script_pack import norm_label

PROMPT_VERSION = 10
PAD_S = 0.18                  # a clip item is played from the start of its first line to the end of its last line, plus this
VO_PAUSE_S = 0.25             # breathing room after a narration item
ANCHOR_SLACK_S = 8.0          # an anchor further than this from where the items put it is sent back (the editor stretches b-roll for small differences)
MIN_GAP_S = 2.0               # a gap item plays for this long at least,
MAX_GAP_S = SP.MAX_GAP_S      # and this long at most
TOLERANCE = 0.03              # the film's length may differ from the target by this share
KEEP = 3                      # drafts kept
VO_WPM = 145.0                # a comfortable narration pace (edit/script.py DEFAULT_WPM)
VO_MAX_SPEEDUP = 1.25         # the voice can be sped up this much at most (edit/vo_fit.py)

SYSTEM = '''You are the script editor of a documentary about one runner's ultramarathon (a very long race), filmed by the runner on a 360 camera. You decide what the film says: which of the runner's own spoken lines are kept, what voice-over links them, and how much picture each clip gets. A video editor cuts the picture afterwards; you write the SCRIPT only.

THE KINDS OF ITEM, played one after another in the order you write them (never at the same time):
- "clip": the runner's own words from the recording, played as spoken with the picture of that clip. You choose them by line id: "from" and "to" are the first and last line of one unbroken stretch (inclusive); lines you do not include are cut. Whole lines only (a line may have been split into pieces such as 0023.27.1, 0023.27.2: they are lines of their own). Its length is from the start of the first line to the end of the last line (the pauses between them are kept).
- "vo": narration the runner records afterwards and speaks over the picture of that clip. First person, natural, spoken. Its length is words / WORDS-PER-MINUTE.
- "broll": picture of that clip with no speech (music only), for a number of seconds you choose.
- "gap": a generated clip for a gap in the footage (a clip marked NO FOOTAGE): "clip" is its name (G01, G02 ...), "kind" is "map" (the route drawn on a 2D map as the runner moves along it) or "flyover" (a 3D terrain flyover: more striking, but the user must approve its render, so use it for a few gaps that matter, such as a big climb or a night), and "seconds" is how long it plays (2 to 45): the gap is shown very fast, the clock, distance, pace and altitude on screen. You may put "vo" over a gap clip. The race is one continuous story, so the passage of time and distance matters: fill MOST gaps of an hour or more with a gap clip (a 2D map of 3 to 6 s is enough for a short gap, longer for a long or dramatic one), and use 3D flyovers for the few that matter most (a big climb, a night, the final stretch). Leave a gap out only when the clips either side already tell what happened in it. A gap clip needs no narration, but narration over one carries time and distance well. A gap is never a "clip" item.
A "clip" or "broll" item may carry "view": "mid" (the usual view of the runner), "close" (a face zoom: for an emotional or intimate line) or "far" (ultra wide: the whole body and the surroundings, for the sense of place, effort or loneliness). A clip lists which views it has ("views of you") and for how much of its time; ask only for a view it has. Without a "view" the editor chooses, and cuts a long talking stretch between the views itself, so ask for one only where it matters.
Any item may carry "anchor": {"film_s": number, "why": "reason"}: where in the film (in seconds) it should start, when it matters (the start of a sung chorus, the music's biggest section, the last line before the end). An anchor is a wish with a reason, not an exact time; the editor snaps items to the music's bars afterwards and keeps what it can.

RULES
1. Length. The film must be as long as the TARGET, within 3%. Work it out item by item and keep the running total ("t"). If your total is short or long, fix it before answering: add or remove lines, narration or picture.
2. Chronological. The clips are in shooting order and the film follows it. Once you leave a clip you never come back to it. Inside a clip, "clip" items go in the order of their lines. Every clip has at most one run of consecutive items.
3. Every clip with usable picture should get at least a moment (3 s or more) unless there is a real reason to leave it out; list any clip you leave out under "skipped" with the reason. Never give a clip more picture than its usable seconds. Give more time to clips that matter to the story and little to the dull ones; do not spread time evenly.
4. Choose the runner's own words for what they carry: the story, emotion, humour, surprise, the stakes. Leave out filler ("um", "right so", false starts), repeats, and logistics that do not matter. Prefer unbroken stretches of about 4 to 20 seconds. Where the runner's words are good, let them do the telling: your narration must set up and link, never repeat or explain what a clip item says.
5. Narration (vo) is a real voice in the film, not a caption: aim for roughly 20 to 30 percent of the film, in short pieces that bridge the runner's recordings, set up what is coming, carry the passage of time and distance, and give the clips that have no speech a reason to be there. Keep each vo item under 40 words, so the film breathes between narration and the runner's voice. Honest, understated, dry; no cliches, no hype, no motivational lines, no exclamations. Short spoken sentences.
6. Facts. Base narration on the material: when you state a fact, take it from the clip's own time, distance, pace, place, what the camera sees, the runner's notes or the runner's own words, and do not state as fact what the material does not say; modest is better than invented. Never invent names, events or numbers. Put a fact only on the clip it belongs to: take times and distances from THAT clip's own track line (a clip 90% of the way through a long race is not "ten kilometres to go" if that is far more than a tenth of the distance left); the runner's notes describe the whole race, and what they say about the end belongs to the last clips only. Give each narration item a short "basis" (what it rests on: a short quote or a paraphrase of the runner's notes or words, or transcript line ids; paraphrase freely, only the user's MUST INCLUDE narration is used word for word): this is a FIRST DRAFT that the user will read, check and improve, and the basis helps them. Where a claim is shown by the runner's own words, prefer to put those words right next to the narration (a "clip" item just before or after it).
7. The runner's recordings are made on the move, sometimes days after the events they describe: what the runner says about "last night" is a recollection. Narrate in a way that keeps the timeline honest.
8. Build an arc: set the scene, let the race grow, make the hard middle felt, and give the ending room: the last part of the film should be the strongest and mostly in the runner's own words.
9. REVISING. When a CURRENT DRAFT is supplied, you are revising it, not starting again: keep every item the new constraints do not touch, with the same wording and the same choice of lines, and change only what the constraints and the target length require. Return the whole revised script.
10. THE MUSIC. The film is cut to the track you are given (its sections, bars and, when it has words, where it is sung). Let the music's energy follow the story: quiet sections for the slow, hard or reflective parts, the loud sections for the pushes and the ending. Narration over singing is normal and often unavoidable (the music is turned down under the voice): do not contort the script to avoid it, but where a line matters most, a gap in the singing is a good place for it. The song's words (rough recognition) tell you what it is about: use a hook where it meets the film (for example a line about not sleeping over the night), never to quote it.
11. FIXED PARTS. Anything the user has fixed (MUST INCLUDE, DO NOT USE, narration to use word for word, phrases never to say) is not up for discussion. Plan the film around the fixed parts: they leave a known amount of time for everything else.
'''

SCHEMA = '''Return ONE JSON object and nothing else:
{
  "title": "short film title",
  "story": "two or three sentences: the arc you chose and why",
  "items": [
    {"type": "vo",    "clip": "0004", "text": "narration the runner speaks over the picture of that clip", "words": 23, "basis": ["a short quote or paraphrase of what the narration rests on (the notes, the track line, the runner's words)", "or a transcript line id such as 0008.03"], "t": 12.5},
    {"type": "clip",  "clip": "0008", "from": "0008.01", "to": "0008.03", "why": "why these lines belong", "t": 31.0, "view": "close" (optional: mid | close | far)},
    {"type": "broll", "clip": "0009", "seconds": 3.5, "why": "what the picture shows / why it is worth a moment", "t": 34.5},
    {"type": "gap",   "clip": "G03", "kind": "map" or "flyover", "seconds": 12, "why": "what the gap holds and why it is shown", "t": 46.5, "anchor": {"film_s": 100, "why": "optional: the chorus starts here"}}
  ],
  "skipped": [{"clip": "0001", "why": "reason"}],
  "total_s": 246.0
}
"t" is the running total of the film's length in seconds AFTER that item, by your own arithmetic; "total_s" is the final total.'''


# ---------------------------------------------------------------- length and pace

def length_guide(pack, music_s=None, target_s=None):
    """(seconds, source): the film's length guide (D8). `target_s` if given, else the music's length from its first downbeat, else automatic: about 5 minutes, but never more than half the footage when there is
    little of it, and longer (up to the larger of half the footage and 10 minutes) as the runner's recorded speech justifies it."""
    if target_s: return float(target_s), 'target'
    if music_s: return float(music_s), 'music'
    cams = [c for c in pack['clips'] if not c.get('synthetic')]; total = sum(c['duration_s'] for c in cams); speech = sum(c['speech_s'] for c in cams); base = 300.0
    if 0.5 * total < base: base = max(0.5 * total, 60.0)
    hi = max(0.5 * total, 600.0)
    return round(min(base + 0.5 * speech if speech else base, hi, total), 0), 'automatic'


def narration_wpm(pack, vo_wpm=VO_WPM, max_speedup=VO_MAX_SPEEDUP, measured=None):
    """The pace the narration is counted at: the voice's own measured speed when there is one (`measured`, from the narration already spoken for this project), else the average of the normal voice-over pace and the runner's own speech rate in the recordings, never faster than the voice can be sped up."""
    if measured: return float(measured)
    own = (pack.get('race') or {}).get('speech_wpm')
    return round(min((vo_wpm + own) / 2.0, vo_wpm * max_speedup) if own else vo_wpm, 0)


# ---------------------------------------------------------------- the request

def build_messages(pack, target_s, wpm, pins=None, draft=None):
    text = SP.render(pack, marks=PN.marks(pins, pack) if pins else None); cons = PN.render_constraints(pins, pack, target_s, wpm)
    user = (f"TARGET FILM LENGTH: {target_s:.0f} seconds (accept {(1 - TOLERANCE) * target_s:.0f} to {(1 + TOLERANCE) * target_s:.0f}).\n"
            f"WORDS-PER-MINUTE for the voice-over: {wpm:.0f} (so {wpm / 60:.2f} words per second; 30 words take {30 * 60 / wpm:.1f} s).\n\n{text}\n\n")
    if cons: user += cons + '\n\n'
    if draft: user += 'CURRENT DRAFT (revise it as rule 9 says):\n' + json.dumps({k: draft.get(k) for k in ('title', 'story', 'items', 'skipped')}, indent=1) + '\n\n'
    return [dict(role='system', content=SYSTEM), dict(role='user', content=user + SCHEMA)], text


def tidy(d):
    """A draft with each item's `basis` a list of strings (models sometimes write one string, or leave it out); other fields untouched. Returns d."""
    for it in (d.get('items') or []) if isinstance(d, dict) else []:
        if isinstance(it, dict) and 'basis' in it:
            b = it['basis']; it['basis'] = [] if b is None else [str(x) for x in b] if isinstance(b, (list, tuple)) else [str(b)] if str(b).strip() else []
    return d


def parse(text):
    m = re.search(r'\{.*\}', text or '', re.S)
    for cand in ((m.group(0), re.sub(r',\s*([}\]])', r'\1', m.group(0))) if m else ()):
        for strict in (True, False):                                                                       # (strict=False lets a string hold a raw newline or tab, which models sometimes write)
            try: return tidy(json.loads(cand, strict=strict))
            except ValueError: pass
    return None


# ---------------------------------------------------------------- the checks

def span(it, pack):
    """(first line id, last line id) of a clip item, or None. A base id of a line that was split stands for its first (from) or last (to) piece."""
    a, b = PN.expand(str(it.get('from')), pack), PN.expand(str(it.get('to')), pack)
    return (a[0], b[-1]) if a and b else None


def on_beats(d, kind, beat_s):
    """An item's length as the film will have it: every window is a whole number of beats (b-roll rounds, everything else rounds up), so with the music's tempo known the writer's arithmetic uses these lengths, not the bare ones (33 items lose about a third of a beat each: ten seconds in a film)."""
    if not beat_s or d <= 0: return d
    n = round(d / beat_s) if kind == 'broll' else math.ceil(d / beat_s - 1e-9); return max(1, n) * beat_s


def check(script, pack, target_s, wpm):
    """(report, problems): durations are recomputed from the pack (the model's arithmetic is not used); `problems` are structural and drive a retry."""
    beat_s = 60.0 / pack['music']['bpm'] if (pack.get('music') or {}).get('bpm') else None
    clips = {c['label']: c for c in pack['clips']}; order = {c['label']: i for i, c in enumerate(pack['clips'])}; by = {l['id']: l for c in pack['clips'] for l in c['lines']}; pos = PN.index(pack)
    rows = []; anchors = []; items = (script or {}).get('items') or []; per = {}; total = 0.0; probs = []; last_clip = -1; seen_done = set(); cur = None; kinds = dict(vo=0.0, clip=0.0, broll=0.0, gap=0.0); words_total = 0; last_line = {}
    for n, it in enumerate(items, 1):
        t = it.get('type'); cl = norm_label(it.get('clip', '')); total_before = total
        if cl not in clips: probs.append(f'item {n}: no such clip {cl}'); continue
        if cl != cur:
            if cur is not None: seen_done.add(cur)
            if cl in seen_done: probs.append(f'item {n}: goes back to clip {cl} after leaving it')
            if order[cl] < last_clip: probs.append(f'item {n}: clip {cl} is out of shooting order')
            cur = cl; last_clip = max(last_clip, order[cl])
        if t == 'vo':
            w = SP.words(it.get('text', '')); d = w * 60.0 / wpm + VO_PAUSE_S; words_total += w
            if w > 45: probs.append(f'item {n}: vo of {w} words is too long (limit about 40)')
            if clips[cl].get('synthetic'): d = max(d, clips[cl]['duration_s'])                             # narration over a generated clip plays for the whole clip
        elif t == 'clip':
            if clips[cl].get('synthetic'): probs.append(f'item {n}: {cl} is a gap with no words: use a gap item'); continue
            sp = span(it, pack)
            if not sp: probs.append(f"item {n}: unknown line id {it.get('from')} or {it.get('to')}"); continue
            a, b = by[sp[0]], by[sp[1]]
            if SP.label_of_id(a['id']) != cl or SP.label_of_id(b['id']) != cl: probs.append(f'item {n}: lines are from another clip than {cl}'); continue
            if pos[sp[1]] < pos[sp[0]]: probs.append(f'item {n}: "to" is before "from"'); continue
            if last_line.get(cl, -1) >= pos[sp[0]]: probs.append(f'item {n}: lines of clip {cl} out of order or overlapping')
            last_line[cl] = pos[sp[1]]; d = b['t1'] - a['t0'] + PAD_S
        elif t == 'broll': d = float(it.get('seconds') or 0)
        elif t == 'gap':
            d = float(it.get('seconds') or 0); c = clips[cl]; kinds_ok = [o['kind'] for o in c.get('options') or []]
            if not c.get('synthetic'): probs.append(f'item {n}: {cl} is a camera clip, not a gap: a gap item names a gap such as G03'); continue
            if it.get('kind') not in kinds_ok: probs.append(f"item {n}: gap kind must be one of {', '.join(kinds_ok)}, not {it.get('kind')}")
            if not MIN_GAP_S <= d <= MAX_GAP_S: probs.append(f'item {n}: a gap plays for {MIN_GAP_S:g} to {MAX_GAP_S:g} seconds, not {d:g}')
        else: probs.append(f'item {n}: unknown type {t}'); continue
        if it.get('view') is not None:
            yv = clips[cl].get('you_views') or {}
            if t not in ('clip', 'broll'): probs.append(f'item {n}: only clip and broll items take a "view"')
            elif it['view'] not in ('mid', 'close', 'far'): probs.append(f"item {n}: view must be mid, close or far, not {it['view']}")
            elif yv.get(it['view'], 0.0) < 0.3: probs.append(f"item {n}: clip {cl} has no {it['view']} view of you (it has {', '.join(f'{k} {v * 100:.0f}%' for k, v in yv.items()) or 'none'} of its time): leave the view out or choose another")
        if it.get('anchor') is not None and not (isinstance(it['anchor'], dict) and isinstance(it['anchor'].get('film_s'), (int, float))): probs.append(f'item {n}: an anchor is {{"film_s": seconds, "why": "reason"}}')
        if isinstance(it.get('anchor'), dict) and isinstance(it['anchor'].get('film_s'), (int, float)): anchors.append((n, float(it['anchor']['film_s']), total_before))
        d = on_beats(d, t, beat_s); kinds[t] += d; total += d; per[cl] = per.get(cl, 0.0) + d; rows.append((n, t, cl, d, total))
    for n, want, start in anchors:
        if abs(want - start) > ANCHOR_SLACK_S: probs.append(f'item {n}: anchored at {want:.0f} s but by the real lengths of your items it starts at {start:.0f} s: the editor can only move it by stretching b-roll before it, so put the anchor where the items really land ({start:.0f} s), or add or remove about {abs(want - start):.0f} s of b-roll or narration before it')
    skipped = {norm_label(s.get('clip', '')) for s in (script or {}).get('skipped') or []}
    for lab, c in clips.items():
        if lab not in per and lab not in skipped and not c.get('synthetic'): probs.append(f'clip {lab} is neither used nor listed under skipped')
        if lab in per and per[lab] > c['usable_s'] + 0.5: probs.append(f"clip {lab} gets {per[lab]:.1f} s of picture but only {c['usable_s']} s is usable")
        if lab in per and per[lab] < 2.5: probs.append(f'clip {lab} gets only {per[lab]:.1f} s')
    if abs(total - target_s) > TOLERANCE * target_s: probs.append(f'the film is {total:.0f} s by the real durations but the target is {target_s:.0f} s (allowed {(1 - TOLERANCE) * target_s:.0f} to {(1 + TOLERANCE) * target_s:.0f}): ' + ('add' if total < target_s else 'remove') + f' about {abs(target_s - total):.0f} s')
    rep = dict(total_s=round(total, 1), target_s=round(target_s, 1), vo_s=round(kinds['vo'], 1), clip_s=round(kinds['clip'], 1), broll_s=round(kinds['broll'], 1), gap_s=round(kinds['gap'], 1), vo_words=words_total, claimed_total=(script or {}).get('total_s'),
               clips_used=len(per), clips_skipped=len(skipped), per_clip={k: round(v, 1) for k, v in sorted(per.items())}, rows=[(n, t, cl, round(d, 1), round(tot, 1)) for n, t, cl, d, tot in rows])
    return rep, probs


def resolve(script, pack, wpm):
    """Adds what the GUI shows to each item: `seconds` (recomputed), and for a clip item the `lines` it covers, their `text` and `refs` (the words of the transcript they are: {clip, si, w0, w1}). Returns the script."""
    by = {l['id']: l for c in pack['clips'] for l in c['lines']}; ids = list(PN.index(pack)); clip_of = {c['label']: c['clip'] for c in pack['clips']}; by_label = {c['label']: c for c in pack['clips']}
    for it in (script or {}).get('items') or []:
        if it.get('type') == 'vo': it['seconds'] = round(max(SP.words(it.get('text', '')) * 60.0 / wpm + VO_PAUSE_S, (by_label.get(norm_label(it.get('clip', ''))) or {}).get('duration_s', 0.0) if (by_label.get(norm_label(it.get('clip', ''))) or {}).get('synthetic') else 0.0), 1)
        elif it.get('type') in ('broll', 'gap'): it['seconds'] = round(float(it.get('seconds') or 0), 1)
        elif it.get('type') == 'clip':
            sp = span(it, pack)
            if sp:
                cover = ids[ids.index(sp[0]):ids.index(sp[1]) + 1]; it['lines'] = cover; it['text'] = ' '.join(by[i]['text'] for i in cover); it['refs'] = [dict(clip=clip_of[SP.label_of_id(i)], si=by[i].get('si'), w0=by[i].get('w0'), w1=by[i].get('w1')) for i in cover]; it['seconds'] = round(by[sp[1]]['t1'] - by[sp[0]]['t0'] + PAD_S, 1)
    return script


def used_line_ids(script, pack):
    """The transcript lines the draft plays (the GUI paints a white word yellow when its line is in here)."""
    out = set(); ids = list(PN.index(pack))
    for it in (script or {}).get('items') or []:
        if it.get('type') == 'clip':
            sp = span(it, pack)
            if sp: out.update(ids[ids.index(sp[0]):ids.index(sp[1]) + 1])
    return out


def director_notes(script, pack):
    """Advisory notes on how the script meets the music (after resolve(): items have `seconds`): anchors that the running time does not reach. (Narration over singing is not noted: it is normal, and the music is turned down under it.) They never force a retry."""
    notes = []; t = 0.0; used = {norm_label(it.get('clip', '')) for it in (script or {}).get('items') or []}
    open_gaps = [c['label'] for c in pack['clips'] if c.get('synthetic') and c.get('race_s', 0) >= 3600 and c['label'] not in used]
    if open_gaps: notes.append(f"{len(open_gaps)} gap(s) of an hour or more are not filled: {', '.join(open_gaps)}")
    for n, it in enumerate((script or {}).get('items') or [], 1):
        d = float(it.get('seconds') or 0.0); a, b = t, t + d
        anc = it.get('anchor')
        if isinstance(anc, dict) and isinstance(anc.get('film_s'), (int, float)) and abs(anc['film_s'] - a) > 6.0: notes.append(f"item {n}: anchored at {anc['film_s']:.0f} s but the running total starts it at {a:.0f} s; the editor will move it to the nearest bar it can")
        t = b
    return notes


# ---------------------------------------------------------------- writing

def write(pack, target_s, wpm, pins=None, draft=None, chat=None, retries=2, model='gemini-3.1-pro-preview', provider='gemini', temperature=0.7, thinking=None, log=print):
    """Ask the writer for a script and check it, sending the problems back up to `retries` times. `chat(messages, model, max_tokens, temperature, timeout=, provider=, thinking=)` is edit/llm_remote.chat
    (replaced in tests). Returns the draft document: the script (items resolved) plus the report, advisory warnings, the pins used and what each attempt cost."""
    if chat is None:
        from strata360.edit import llm_remote; chat = llm_remote.chat
    msgs, ptxt = build_messages(pack, target_s, wpm, pins, draft); runs = []; script = None; rep = {}; probs = []; best = None
    for attempt in range(retries + 1):
        r = chat(msgs, model, 30000, temperature, timeout=600, provider=provider, thinking=thinking); script = parse(r['text']) or {}
        if script:
            rep, probs = check(script, pack, target_s, wpm)
            if pins: probs = probs + PN.check(script, pack, pins)
        else: rep, probs = {}, ['not valid JSON']
        if script and (best is None or (len(probs), abs(rep.get('total_s', 0) - target_s)) < best[3]): best = (script, rep, probs, (len(probs), abs(rep.get('total_s', 0) - target_s)))         # the best valid attempt so far (fewest problems, then nearest the length), kept in case a later one is unusable
        runs.append(dict(attempt=attempt, seconds=r.get('seconds'), tokens=r.get('tokens'), total_s=rep.get('total_s'), problems=probs, **({} if script else dict(raw_head=(r['text'] or '')[:300])))); log(f"attempt {attempt}: {r.get('seconds')} s, total {rep.get('total_s')} s of {target_s:.0f}, {len(probs)} problem(s)")
        if not probs or attempt == retries: break
        table = ''
        if any(p.startswith('the film is') for p in probs) and rep.get('rows'):                   # the real length of every item, so the writer can see where the time goes
            table = '\nThe real length of each of your items (whole beats) and the running total:\n' + '\n'.join(f"  {n}. {t} {cl}: {d:.1f} s (total {tot:.1f} s)" for n, t, cl, d, tot in rep['rows']) + '\n'
        msgs = msgs + [dict(role='assistant', content=r['text'] or '(nothing)'), dict(role='user', content='Your script has these problems, checked against the real durations (your own arithmetic is not used):\n- ' + '\n- '.join(probs) + table + '\nReturn the corrected script as the same JSON object, nothing else: a single JSON object, no commentary.')]
    if not script and best is not None: script, rep, probs = best[:3]; log('the last attempt could not be read: keeping the closest earlier one')
    warns = GR.check(script, pack, ptxt) if script else []
    resolve(script, pack, wpm); warns = warns + (director_notes(script, pack) if script else [])
    return dict(version=1, prompt_version=PROMPT_VERSION, created=dt.datetime.now().isoformat(timespec='seconds'), model=model, provider=provider, target_s=round(target_s, 1), wpm=wpm, title=script.get('title'), story=script.get('story'),
                items=script.get('items') or [], skipped=script.get('skipped') or [], report=rep, problems=probs, warnings=warns, pins=pins or {}, revised=bool(draft), runs=runs)


# ---------------------------------------------------------------- the project's drafts and pins

def _dir(folder):
    from strata360.pipeline import config
    return os.path.join(config.race_dir(folder), 'script2')


def list_drafts(folder):
    d = _dir(folder); return sorted(f for f in os.listdir(d) if f.startswith('draft-') and f.endswith('.json')) if os.path.isdir(d) else []


def save_draft(folder, doc):
    """Writes script2/draft-<time>.json and removes all but the last KEEP drafts. Returns the file name."""
    d = _dir(folder); os.makedirs(d, exist_ok=True); name = 'draft-' + dt.datetime.now().strftime('%Y%m%d-%H%M%S-%f') + '.json'                        # microseconds: names sort in the order they were written
    p = os.path.join(d, name); json.dump(doc, open(p + '.tmp', 'w'), indent=1); os.replace(p + '.tmp', p)
    for old in list_drafts(folder)[:-KEEP]: os.remove(os.path.join(d, old))
    return name


def load_draft(folder, name=None):
    """The newest draft (or the named one) as a dict, or None."""
    names = list_drafts(folder); name = name or (names[-1] if names else None)
    if not name: return None
    try: return tidy(json.load(open(os.path.join(_dir(folder), os.path.basename(name)))))
    except (OSError, ValueError): return None


def load_pins(folder):
    try: return json.load(open(os.path.join(_dir(folder), 'pins.json')))
    except (OSError, ValueError): return {}


def save_pins(folder, pins):
    """The user's own pins (include / exclude lines, narration pins, never-say phrases); the notes' narration fields and the transcript marks are added when a draft is asked for."""
    d = _dir(folder); os.makedirs(d, exist_ok=True); keep = {k: pins.get(k) or [] for k in ('include', 'exclude', 'vo', 'vo_never')}; p = os.path.join(d, 'pins.json')
    json.dump(keep, open(p + '.tmp', 'w'), indent=1); os.replace(p + '.tmp', p); return keep
