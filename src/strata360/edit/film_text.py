"""Word art through the film: short cards of lettering over the footage, a progress update ("Day 2, kilometre 84") or a partial quote from what was said (the runner's speech or the voice-over).

The local models make OPTIONS and the planner decides, because a card is only worth having where it does not get in the way of the shot:

  options(folder, plan)       the text model proposes cards (the words, each rated for how worth showing it is); the vision model then looks at the film at that moment and rates the SHOT: how exciting it is, how much a card would
                              cover or distract from it, where the calm part of the frame is. Written to <project>/strata360/film_text_options.json, every option with both ratings and a verdict (good, ok, avoid).
  pick(options, length)       the planner's choice among them: the best by combined score, none on a moment the shot rates "avoid", none too close together, not too many (the density is a setting). Returned as the plan's `text_cards`.
  design_cards(...)           the vision model designs the word art of the chosen cards (edit/title_design.py); written with the choice to film_text.json, which the preview and the final film draw (render/captions.py).

The model cannot invent: a progress card may only use numbers the race track gives for that moment (day, kilometre, percent, local time, elapsed hours, altitude), and a quote must be a run of the words of the candidate it names."""
import json, os, re, time
import numpy as np

CARD_S = dict(progress=3.4, quote=2.6)
MIN_GAP = 12.0                                   # seconds between chosen cards
EDGE = 8.0                                       # none in the first and last seconds (the opening and the ending have their own title)
SAFE_ZONE = (0.03, 0.04, 0.97, 0.80)               # where a card may sit: the race overlay has the edges and the top row, the subtitles the bottom
OPTIONS = 24                                     # how many options the text model is asked for


def _norm(t): return re.sub(r"[^a-z0-9' ]+", ' ', str(t).lower()).split()


def facts_for(folder, plan, tz='Europe/Brussels'):
    """[{t, clip, day, local_time, km, percent, elapsed_h, altitude_m, daylight, gradient_pct}] one for each footage segment of the plan: the race track's facts at that moment."""
    import datetime as dt
    from strata360.pipeline import config
    from strata360.gps import track as TRK, context as X
    tp = config.track_path(folder, config.load(folder)); out = []
    if not tp: return out
    tr = TRK.load(tp)
    for g in plan['segments']:
        if g.get('synthetic') or not g.get('utc_start'): continue
        t0 = dt.datetime.fromisoformat(g['utc_start'].replace('Z', '+00:00')).timestamp(); c = X.context_at(tr, t0, t0 + float(g['dur_s']), tz)
        if not c.get('covered'): continue
        out.append(dict(t=round(float(g['film_start_s']), 1), clip=g['clip'][-9:], day=c['race_day'], local_time=c['local_time'], km=c['distance_km'], percent=c['percent_of_distance'], elapsed_h=c['elapsed_h'], altitude_m=c['altitude_m'], daylight=c['daylight'], gradient_pct=c['gradient_pct']))
    return out


def quotes_for(folder, plan):
    """[{id, t, kind, text}] the candidate quotes: the cues of the subtitle track that are at least 4 words, in film time."""
    from strata360.render import captions as CP
    out = []
    for i, c in enumerate(CP.build_cues(folder, plan)):
        if len(c['text'].split()) >= 4: out.append(dict(id=f'q{i}', t=round(c['t0'], 1), kind=c['kind'], text=c['text']))
    return out


PROMPT = """You are choosing candidate on-screen text cards for a film about an ultramarathon (a 367 km race run with no sleep over several days), {length:.0f} seconds long. Cards are short lettering over the footage: progress updates and partial quotes. A planner will pick among your options, so give the most promising ones, each rated.

PROGRESS FACTS (film time in seconds; the race track's facts for the footage at that moment):
{facts}

QUOTE CANDIDATES (id, film time, who: speech = the runner or someone near them, vo = the voice-over):
{quotes}

Give up to {n} options, best first, spread over the film, never in the first or last {edge:.0f} seconds. Mix the two kinds. Rules:
- A progress card uses only numbers from the facts for the moment it is placed at (day, kilometre, percent, local time, elapsed hours, altitude). Short, like a title: for instance title "DAY 2" and meta "KILOMETRE 84", or title "HALFWAY" with meta "KM 183". Give its film time `t` as one of the fact times.
- A quote card uses a PART of one candidate: the most vivid run of 3 to 9 consecutive words, copied exactly. Name its id; its `t` is that candidate's time.
- `worth` is 1 to 10: how much the viewer gains from seeing these words on screen (a turning point, a vivid line, a funny or moving moment, a milestone: high; a plain remark or a number nobody needs: low).
Answer with ONE JSON object and nothing else: {{"options": [{{"type": "progress" or "quote", "t": film seconds, "id": quote id or null, "title": "...", "meta": "..." or "", "worth": number, "why": "short"}}, ...]}}"""

SHOT = """These are 3 frames of a film, over {dur:.1f} seconds starting at {t:.0f} s. What the viewer hears there: {heard}
A card of lettering with the words "{text}" is being considered for this moment. Judge the SHOT, not the words: would the card get in the way?
- excitement: 1 to 10, how dramatic or important the action is (a crowd at the start, a fall, a spectacular camera move, a clear and emotional face close-up, a view worth looking at: high; a plain stretch of path: low)
- obscure_risk: 1 to 10, how likely lettering over it would cover something that matters or fight with it for attention
- calm: where the lettering could go with the least harm: top, bottom, left, right, centre or none
- verdict: "good" (a card would sit well), "ok", or "avoid" (it would spoil an exciting moment)
Answer with ONE JSON object and nothing else: {{"excitement": n, "obscure_risk": n, "calm": "...", "verdict": "...", "why": "short"}}"""


def parse(text):
    m = re.search(r'\{.*\}', text, re.S)
    if not m: return None
    for cand in (m.group(0), re.sub(r',\s*([}\]])', r'\1', m.group(0))):
        try: return json.loads(cand)
        except ValueError: pass
    return None


def parse_options(text):
    """The option objects of a model's answer, each parsed on its own, so one broken object (a missing brace, a stray colon) costs only itself."""
    whole = parse(text)
    if whole and (whole.get('options') or whole.get('cards')): return whole.get('options') or whole.get('cards')
    out = []; i = text.find('['); depth = 0; start = None
    for k in range(max(i, 0), len(text)):
        ch = text[k]
        if ch == '{':
            if depth == 0: start = k
            depth += 1
        elif ch == '}' and depth:
            depth -= 1
            if depth == 0 and start is not None:
                for cand in (text[start:k + 1], re.sub(r',\s*([}\]])', r'\1', text[start:k + 1])):
                    try: out.append(json.loads(cand)); break
                    except ValueError: pass
    return out


def validate(cards, facts, quotes, length):
    """The cards the model may offer: quotes that are a run of a candidate's words, progress numbers that the facts give, times inside the film. Returns (options, dropped reasons); `worth` and `why` are kept."""
    qs = {q['id']: q for q in quotes}; keep = []; drop = []
    for c in sorted(cards, key=lambda c: float(c.get('t', 0)) if str(c.get('t', '')).replace('.', '', 1).isdigit() else 0.0):
        try: t = float(c['t'])
        except (KeyError, TypeError, ValueError): drop.append('no time'); continue
        lines = [dict(role=str(l.get('role', 'title')), text=str(l.get('text', '')).strip()) for l in c.get('lines', []) if isinstance(l, dict) and str(l.get('text', '')).strip()] if c.get('lines') else [dict(role=r, text=str(c.get(r)).strip()) for r in ('title', 'meta') if isinstance(c.get(r), str) and c.get(r).strip()]
        if not lines or t < EDGE or t > length - EDGE: drop.append(f'{t}: place or empty'); continue
        if c.get('type') == 'quote':
            q = qs.get(c.get('id'))
            if not q: drop.append(f'{t}: unknown quote'); continue
            words = _norm(' '.join(l['text'] for l in lines)); src = _norm(q['text'])
            if not (3 <= len(words) <= 12) or not any(src[i:i + len(words)] == words for i in range(len(src) - len(words) + 1)): drop.append(f"{t}: not a run of the words of {q['id']}"); continue
            t = q['t']; lines = [dict(role='title', text=' '.join(l['text'] for l in lines))]; kind = 'quote'
        else:
            near = min(facts, key=lambda f: abs(f['t'] - t)) if facts else None
            if near is None or abs(near['t'] - t) > 8: drop.append(f'{t}: no facts near'); continue
            allowed = {str(v) for k, v in near.items() if isinstance(v, (int, float))} | {str(int(round(v))) for k, v in near.items() if isinstance(v, (int, float)) and k in ('km', 'percent', 'altitude_m', 'elapsed_h')} | {near['local_time'].replace(':', ''), *near['local_time'].split(':')}
            nums = {n.lstrip('0') or '0' for n in re.findall(r'\d+(?:\.\d+)?', ' '.join(l['text'] for l in lines))}; ok = {a.lstrip('0') or '0' for a in allowed}
            if nums - ok: drop.append(f"{t}: numbers {sorted(nums - ok)} are not in the facts"); continue
            t = near['t']; kind = 'progress'
        words_n = len(_norm(' '.join(l['text'] for l in lines))); dur = CARD_S['progress'] if kind == 'progress' else round(min(max(CARD_S['quote'], 0.35 * words_n + 1.5), 6.0), 2)
        try: worth = float(np.clip(float(c.get('worth', 5)), 1, 10))
        except (TypeError, ValueError): worth = 5.0
        keep.append(dict(type=kind, t=round(t, 2), dur_s=dur, lines=lines, worth=worth, worth_why=str(c.get('why', '')), source=c.get('id')))
    return keep, drop


def propose(facts, quotes, length, server, n=OPTIONS):
    fx = '\n'.join(f"t={f['t']}s day {f['day']} {f['local_time']} km {f['km']} ({f['percent']}% of the distance, {f['elapsed_h']} h elapsed, {f['altitude_m']} m, {f['daylight']})" for f in facts); qx = '\n'.join(f"{q['id']} t={q['t']}s {q['kind']}: {q['text']}" for q in quotes)
    raw = server.chat([dict(role='user', content=PROMPT.format(length=length, facts=fx or '(none)', quotes=qx or '(none)', n=n, edge=EDGE))], 4000, 0.4); opts = parse_options(raw)
    return validate(opts, facts, quotes, length)


def frames_of_film(key_dir, t0, dur, n=5):
    """uint8 RGB frames of the film's preview at n moments from t0 to t0 + dur."""
    import subprocess
    src = os.path.join(key_dir, 'index.m3u8'); out = []
    for k in range(n):
        t = t0 + dur * (0.05 + 0.9 * k / max(n - 1, 1)); r = subprocess.run(['ffmpeg', '-v', 'error', '-ss', f'{t:.2f}', '-i', src, '-frames:v', '1', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-vf', 'scale=960:540', '-'], capture_output=True)
        if len(r.stdout) != 960 * 540 * 3: raise RuntimeError(f'could not read the preview at {t:.1f} s ({key_dir})')
        out.append(np.frombuffer(r.stdout, np.uint8).reshape(540, 960, 3).copy())
    return out


def latest_preview(folder):
    from strata360.pipeline import config
    root = os.path.join(config.race_dir(folder), 'preview'); dirs = [os.path.join(root, d) for d in os.listdir(root) if d.startswith('film-') and os.path.exists(os.path.join(root, d, 'index.m3u8'))] if os.path.isdir(root) else []
    return max(dirs, key=os.path.getmtime) if dirs else None


def heard_at(cues, t0, t1):
    got = [f"{c['kind']}: {c['text']}" for c in cues if c['t0'] < t1 and c['t1'] > t0]; return ' | '.join(got)[:300] or 'nothing said'


def judge_shot(option, key_dir, cues, server, tmp_dir):
    """The vision model's rating of the shot under an option: excitement, how much a card would cover or distract, the calm part of the frame and a verdict."""
    import cv2
    t0, dur = option['t'], option['dur_s']; frames = frames_of_film(key_dir, t0, dur, 3); paths = []
    for k, f in enumerate(frames):
        p = os.path.join(tmp_dir, f'_ft_shot{k}.jpg'); cv2.imwrite(p, f[..., ::-1], [cv2.IMWRITE_JPEG_QUALITY, 88]); paths.append(p)
    ans = parse(server.ask(SHOT.format(dur=dur, t=t0, heard=heard_at(cues, t0, t0 + dur), text=' / '.join(l['text'] for l in option['lines'])), paths, 400)) or {}
    def num(v, d):
        try: return float(np.clip(float(v), 1, 10))
        except (TypeError, ValueError): return d
    verdict = ans.get('verdict') if ans.get('verdict') in ('good', 'ok', 'avoid') else 'ok'
    return dict(excitement=num(ans.get('excitement'), 5.0), obscure_risk=num(ans.get('obscure_risk'), 5.0), calm=str(ans.get('calm', 'none')), verdict=verdict, why=str(ans.get('why', '')))


def score(option):
    """The combined score of an option, 0 to 10, a continuous trade-off: how worth the words are, less what a card would cost the shot (a risk of covering something matters more in an exciting moment) and, once its place is optimised, how much it still blocks. 'avoid' lowers it by 2."""
    s = option['shot']; cost = s['obscure_risk'] * (0.4 + 0.06 * s['excitement']); bl = (option.get('blocking') or {}).get('score')
    sc = 0.6 * option['worth'] + 0.4 * (10 - min(cost, 10.0)) if bl is None else 0.5 * option['worth'] + 0.25 * (10 - min(cost, 10.0)) + 0.25 * (10 - bl)                      # once the card is placed, how much it blocks counts too
    return round(sc - (2.0 if s['verdict'] == 'avoid' else 0.0), 2)


def options(folder, plan=None, n=OPTIONS, log=print):
    """The options file of a project (see the module text); needs a rendered preview to look at the shots. Returns the document."""
    from strata360.pipeline import config
    from strata360.analysis import vlm
    from strata360.edit.bookends import glob_first
    from strata360.render import captions as CP
    from strata360.render import preview as PVW
    plan = plan or json.load(open(os.path.join(config.race_dir(folder), 'project.json')))['edit']['plan']; length = float(plan['film']['length_s']); t0 = time.time()
    key_dir = latest_preview(folder)
    if key_dir is None: raise SystemExit('no preview of the film yet: render it first (the shots are judged from its frames)')
    facts = facts_for(folder, plan); quotes = quotes_for(folder, plan); cues = CP.build_cues(folder, plan); log(f'{len(facts)} moments with race facts, {len(quotes)} candidate quotes')
    with vlm.Server(text=True) as srv: opts, dropped = propose(facts, quotes, length, srv, n)
    log(f'{len(opts)} options from the text model' + (f' ({len(dropped)} dropped by the checks)' if dropped else ''))
    moe = os.path.join(vlm.ROOT, 'models', 'qwen36-35b-a3b'); tmp = os.path.dirname(key_dir)
    with vlm.Server(vlm.llm_files()[0], glob_first(moe, 'mmproj*.gguf') or vlm.model_files()[1]) as srv:
        for i, o in enumerate(opts):
            o['id'] = f'o{i}'; o['shot'] = judge_shot(o, key_dir, cues, srv, tmp); o['score'] = score(o); log(f"  {o['t']:6.1f} s {o['type']:8} worth {o['worth']:.0f} shot {o['shot']['verdict']:5} exc {o['shot']['excitement']:.0f} risk {o['shot']['obscure_risk']:.0f} -> {o['score']:.1f}  {' / '.join(l['text'] for l in o['lines'])}")
    doc = dict(schema=1, plan_key=PVW.plan_key(folder, plan), generated=time.strftime('%Y-%m-%dT%H:%M:%S'), seconds=round(time.time() - t0, 1), preview=os.path.basename(key_dir), length_s=length, dropped=dropped, options=opts)
    json.dump(doc, open(os.path.join(config.race_dir(folder), 'film_text_options.json'), 'w'), indent=1); return doc


def pick(opts, length, per_minute=2.0, gap=MIN_GAP, min_score=4.0):
    """The planner's choice: the best options by combined score (worth, the shot's excitement and risk, how much the placed card blocks: all graded), none closer than `gap` seconds to one chosen (a card's own length counts), at most `per_minute` cards a minute of film. Returns the chosen, in film order."""
    limit = max(int(round(per_minute * length / 60.0)), 1); chosen = []
    for o in sorted(opts, key=lambda o: -o['score']):
        if len(chosen) >= limit: break
        if o['score'] < min_score: continue                                                                    # (a floor on the score; every factor in it is graded, none is a veto)
        if any(o['t'] < c['t'] + c['dur_s'] + gap and c['t'] < o['t'] + o['dur_s'] + gap for c in chosen): continue
        chosen.append(o)
    return sorted(chosen, key=lambda o: o['t'])


def for_plan(folder, plan):
    """What the planner is given: the text options with their ratings (and the ids the planner picked) when they were made for exactly this plan; a flag when the file is from another plan (the film times have moved: make them again with `strata360 filmtext`)."""
    from strata360.pipeline import config
    from strata360.render import preview as PVW
    try: doc = json.load(open(os.path.join(config.race_dir(folder), 'film_text_options.json')))
    except (OSError, ValueError): return {}
    if doc.get('plan_key') != PVW.plan_key(folder, plan): return dict(text_options_stale=True)
    try: chosen = {(c['t'], tuple(l['text'] for l in c['lines'])) for c in json.load(open(os.path.join(config.race_dir(folder), 'film_text.json'))).get('cards', [])}
    except (OSError, ValueError): chosen = set()
    opts = [dict(id=o['id'], type=o['type'], t=o['t'], dur_s=o['dur_s'], lines=o['lines'], worth=o['worth'], shot=dict(verdict=o['shot']['verdict'], excitement=o['shot']['excitement'], obscure_risk=o['shot']['obscure_risk'], calm=o['shot']['calm']), score=o['score'], blocking=o.get('blocking') and dict(score=o['blocking']['score'], what=o['blocking']['what']),
                 picked=(o['t'], tuple(l['text'] for l in o['lines'])) in chosen) for o in doc['options']]
    return dict(text_options=opts, text_cards=[o['id'] for o in opts if o['picked']])


def attach(folder):
    """Put the options (and the planner's picks) into the saved plan, without planning again."""
    from strata360.edit import project as PJ
    edit = PJ.load(folder); plan = edit.get('plan')
    if plan:
        for k in ('text_options', 'text_cards', 'text_options_stale'): plan.pop(k, None)
        plan.update(for_plan(folder, plan)); PJ.save(folder, edit)


def hud_boxes(folder, plan, t, W=960, H=540):
    """[(x0, y0, x1, y1)] fractions of the frame: where the race overlay has something drawn at film time `t` (its text and graph from its own patches, the two maps from the layout), so the cards keep clear of it."""
    import datetime as dt
    from strata360.pipeline import config
    from strata360.overlay import build, layout as L
    cfg = config.load(folder); tp = config.track_path(folder, cfg); st = L.settings(cfg.get('overlay')); out = []
    if not (cfg.get('overlay') or {}).get('enabled', True): return out
    sc = W / 1920.0
    for name in ('route_map', 'local_map'):
        if name in st['elements']: e = {**L.ELEMENTS[name], **st['layout'].get(name, {})}; s = e.get('size', 256); out.append((e['x'] / 1920.0, e['y'] / 1080.0, (e['x'] + s) / 1920.0, (e['y'] + s) / 1080.0))
    g = next((g for g in plan['segments'] if g['film_start_s'] <= t < g['film_start_s'] + g['dur_s'] and g.get('utc_start')), None)
    if tp and g:
        try:
            ov = build(cfg, tp, (W, H), maps=False); utc = dt.datetime.fromisoformat(g['utc_start'].replace('Z', '+00:00')).timestamp() + (t - g['film_start_s'])
            for x, y, p in ov.patches(utc):
                if p.shape[2] == 4 and (p[..., 3] > 40).mean() > 0.02: out.append((x / W, y / H, (x + p.shape[1]) / W, (y + p.shape[0]) / H))
        except Exception: pass
    return out


def design_cards(folder, cards, server, key_dir, log=print, plan=None):
    from strata360.edit import title_design as TD
    from strata360.render import captions as CP, titles as TT
    cues = CP.build_cues(folder, plan) if plan else []; cap = CP.Captions(cues, 960, 540, 25.0)                      # the subtitles are put on the frames the model sees: the cards are designed LAST, round everything else
    for ci, c in enumerate(cards):
        frames = [cap.apply(np.ascontiguousarray(f), int((c['t'] + c['dur_s'] * (0.05 + 0.9 * k / 4)) * 25)) for k, f in enumerate(frames_of_film(key_dir, c['t'], c['dur_s']))]
        avoid = hud_boxes(folder, plan, c['t'] + c['dur_s'] / 2) if plan else []; avoid += cap.boxes(c['t'], c['t'] + c['dur_s'])
        for o in cards[:ci]:                                                                                          # cards already designed: their words are text too
            if o.get('spec') and o['t'] < c['t'] + c['dur_s'] and c['t'] < o['t'] + o['dur_s']: avoid += [b for _, b in TT.piece_boxes(TT.Title(o['spec'], 960, 540, o['dur_s']))]
        purpose = {'quote': "a quote from what was said, shown as a short on-screen note", 'progress': 'a progress update about the race (a short on-screen note)'}[c['type']]
        calm = c.get('shot', {}).get('calm', 'none'); hint = f" The shot's calmest part for lettering is the {calm}." if calm in ('top', 'bottom', 'left', 'right', 'centre') else ''
        spec, report = TD.design(frames, c['lines'], purpose, c['dur_s'], server, scene='The film already has the race overlay along the left and right edges and the top row, and subtitles along the bottom: keep the words inside the middle of the frame (x from 0.2 to 0.8, y from 0.1 to 0.78). The word art is short and quick: it must read at a glance.' + hint, tmp_dir=os.path.dirname(key_dir), rounds=1, log=log, bottom_clear=0.18, keep_in=SAFE_ZONE, avoid=avoid)
        c['spec'] = spec; c['changes'] = report['changes']; c['blocking'] = report.get('blocking');  log(f"  designed {c['type']} at {c['t']} s: {' / '.join(l['text'] for l in c['lines'])}")
    return cards


def run(folder, plan=None, n=OPTIONS, per_minute=2.0, reuse=False, log=print):
    """options (or the stored ones with `reuse`) -> the planner's pick -> the word art of the picked cards -> film_text.json. Returns (options document, film_text document)."""
    from strata360.pipeline import config
    from strata360.analysis import vlm
    from strata360.edit.bookends import glob_first
    rd = config.race_dir(folder); plan = plan or json.load(open(os.path.join(rd, 'project.json')))['edit']['plan']; t0 = time.time(); path = os.path.join(rd, 'film_text_options.json')
    odoc = json.load(open(path)) if reuse and os.path.exists(path) else options(folder, plan, n, log)
    limit = max(int(round(per_minute * odoc['length_s'] / 60.0)), 1); pool = sorted(odoc['options'], key=lambda o: -o['score'])[:2 * limit + 2]; pool = sorted((o for o in pool if o['score'] >= 3.0), key=lambda o: o['t'])    # the best by the shot and the words alone get their word art made, so how much each blocks is known
    log(f'{len(pool)} options get their word art placed, to know how much each would block')
    key_dir = latest_preview(folder); moe = os.path.join(vlm.ROOT, 'models', 'qwen36-35b-a3b')
    with vlm.Server(vlm.llm_files()[0], glob_first(moe, 'mmproj*.gguf') or vlm.model_files()[1]) as srv: designed = design_cards(folder, [dict(c) for c in pool], srv, key_dir, log, plan)
    for c in designed:
        o = next(o for o in odoc['options'] if o['id'] == c['id']); o['blocking'] = c.get('blocking'); o['score'] = score(o); c['score'] = o['score']; log(f"  {c['id']} blocks {(c.get('blocking') or {}).get('score', '-')} {(c.get('blocking') or {}).get('what', '')} -> score {o['score']:.1f}")
    cards = pick(designed, odoc['length_s'], per_minute); log(f'the planner picks {len(cards)} of {len(odoc["options"])} options')
    from strata360.render import preview as PVW
    json.dump(odoc, open(path, 'w'), indent=1)
    doc = dict(schema=1, plan_key=PVW.plan_key(folder, plan), generated=time.strftime('%Y-%m-%dT%H:%M:%S'), seconds=round(time.time() - t0, 1), preview=os.path.basename(key_dir), cards=cards)
    json.dump(doc, open(os.path.join(rd, 'film_text.json'), 'w'), indent=1); attach(folder); return odoc, doc
