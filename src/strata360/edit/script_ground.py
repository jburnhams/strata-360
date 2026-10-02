"""Checking that narration in a script is grounded in the material the writer was given (implementation plan V2): no invented facts.

Each "vo" item lists a `basis`: verbatim quotes copied from the material (or a transcript line id). check(script, pack, text) returns problems: a quote that is not in the material, a number that is nowhere in
the material, and a "N km to go" that does not match the clip's own distance."""
import re
from strata360.edit.script_pack import norm_label

UNITS = {w: i for i, w in enumerate('zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen'.split())}
TENS = {w: 10 * (i + 2) for i, w in enumerate('twenty thirty forty fifty sixty seventy eighty ninety'.split())}


def norm(t): return ' '.join(re.sub(r'[^a-z0-9. ]+', ' ', t.lower().replace('’', "'").replace("'", '')).split())


def numbers_in(text):
    """The numbers a sentence mentions: digits and spelled-out numbers up to the thousands ('a hundred and eleven' -> 111, 'forty-two' -> 42)."""
    out = [float(x) for x in re.findall(r'\d+(?:\.\d+)?', text)]; toks = re.findall(r"[a-z]+", re.sub(r'\d+(?:\.\d+)?', ' ', text.lower().replace('-', ' '))); cur = None; total = 0; seen = False
    def flush():
        nonlocal cur, total, seen
        if seen: out.append(float(total + (cur or 0)))
        cur = None; total = 0; seen = False
    for i, w in enumerate(toks):
        if w in UNITS: cur = (cur or 0) + UNITS[w]; seen = True
        elif w in TENS: cur = (cur or 0) + TENS[w]; seen = True
        elif w == 'hundred': cur = (cur or 1) * 100; total += cur; cur = None; seen = True
        elif w == 'thousand': cur = (cur or 1) * 1000; total += cur; cur = None; seen = True
        elif w in ('and', 'a') and seen and i + 1 < len(toks) and (toks[i + 1] in UNITS or toks[i + 1] in TENS or toks[i + 1] == 'hundred'): continue
        elif w == 'a' and not seen and i + 1 < len(toks) and toks[i + 1] in ('hundred', 'thousand'): seen = True; cur = 1
        else: flush()
    flush(); return out


def evidence_problems(script, pack, near=2):
    """A claim that rests on the runner's words must have those words in the film, in a clip item right next to the narration (within `near` items): [str]."""
    items = (script or {}).get('items') or []; lines = {l['id']: norm(l['text']) for c in pack['clips'] for l in c['lines']}; probs = []; pos = {i: n for n, i in enumerate(lines)}
    def covers(it, lid):
        if it.get('type') != 'clip': return False
        a, b = str(it.get('from')), str(it.get('to'))
        return a in pos and b in pos and a.split('.')[0] == lid.split('.')[0] and pos[a] <= pos[lid] <= pos[b]
    for n, it in enumerate(items):
        if it.get('type') != 'vo': continue
        need = set()
        for b in it.get('basis') or []:
            b = str(b).strip()
            if b in lines: need.add(b)
            else:
                q = norm(b)
                if len(q) >= 12: need |= {lid for lid, t in lines.items() if q in t}
        for lid in sorted(need):
            if not any(covers(items[k], lid) for k in range(max(n - near, 0), min(n + near + 1, len(items)))): probs.append(f"item {n + 1}: rests on the runner's line {lid} but that line is not in a clip item next to it")
    return probs


def check(script, pack, text, tol=1.5):
    """Problems with how well the narration is grounded: [str]. `text` is the material exactly as the writer saw it (script_pack.render)."""
    probs = []; hay = norm(text); ids = {l['id'] for c in pack['clips'] for l in c['lines']}; pack_nums = [float(x) for x in re.findall(r'\d+(?:\.\d+)?', text)]; clips = {c['label']: c for c in pack['clips']}
    total = (pack.get('race') or {}).get('km_total')
    for n, it in enumerate((script or {}).get('items') or [], 1):
        if it.get('type') != 'vo': continue
        basis = [b for b in it.get('basis') or [] if str(b).strip()]
        if not basis: probs.append(f'item {n}: narration has no basis (quote the material it rests on)')
        for b in basis:
            if str(b).strip() in ids: continue
            q = norm(str(b))
            if len(q) >= 6 and q not in hay: probs.append(f'item {n}: basis "{str(b)[:60]}" is not in the material (quotes must be copied word for word)')
        c = clips.get(norm_label(it.get('clip', ''))); t = it.get('text', '').lower(); derived = [total - c['km']] if (c and c.get('km') is not None and total) else []          # the distance still to run is race distance minus the clip's own
        for v in numbers_in(it.get('text', '')):
            if not any(abs(v - x) <= tol for x in pack_nums + derived) and v > 3: probs.append(f'item {n}: the number {v:g} is not in the material')
        for m in re.finditer(r"([\w\- ]{1,30}?)\s(?:kilomet(?:er|re)s?|km)\s(?:to go|left|from the (?:end|finish)|before the (?:end|finish))", t):
            vals = numbers_in(m.group(1))
            if vals and c and c.get('km') is not None and total and abs((total - c['km']) - vals[-1]) > max(6.0, 0.08 * total): probs.append(f"item {n}: says {vals[-1]:g} km to go but clip {c['label']} is at GPS km {c['km']} of the {total:g} km race ({total - c['km']:.0f} km to go)")
    return probs + evidence_problems(script, pack)
