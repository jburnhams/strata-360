"""The context pack for the whole-race script writer (implementation plan K / V2): everything the writer should know about every clip, in shooting order, as plain data and as text for a prompt.

build(folder) -> dict(race=..., clips=[...]); render(pack) -> str.
Per clip: a short label (the clip number, 0023), local time and race facts from the track, the length and usable footage, the place, what the scene model saw, the runner's note, and the wearer's own words as numbered
LINES with exact times (the word alignment where it passed its checks, else the recogniser's times shifted by its usual 0.15 s lag). Nothing but text leaves the machine: no audio, pictures or faces."""
import json, os, re

WHISPER_LAG_S = 0.15


def words(s): return len(re.findall(r"[\w'’-]+", s))


def norm_label(x):
    """A clip label as the script and the pack write it: a camera clip's number padded to four digits (`23` -> `0023`), a generated clip's name as it is (`g03` -> `G03`)."""
    x = str(x or '').strip(); return x.zfill(4) if x.isdigit() else x.upper()


def label_of(clip_id):
    m = re.search(r'_(\d{4})_[A-Z]$', clip_id); return m.group(1) if m else clip_id[-6:]


def label_of_id(line_id): return line_id.split('.')[0]


def merge(iv, gap=1e-6):
    out = []
    for a, b in sorted(iv):
        if out and a <= out[-1][1] + gap: out[-1] = (out[-1][0], max(out[-1][1], b))
        else: out.append((a, b))
    return out


def transcript_lines(cdir, label):
    """The wearer's speech as lines [{id, t0, t1, text, words, lang, mark, si, w0, w1}] with exact times (`si` the segment, `w0`..`w1` the recognised words it covers, end exclusive); flagged and empty segments are left out. A line is split wherever the user's mark changes (MUST USE, NEVER USE,
    none; edit/../analysis/transcript_marks.py), so every line has one state: the pieces get ids `<clip>.<segment>.<n>`; an unsplit line is `<clip>.<segment>`. `mark` is 'must', 'never' or None."""
    from strata360.analysis import transcript_edits as TE, transcript_marks as TM
    if not os.path.exists(os.path.join(cdir, 'transcript.json')): return []
    tr = TE.load_effective(cdir); mk = TM.states(cdir); ap = os.path.join(cdir, 'alignment.json')
    al = {a['index']: a for a in (json.load(open(ap)).get('segments') or []) if a} if os.path.exists(ap) else {}; out = []

    def span(ws, aw, a, b):
        got = []
        for k in range(a, b):
            x = aw[k] if k < len(aw) else None
            got.append((x['a0'], x['a1']) if x and x.get('ok') and x.get('a0') is not None and x.get('a1') is not None else (ws[k]['t0'] + WHISPER_LAG_S, ws[k]['t1'] + WHISPER_LAG_S))
        return min(g[0] for g in got), max(g[1] for g in got)

    for si, s in enumerate(tr['segments']):
        text = (s.get('text_en') or s.get('text') or '').strip()
        if not text or s.get('flags'): continue
        ws = s.get('words') or []; aw = (al.get(si) or {}).get('words') or []; ms = [mk.get((si, k)) for k in range(len(ws))]
        foreign = s.get('lang', 'en') != 'en' and s.get('text_en') and s['text_en'].strip() != (s.get('text') or '').strip()
        w = [x for x in aw if x.get('ok') and x.get('a0') is not None and x.get('a1') is not None]
        whole_t = (min(x['a0'] for x in w), max(x['a1'] for x in w)) if w else (s['t0'] + WHISPER_LAG_S, s['t1'] + WHISPER_LAG_S)
        if foreign or not ws or len(set(ms)) <= 1:                                       # one state: the whole line, as before
            state = 'never' if 'never' in ms else 'must' if 'must' in ms else None
            out.append(dict(id=f'{label}.{si:02d}', t0=round(whole_t[0], 2), t1=round(whole_t[1], 2), text=text, words=words(text), lang=s.get('lang', 'en'), mark=state, si=si, w0=0, w1=len(ws))); continue
        groups = []; a = 0
        for k in range(1, len(ws) + 1):
            if k == len(ws) or ms[k] != ms[a]: groups.append((a, k, ms[a])); a = k
        for n, (a, b, state) in enumerate(groups, 1):
            t = ' '.join(x['w'].strip() for x in ws[a:b] if x['w'].strip()); t0, t1 = span(ws, aw, a, b)
            out.append(dict(id=f'{label}.{si:02d}.{n}', t0=round(t0, 2), t1=round(t1, 2), text=t, words=words(t), lang=s.get('lang', 'en'), mark=state, si=si, w0=a, w1=b))
    return out


def scene_summary(cdir):
    p = os.path.join(cdir, 'scenes.json')
    if not os.path.exists(p): return {}
    items = [i for i in json.load(open(p)).get('items') or [] if i.get('ok')]
    if not items: return {}
    from collections import Counter
    def top(k, n=3): return [v for v, _ in Counter(i[k] for i in items if i.get(k) and i[k] != 'unknown').most_common(n)]
    desc = []
    for i in items:
        if i['view'] == 'front' and i.get('description') and i['description'] not in desc: desc.append(i['description'])
    step = max(len(desc) // 3, 1)
    return dict(settings=top('setting'), weather=top('weather', 2), lighting=top('lighting', 2), crowd=top('crowd', 1), seen=desc[::step][:3], lens_problems=[v for v in top('lens_problems', 2) if v != 'none'])


def synthetic_clips(folder, tr, tz):
    """The generated clips that are rendered (edit/synthetic.py) as pack clips: a label like `G03`, a length in the film, the stretch of the race they cover, and no words. They are picture only."""
    import datetime as dt
    from strata360.edit import synthetic as SY
    from strata360.gps import context as X
    out = []
    for c in SY.load(folder)['clips']:
        if c.get('status') != 'ready' or not c.get('file'): continue
        t0 = dt.datetime.fromisoformat(c['t0'].replace('Z', '+00:00')).timestamp(); t1 = dt.datetime.fromisoformat(c['t1'].replace('Z', '+00:00')).timestamp()
        d = dict(label=norm_label(c['id']), clip=c['id'], start_utc=c['t0'], duration_s=round(c['seconds'], 1), usable_s=round(c['seconds'], 1), usable=[(0.0, round(c['seconds'], 1))], synthetic=True, race_s=c['duration_s'], speedup=c['speedup'],
                 scene={}, note='', lines=[], speech_s=0.0, speech_words=0)
        if tr is not None:
            ctx = X.context_at(tr, t0, t1, tz); d['track'] = X.describe(ctx)
            if ctx.get('covered'): d['km'] = ctx.get('distance_km'); d['elapsed_h'] = ctx.get('elapsed_h'); d['local'] = f"{ctx['local_date']} {ctx['local_time']}"
        out.append(d)
    return out


def build(folder, tz=None):
    import datetime as dt
    from strata360.pipeline import config, notes as N, meta as MT
    from strata360.edit import project as PJ
    from strata360.gps import track, context as X
    cfg = config.load(folder); rd = config.race_dir(folder); notes = N.load(folder); tp = config.track_path(folder, cfg); tr = track.load(tp) if tp else None; tz = tz or cfg.get('timezone', 'Europe/Brussels')
    clips, missing = PJ.load_clips(folder); out = []
    for c in sorted(clips, key=lambda c: c['start_utc']):
        cdir = os.path.join(rd, 'clips', c['id']); label = label_of(c['id']); t0 = dt.datetime.fromisoformat(c['start_utc'].replace('Z', '+00:00')).timestamp(); dur = float(c['duration_s'])
        usable = merge([(x['start_s'], x['end_s']) for x in c['candidates']]); usable_s = sum(b - a for a, b in usable)
        d = dict(label=label, clip=c['id'], start_utc=c['start_utc'], duration_s=round(dur, 1), usable_s=round(usable_s, 1), usable=[(round(a, 1), round(b, 1)) for a, b in usable])
        if tr is not None:
            ctx = X.context_at(tr, t0, t0 + dur, tz); d['track'] = X.describe(ctx)
            if ctx.get('covered'): d['km'] = ctx.get('distance_km'); d['elapsed_h'] = ctx.get('elapsed_h'); d['local'] = f"{ctx['local_date']} {ctx['local_time']}"
        pl = os.path.join(cdir, 'places.json')
        if os.path.exists(pl):
            pj = json.load(open(pl))
            if pj.get('covered') and pj.get('summary'): d['place'] = pj['summary']['text'] + (f", on {pj['summary']['road']}" if pj['summary'].get('road') else '')
        d['scene'] = scene_summary(cdir); d['note'] = (notes.get('clips', {}).get(c['id']) or '').strip(); d['lines'] = transcript_lines(cdir, label)
        d['speech_s'] = round(sum(l['t1'] - l['t0'] for l in d['lines']), 1); d['speech_words'] = sum(l['words'] for l in d['lines']); out.append(d)
    out = sorted(out + synthetic_clips(folder, tr, tz), key=lambda c: c['start_utc'])
    speech_s = sum(c['speech_s'] for c in out); speech_w = sum(c['speech_words'] for c in out)
    race = dict(note=(notes.get('folder') or '').strip(), details=MT.describe(folder), km_total=MT.load(folder).get('distance_km'), speech_wpm=round(speech_w / speech_s * 60) if speech_s else None, clips_missing=missing)
    if tr is not None: race['track'] = f"the GPS recorded {tr['dist'][-1] / 1000:.0f} km over {(tr['t'][-1] - tr['t'][0]) / 3600:.0f} hours (the runner's own elapsed time: not a time limit, and the distance can exceed the official one because of detours). The km in each clip's track line is GPS distance from the start"
    return dict(race=race, clips=out)


def render(pack, with_usable=False, marks=None):
    """The pack as prompt text. `marks` ({line id: 'must' | 'never'}, edit/script_pins.py) tags the lines the user fixed."""
    marks = marks or {}; r = pack['race']; L = ['THE RACE']
    if r.get('details'): L.append(r['details'])
    if r.get('track'): L.append('Track: ' + r['track'])
    if r.get('note'): L += ["The runner's own notes about the race:", r['note']]
    L += ['', f"CLIPS (all {len(pack['clips'])}, in shooting order; the film follows this order)"]
    for c in pack['clips']:
        L.append(f"\n=== CLIP {c['label']}: {c['duration_s']} s long, {c['usable_s']} s usable" + (f" | {c['local']}" if c.get('local') else '') + (f" | km {c['km']}" if c.get('km') is not None else '') + ' ===')
        if c.get('synthetic'): L.append(f"NO FOOTAGE: a generated animated map of the route, {c['race_s'] / 3600:.1f} h of the race in {c['duration_s']} s (x{c['speedup']:g}). Picture only: use it as b-roll or under narration; it has no sound and no words.")
        if c.get('track'): L.append('track: ' + c['track'])
        if c.get('place'): L.append('place: ' + c['place'])
        s = c.get('scene') or {}
        if s: L.append('camera sees: ' + '; '.join(x for x in [', '.join(s.get('settings') or []), ('weather ' + ', '.join(s['weather'])) if s.get('weather') else '', ('lighting ' + ', '.join(s['lighting'])) if s.get('lighting') else '', ('crowd ' + ', '.join(s['crowd'])) if s.get('crowd') and s['crowd'] != ['none'] else '', ('; '.join(s['seen'])) if s.get('seen') else '', ('lens problems: ' + ', '.join(s['lens_problems'])) if s.get('lens_problems') else ''] if x))
        if c.get('note'): L.append("runner's note: " + c['note'])
        if with_usable and c.get('usable'): L.append('usable stretches (s): ' + ', '.join(f'{a}-{b}' for a, b in c['usable']))
        if c['lines']:
            L.append(f"the runner says ({c['speech_s']} s of speech, {c['speech_words']} words):")
            for l in c['lines']: L.append(f"  [{l['id']}] {l['t0']:.1f}-{l['t1']:.1f} s ({l['t1'] - l['t0']:.1f} s): {l['text']}" + ('' if l['lang'] == 'en' else f" (translated from {l['lang']})") + {'must': '   <<< MUST INCLUDE', 'never': '   <<< DO NOT USE'}.get(marks.get(l['id']), ''))
        else: L.append('the runner says nothing in this clip.')
    return '\n'.join(L)
