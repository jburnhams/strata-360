"""What the user pins on the whole-race script (implementation plan K / V2), for the prompt and for checking the reply.

pins = {
  "include": ["0021.00..0021.04", "0023.27"],          # transcript lines the film MUST use (a line id, or first..last of one clip)
  "exclude": ["0004.03"],                              # transcript lines the film must NOT use
  "vo": [ {"id": "v1", "text": "...", "mode": "clip", "clip": "0004"},      # narration the film MUST contain, word for word, inside that clip's run
          {"id": "v2", "text": "...", "mode": "ordered"},                  # must appear, in this order relative to the other ordered / clip pins, anywhere
          {"id": "v3", "text": "...", "mode": "anywhere"} ] }               # must appear somewhere; no order

render_pack_marks(pins, pack) -> {line id: 'must' | 'never'};  render_constraints(...) -> the prompt section;  check(script, pack, pins) -> problems."""
import re
from strata360.edit.script_pack import norm_label

MODES = ('clip', 'ordered', 'anywhere')


def index(pack):
    """{line id: position in the whole film's line order}."""
    return {l['id']: n for n, l in enumerate(l for c in pack['clips'] for l in c['lines'])}


def _label(i): return i.split('.')[0]


def expand(spec, pack):
    """'0023.27', '0023.27.2' or '0023.27..0023.29' -> the line ids in order. A base id whose line was split by marks stands for all its pieces. Unknown ids give []."""
    ids = list(index(pack))
    if '..' in spec:
        a, b = spec.split('..'); ia = next((n for n, i in enumerate(ids) if i == a or i.startswith(a + '.')), None); ib = max((n for n, i in enumerate(ids) if i == b or i.startswith(b + '.')), default=None)
        return [] if ia is None or ib is None else [i for i in ids[ia:ib + 1] if _label(i) == _label(a)]
    return [i for i in ids if i == spec or i.startswith(spec + '.')]


def marks(pins, pack):
    """{line id: 'must' | 'never'}: the user's marks on the transcript (carried by the pack's lines) and the pins' include and exclude lists; never wins over must."""
    out = {l['id']: l['mark'] for c in pack['clips'] for l in c['lines'] if l.get('mark') in ('must', 'never')}
    for s in (pins or {}).get('include') or []:
        for i in expand(s, pack): out[i] = 'must'
    for s in (pins or {}).get('exclude') or []:
        for i in expand(s, pack): out[i] = 'never'
    return out


def norm(t): return re.sub(r'[^a-z0-9 ]+', '', t.lower().replace('’', "'").replace("'", '')).split()


def vo_pins(pins): return [p for p in (pins or {}).get('vo') or [] if p.get('text', '').strip()]


def seconds_summary(pins, pack, wpm):
    """Time the pinned material takes: (clip seconds of must-include lines as played, narration seconds of the pinned voice-over)."""
    by = {l['id']: l for c in pack['clips'] for l in c['lines']}; pos = index(pack); m = marks(pins, pack); must = sorted((i for i, v in m.items() if v == 'must'), key=pos.get); runs = []
    for i in must:
        if runs and _label(runs[-1][-1]) == _label(i) and pos[i] - pos[runs[-1][-1]] <= 1: runs[-1].append(i)
        else: runs.append([i])
    clip_s = sum(by[r[-1]]['t1'] - by[r[0]]['t0'] + 0.18 for r in runs); vo_s = sum(len(norm(p['text'])) * 60.0 / wpm + 0.25 for p in vo_pins(pins))
    return round(clip_s, 1), round(vo_s, 1)


def render_constraints(pins, pack, target_s, wpm):
    """The prompt section for the pins ('' when there are none)."""
    m0 = marks(pins, pack)
    if not (m0 or vo_pins(pins) or (pins or {}).get('vo_never')): return ''
    L = ['THE USER HAS FIXED PART OF THE SCRIPT. These are hard rules, stronger than your own taste:']; m = marks(pins, pack)
    if any(v == 'must' for v in m.values()):
        L.append('- Transcript lines tagged MUST INCLUDE in the clip list above must all be used, inside "clip" items, whole and in order. You may add neighbouring lines around them so they make sense and flow.')
    if any(v == 'never' for v in m.values()): L.append('- Transcript lines tagged DO NOT USE must not appear in any "clip" item (not even inside a range: choose the ranges to avoid them).')
    vp = vo_pins(pins)
    if vp:
        L.append('- Narration the user has written (MUST INCLUDE, word for word, each as its own "vo" item or inside one; you may add your own narration around them):')
        for p in vp:
            how = {'clip': f"at about the moment of clip {p.get('clip')}: inside it, or in the item just before or after it if there is not room", 'ordered': 'anywhere, but keep the order of the numbered pins (v1 before v2 ...) relative to the other ordered or clip-anchored pins', 'anywhere': 'anywhere you think best, no order'}[p.get('mode', 'anywhere')]
            L.append(f"    [{p['id']}] ({how}) \"{p['text'].strip()}\"")
    for ph in (pins or {}).get('vo_never') or []: L.append(f'- The narration must never say: "{ph}" (nor a close rewording).')
    cs, vs = seconds_summary(pins, pack, wpm)
    L.append(f"- The fixed material takes about {cs:.0f} s of the runner's recorded speech and {vs:.0f} s of narration: {cs + vs:.0f} s of the {target_s:.0f} s target. The remaining {max(target_s - cs - vs, 0):.0f} s is yours to fill with the other clips, b-roll and your own narration; plan the story around the fixed pieces.")
    return '\n'.join(L)


def check(script, pack, pins):
    """Problems with the user's pins in a script: [str]."""
    probs = []; items = (script or {}).get('items') or []; m = marks(pins, pack); used = set(); clip_of = {}; pos = index(pack)
    for it in items:
        if it.get('type') == 'clip':
            for i in expand(f"{it.get('from')}..{it.get('to')}", pack): used.add(i)
    for i, v in sorted(m.items(), key=lambda kv: pos.get(kv[0], 0)):
        if v == 'must' and i not in used: probs.append(f'MUST INCLUDE line {i} is not in any clip item')
        if v == 'never' and i in used: probs.append(f'DO NOT USE line {i} is inside a clip item')
    vpos = {}
    for p in vo_pins(pins):
        want = norm(p['text']); hit = None
        for n, it in enumerate(items):
            if it.get('type') == 'vo':
                got = norm(it.get('text', ''))
                if any(got[k:k + len(want)] == want for k in range(len(got) - len(want) + 1)): hit = n; clip_of[p['id']] = norm_label(it.get('clip', '')); break
        if hit is None: probs.append(f"user narration [{p['id']}] is missing or reworded (it must appear word for word)"); continue
        vpos[p['id']] = hit
        if p.get('mode') == 'clip':                                                 # the moment of the clip, not its exact run: the item before or after may carry it when there is not time inside
            want_c = norm_label(p.get('clip', '')); homes = [k for k, x in enumerate(items) if norm_label(x.get('clip', '')) == want_c]
            if homes and min(abs(hit - k) for k in homes) > 1: probs.append(f"user narration [{p['id']}] belongs at the moment of clip {p.get('clip')} (inside it or in the item just before or after it) but is in clip {clip_of[p['id']]}, further away")
    for ph in (pins or {}).get('vo_never') or []:
        w = norm(ph)
        for n, it in enumerate(items, 1):
            got = norm(it.get('text', '')) if it.get('type') == 'vo' else []
            if w and any(got[k:k + len(w)] == w for k in range(len(got) - len(w) + 1)): probs.append(f'item {n}: says "{ph}", which the user marked never to say')
    seq = [p for p in vo_pins(pins) if p.get('mode') in ('ordered', 'clip') and p['id'] in vpos]
    for a, b in zip(seq, seq[1:]):
        if vpos[a['id']] > vpos[b['id']]: probs.append(f"user narration [{a['id']}] must come before [{b['id']}]")
    return probs


def notes_pins(notes, pack):
    """The narration pins written in the notes' "voice-over MUST INCLUDE" fields (pipeline/notes.py): one per line. A clip's lines are anchored at about that clip's moment in the film (in its item or the one next to it); the folder's lines are in the order written
    (mode 'ordered') or anywhere, as its switch says."""
    vo = (notes or {}).get('vo_must') or {}; labels = {c['clip']: c['label'] for c in pack['clips']}; out = []
    def lines(t): return [x.strip() for x in (t or '').splitlines() if x.strip()]
    for n, t in enumerate(lines(vo.get('folder')), 1): out.append(dict(id=f'n{n}', text=t, mode='ordered' if vo.get('folder_ordered', True) else 'anywhere'))
    for cid, txt in (vo.get('clips') or {}).items():
        lab = labels.get(cid)
        if lab is None: continue
        for n, t in enumerate(lines(txt), 1): out.append(dict(id=f'{lab}-{n}', text=t, mode='clip', clip=lab))
    return out


def project_pins(notes, pack, base=None):
    """The pins for a revise: the user's own `base` pins plus the narration written in the notes (the transcript marks travel in the pack's lines)."""
    pins = dict(base or {}); pins['vo'] = list(pins.get('vo') or []) + notes_pins(notes, pack); return pins
