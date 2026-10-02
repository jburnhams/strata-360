"""Experiment: ask Gemini (paid key) for a whole-race script and check it.  PYTHONPATH=src python scripts/script_exp/run.py FOLDER OUT.json [--prompt v1] [--target 246] [--wpm 180] [--think low] [--retries 1]
The checker recomputes every length itself (the model's arithmetic is not trusted) and, with --retries, sends the problems back once or twice."""
import argparse, json, os, re, sys, time
sys.path.insert(0, os.path.dirname(__file__))
from prompts import VERSIONS
from strata360.edit import script_pack as SP, script_pins as PN, script_ground as GR, llm_remote as LR

PAD_S = 0.18; VO_PAUSE_S = 0.25


def parse(text):
    m = re.search(r'\{.*\}', text, re.S)
    for cand in ((m.group(0), re.sub(r',\s*([}\]])', r'\1', m.group(0))) if m else ()):
        try: return json.loads(cand)
        except ValueError: pass
    return None


def check(script, pack, target_s, wpm):
    """(report, problems): durations recomputed from the pack."""
    clips = {c['label']: c for c in pack['clips']}; order = {c['label']: i for i, c in enumerate(pack['clips'])}; lines = {l['id']: l for c in pack['clips'] for l in c['lines']}
    items = script.get('items') or []; per = {}; pos = {i: n for n, i in enumerate(lines)}; total = 0.0; probs = []; last_clip = -1; seen_done = set(); cur = None; kinds = dict(vo=0.0, clip=0.0, broll=0.0); words_total = 0; last_line = {}
    for n, it in enumerate(items, 1):
        t = it.get('type'); cl = str(it.get('clip', '')).zfill(4)
        if cl not in clips: probs.append(f'item {n}: no such clip {cl}'); continue
        if cl != cur:
            if cur is not None: seen_done.add(cur)
            if cl in seen_done: probs.append(f'item {n}: goes back to clip {cl} after leaving it')
            if order[cl] < last_clip: probs.append(f'item {n}: clip {cl} is out of shooting order')
            cur = cl; last_clip = max(last_clip, order[cl])
        if t == 'vo':
            w = SP.words(it.get('text', '')); d = w * 60.0 / wpm + VO_PAUSE_S; words_total += w
            if it.get('words') is not None and abs(int(it['words']) - w) > 2: probs.append(f"item {n}: says {it['words']} words but has {w}")
            if w > 45: probs.append(f'item {n}: vo of {w} words is too long (limit about 40)')
        elif t == 'clip':
            a, b = lines.get(it.get('from')), lines.get(it.get('to'))
            if not a or not b: probs.append(f"item {n}: unknown line id {it.get('from')} or {it.get('to')}"); continue
            if a['id'].split('.')[0] != cl or b['id'].split('.')[0] != cl: probs.append(f'item {n}: lines are from another clip than {cl}'); continue
            if b['t1'] < a['t0']: probs.append(f'item {n}: "to" is before "from"'); continue
            if last_line.get(cl, -1) >= pos[a['id']]: probs.append(f"item {n}: lines of clip {cl} out of order or overlapping")
            last_line[cl] = pos[b['id']]; d = b['t1'] - a['t0'] + PAD_S
        elif t == 'broll': d = float(it.get('seconds') or 0)
        else: probs.append(f'item {n}: unknown type {t}'); continue
        kinds[t] += d; total += d; per[cl] = per.get(cl, 0.0) + d
    skipped = {str(s.get('clip', '')).zfill(4) for s in script.get('skipped') or []}
    for lab, c in clips.items():
        if lab not in per and lab not in skipped: probs.append(f'clip {lab} is neither used nor listed under skipped')
        if lab in per and per[lab] > c['usable_s'] + 0.5: probs.append(f"clip {lab} gets {per[lab]:.1f} s of picture but only {c['usable_s']} s is usable")
        if lab in per and per[lab] < 2.5: probs.append(f'clip {lab} gets only {per[lab]:.1f} s')
    if abs(total - target_s) > 0.03 * target_s: probs.append(f'the film is {total:.0f} s by the real durations but the target is {target_s:.0f} s (allowed {0.97 * target_s:.0f} to {1.03 * target_s:.0f}): ' + ('add' if total < target_s else 'remove') + f' about {abs(target_s - total):.0f} s')
    rep = dict(total_s=round(total, 1), target_s=target_s, vo_s=round(kinds['vo'], 1), clip_s=round(kinds['clip'], 1), broll_s=round(kinds['broll'], 1), vo_words=words_total, claimed_total=script.get('total_s'),
               clips_used=len(per), clips_skipped=len(skipped), per_clip={k: round(v, 1) for k, v in sorted(per.items())})
    return rep, probs


def sig(it): return (it.get('type'), str(it.get('clip')), it.get('text') if it.get('type') == 'vo' else (it.get('from'), it.get('to')) if it.get('type') == 'clip' else round(float(it.get('seconds') or 0)))


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('folder'); ap.add_argument('out'); ap.add_argument('--prompt', default='v1'); ap.add_argument('--target', type=float, default=246.0); ap.add_argument('--wpm', type=float, default=180.0)
    ap.add_argument('--think', default=None); ap.add_argument('--pins'); ap.add_argument('--distance', type=float, help='official race distance in km (for this run only; the app stores it in the film details)'); ap.add_argument('--draft', help='a previous output file: its script is the current draft to revise'); ap.add_argument('--retries', type=int, default=1); ap.add_argument('--temp', type=float, default=0.7); a = ap.parse_args()
    pack = SP.build(a.folder)
    if a.distance: pack['race']['km_total'] = a.distance; pack['race']['details'] += f" Official race distance: {a.distance:g} km (the runner's GPS track can read longer: detours and wrong turns add distance)."
    system, user = VERSIONS[a.prompt]; pins = json.load(open(a.pins)) if a.pins else None; draft = json.load(open(a.draft))['script'] if a.draft else None
    kw = dict(constraints=PN.render_constraints(pins, pack, a.target, a.wpm), draft=json.dumps(draft, indent=1) if draft else None) if a.prompt != 'v1' else {}
    ptxt = SP.render(pack, marks=PN.marks(pins, pack) if pins else None)
    msgs = [dict(role='system', content=system), dict(role='user', content=user(ptxt, a.target, a.wpm, len(pack['clips']), **kw))]
    runs = []; script = None
    for attempt in range(a.retries + 1):
        t0 = time.time(); r = LR.chat(msgs, 'gemini-3.1-pro-preview', 30000, a.temp, timeout=600, provider='gemini', thinking=a.think); script = parse(r['text']) or {}
        rep, probs = check(script, pack, a.target, a.wpm) if script else ({}, ['not valid JSON'])
        if script and pins: probs = probs + PN.check(script, pack, pins)
        warns = GR.check(script, pack, ptxt) if script and a.prompt in ('v3', 'v4') else []
        if a.prompt == 'v3': probs = probs + warns; warns = []                              # v3 made grounding a hard rule; v4 only reports it (advisory: the user reviews the draft)
        if script and draft: rep['kept_from_draft'] = sum(1 for x in script.get('items') or [] if any(sig(x) == sig(y) for y in draft.get('items') or [])); rep['draft_items'] = len(draft.get('items') or [])
        runs.append(dict(attempt=attempt, seconds=r['seconds'], tokens=r['tokens'], report=rep, problems=probs, warnings=warns, raw=r['text'] if not script else None)); print(f"attempt {attempt}: {r['seconds']} s, tokens {r['tokens']}, total {rep.get('total_s')} s / target {a.target:.0f}, {len(probs)} problem(s)", flush=True)
        for p in probs[:8]: print('   -', p)
        for w in warns[:8]: print('   ~ warning:', w)
        if not probs or attempt == a.retries: break
        msgs += [dict(role='assistant', content=r['text']), dict(role='user', content='Your script has these problems, checked against the real durations (your own arithmetic is not used):\n- ' + '\n- '.join(probs) + '\nReturn the corrected script as the same JSON object, nothing else.')]
    json.dump(dict(prompt=a.prompt, target=a.target, wpm=a.wpm, script=script, runs=runs), open(a.out, 'w'), indent=1)
main()
