"""Voice-over script writer: a local LLM turns the user's notes, the transcript and everything known about each moment into narration that fits the film.

Inputs
  * the plan: an ordered list of segments (film time, duration, clip, candidate) from the optimiser (or the user's edited plan),
  * the user's notes: one for the whole folder, one per clip,
  * per segment: what the wearer says on camera (with translation), the clip's own notes, the race track facts (pace, gradient, altitude, heart rate, distance and percent of the
    race, elapsed time, local time and daylight), and what the camera sees (setting, tags, weather, lighting, people),
  * the target: total length, speaking rate, style.

Rules the writer is held to (checked, and fixed with one retry): every line fits the seconds of its segment at the speaking rate; no narration over the wearer's own speech unless a
segment is explicitly marked as commentary; no facts beyond those supplied (no invented names, places or numbers); the total fits the film. The output is a script with a word and
seconds budget per segment, ready to be read, recorded and re-fitted (README 17)."""
import json, math, os, re, subprocess, tempfile, time

DEFAULT_WPM = 145.0          # comfortable reflective narration; a fast read is 170
FILL = 0.85                  # share of a segment's seconds the narration may occupy (leaves breathing room)


def words(s): return len(re.findall(r"[\w'’-]+", s))


def budget_words(dur_s, wpm=DEFAULT_WPM, fill=FILL): return max(int(dur_s * wpm / 60.0 * fill), 0)


def words_in_window(cdir, clip, w0, w1):
    """What the wearer says inside the window [w0, w1] (clip-relative seconds): only the words whose middle falls in the window, from the word timings (accurate alignment where it passed
    its checks, else whisper's times, which run about 0.15 s early). Phrases in other languages give the matching share of the English translation (its words are not timed). A trailing or
    leading ellipsis marks a sentence cut by the window. Returns a list with one string per phrase, or [] when the clip has no transcript."""
    tp = os.path.join(cdir, clip, 'transcript.json')
    if not cdir or not os.path.exists(tp): return []
    from strata360.analysis import transcript_edits as TE
    tr = TE.load_effective(os.path.join(cdir, clip)); ap = os.path.join(cdir, clip, 'alignment.json'); al = {a['index']: a for a in (json.load(open(ap)).get('segments') or []) if a} if os.path.exists(ap) else {}
    out = []
    for si, seg in enumerate(tr['segments']):
        if seg['t1'] <= w0 or seg['t0'] >= w1 or not seg.get('text', '').strip() or seg.get('flags'): continue
        ws = seg.get('words') or []
        if not ws: out.append((seg.get('text_en') or seg['text']).strip()); continue
        aw = (al.get(si) or {}).get('words') or []; inside = []
        for k, w in enumerate(ws):
            a = aw[k] if k < len(aw) else None
            t0, t1 = (a['a0'], a['a1']) if a and a.get('ok') else (w['t0'] + 0.15, w['t1'] + 0.15)
            if w0 <= (t0 + t1) / 2 < w1: inside.append(k)
        if not inside: continue
        n = len(ws); foreign = seg.get('lang', 'en') != 'en' and seg.get('text_en') and seg['text_en'].strip() != seg['text'].strip()
        if foreign:
            tok = seg['text_en'].split(); lo = int(inside[0] / n * len(tok)); hi = max(int(math.ceil((inside[-1] + 1) / n * len(tok))), lo + 1); text = ' '.join(tok[lo:hi])
        else: text = ' '.join(ws[k]['w'].strip() for k in inside)
        out.append(('… ' if inside[0] > 0 else '') + text.strip() + (' …' if inside[-1] < n - 1 else ''))
    return out


def segment_facts(seg, cand, cdir, track, notes, tz='Europe/Brussels'):
    """Everything worth telling the writer about one planned segment (a dict, later rendered as text)."""
    import datetime as dt
    from strata360.gps import context as X
    f = dict(id=seg.get('id'), index=seg['index'], film_start_s=round(seg['start_s'], 1), seconds=round(seg['dur_s'], 1), clip=cand['clip'], technique=seg.get('technique'))
    t0 = dt.datetime.fromisoformat(cand['start_utc'].replace('Z', '+00:00')).timestamp() + seg.get('in_s', 0.0); t1 = t0 + seg['dur_s']
    if track is not None: f['track'] = X.describe(X.context_at(track, t0, t1, tz))
    pl = os.path.join(cdir, cand['clip'], 'places.json') if cdir else None
    if pl and os.path.exists(pl):
        pj = json.load(open(pl))
        if pj.get('covered') and pj.get('summary'): f['place'] = pj['summary']['text'] + (f", on {pj['summary']['road']}" if pj['summary'].get('road') else '') + '; nearby: ' + ', '.join(sorted({n['name'] for p in pj['points'] for n in (p.get('nearby') or [])[:4]})[:6])
    f['clip_note'] = (notes.get('clips', {}).get(cand['clip']) or '').strip()
    sp = cand.get('transcript') or []
    w0 = seg.get('in_s', 0.0) + cand['start_s']; w1 = w0 + seg['dur_s']
    f['wearer_says'] = (words_in_window(cdir, cand['clip'], w0, w1) or [s_.get('text_en') or s_['text'] for s_ in sp if s_['t1'] > w0 and s_['t0'] < w1]) if cand['features'].get('speech') else []
    sc = None
    p = os.path.join(cdir, cand['clip'], 'scenes.json') if cdir else None
    if p and os.path.exists(p):
        sc = json.load(open(p)); it = [i for i in sc['items'] if i['ok'] and i['view'] == 'front' and cand['start_s'] - 2 <= i['t_s'] <= cand['end_s'] + 2]
        if it: f['sees'] = '; '.join(sorted({f"{i['setting']}: {i['description']}" for i in it if i.get('description')})[:2]); f['tags'] = sorted({t for i in it for t in (i.get('tags') or [])})[:8]; f['weather'] = sorted({i['weather'] for i in it if i.get('weather') and i['weather'] != 'unknown'})
    f['people_in_shot'] = cand.get('people')
    return f


def build_messages(folder_note, facts, target_s, wpm=DEFAULT_WPM, style='', race_line=''):
    sys_msg = ("You write voice-over narration for a short film of an ultramarathon, spoken by the runner who wore the camera (first person, natural, understated, honest; no clichés, no hype, "
               "no motivational-poster lines). Use ONLY the facts supplied: never invent names, places, numbers, times or events. If something is not given, leave it out. Write in short spoken "
               "sentences a person could say while running. Each segment has a word budget: never exceed it. Segments where the runner speaks on camera must get no narration (leave them empty) "
               "unless marked 'commentary allowed'. Return ONE JSON object and nothing else: "
               '{"title": str, "lines": [{"seg": int, "text": str}]} with one entry per segment index (empty text where silent). The narration should have an arc across the film and must not repeat itself.')
    lines = [f"FILM: {target_s:.0f} seconds in {len(facts)} segments; speaking rate about {wpm:.0f} words per minute." + (f" {race_line}" if race_line else ''), '']
    if folder_note.strip(): lines += ['THE RUNNER\'S NOTES ABOUT THE WHOLE RACE:', folder_note.strip(), '']
    if style.strip(): lines += ['STYLE REQUEST:', style.strip(), '']
    lines.append('SEGMENTS (in film order):')
    for f in facts:
        b = budget_words(f['seconds'], wpm); talk = bool(f.get('wearer_says'))
        lines.append(f"[{f['index']}] {f['seconds']} s, word budget {0 if talk else b}" + (' (the runner speaks here: do not narrate)' if talk else ''))
        if f.get('track'): lines.append(f"    track: {f['track']}")
        if f.get('place'): lines.append(f"    place (OpenStreetMap): {f['place']}")
        if f.get('sees'): lines.append(f"    camera sees: {f['sees']}" + (f" (tags: {', '.join(f['tags'])})" if f.get('tags') else '') + (f"; weather {', '.join(f['weather'])}" if f.get('weather') else ''))
        if f.get('clip_note'): lines.append(f"    runner's note for this clip: {f['clip_note']}")
        if talk: lines.append('    the runner says: ' + ' / '.join(f['wearer_says'])[:300])
    return [dict(role='system', content=sys_msg), dict(role='user', content='\n'.join(lines))]


def _parse_json(text):
    m = re.search(r'\{.*\}', text, re.S)
    if not m: return None
    for cand in (m.group(0), re.sub(r',\s*([}\]])', r'\1', m.group(0))):
        try: return json.loads(cand)
        except ValueError: pass
    return None


def run_llm(messages, model=None, max_tokens=1600, temperature=0.7, work_dir=None, provider='vertex'):
    """provider 'anthropic' (the Claude API; the default) or 'local' (mlx-lm in .venv-vision)."""
    if provider in ('anthropic', 'gemini', 'vertex'):
        from strata360.edit import llm_remote
        default = llm_remote.PROVIDERS[provider]['default']
        r = llm_remote.chat(messages, model or default, max(max_tokens, 16000), temperature, provider=provider); r['parsed'] = _parse_json(r['text']); return r      # generous: a reasoning model's hidden thinking counts against the limit
    tmp = tempfile.mkdtemp(prefix='s360llm_', dir=work_dir)
    rq, out = os.path.join(tmp, 'req.json'), os.path.join(tmp, 'out.json'); json.dump(dict(messages=messages, max_tokens=max_tokens, temperature=temperature, json=True), open(rq, 'w'))
    py = os.path.join(os.path.dirname(__file__), '..', '..', '..', '.venv-vision', 'bin', 'python'); src = os.path.join(os.path.dirname(__file__), '..', '..')
    subprocess.run([py, '-m', 'strata360.edit.llm_cli', rq, out] + (['--model', model] if model else []), check=True, env={**os.environ, 'PYTHONPATH': src, 'PYTHONWARNINGS': 'ignore'}, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    r = json.load(open(out))
    for f in (rq, out): os.remove(f)
    os.rmdir(tmp); return r


def check(script, facts, wpm=DEFAULT_WPM):
    """Problems in a written script: over-budget lines, narration over the wearer's speech, missing segments. Returns [(seg, message)]."""
    by = {f['index']: f for f in facts}; got = {int(l['seg']): (l.get('text') or '').strip() for l in script.get('lines', []) if isinstance(l, dict) and 'seg' in l}; bad = []
    for i, f in by.items():
        t = got.get(i, ''); b = 0 if f.get('wearer_says') else budget_words(f['seconds'], wpm)
        if words(t) > b: bad.append((i, f"{words(t)} words but the budget is {b}" + (' (the runner speaks here)' if f.get('wearer_says') else '')))
    for i in got:
        if i not in by: bad.append((i, 'no such segment'))
    return bad


def write_script(facts, folder_note, target_s, wpm=DEFAULT_WPM, style='', race_line='', model=None, work_dir=None, retries=1, provider='vertex'):
    msgs = build_messages(folder_note, facts, target_s, wpm, style, race_line); t0 = time.time(); r = run_llm(msgs, model, work_dir=work_dir, provider=provider); s = r.get('parsed') or {}; bad = check(s, facts, wpm) if s else [(-1, 'not valid JSON')]
    tries = 1
    while bad and tries <= retries:
        fix = '; '.join(f"segment {i}: {m}" for i, m in bad[:12]); msgs = msgs + [dict(role='assistant', content=r['text']), dict(role='user', content=f"Fix these problems and return the full JSON again: {fix}. Shorten the lines; never exceed a budget.")]
        r = run_llm(msgs, model, work_dir=work_dir, provider=provider); s = r.get('parsed') or s; bad = check(s, facts, wpm); tries += 1
    by = {f['index']: f for f in facts}; out = []
    for f in facts:
        t = next((l.get('text', '').strip() for l in s.get('lines', []) if isinstance(l, dict) and int(l.get('seg', -1)) == f['index']), '')
        b = 0 if f.get('wearer_says') else budget_words(f['seconds'], wpm)
        if words(t) > b:                                                                                      # still too long: cut at the last sentence that fits
            parts = re.split(r'(?<=[.!?])\s+', t); t = ''
            for p in parts:
                if words((t + ' ' + p).strip()) <= b: t = (t + ' ' + p).strip()
        out.append(dict(seg=f['index'], id=f.get('id'), film_start_s=f['film_start_s'], seconds=f['seconds'], clip=f['clip'], text=t, says=f.get('wearer_says') or [], words=words(t), est_speak_s=round(words(t) * 60.0 / wpm, 1), budget_words=b))
    dbg = dict(finish=r.get('finish'), tokens=r.get('tokens'), text_head=(r.get('text') or '')[:600]) if (not s or bad) else None
    return dict(schema=1, provider=provider, model=r.get('model') or model, llm_debug=dbg, title=s.get('title'), target_s=target_s, wpm=wpm, style=style, seconds_llm=round(time.time() - t0, 1), remaining_problems=[dict(seg=i, problem=m) for i, m in bad], lines=out,
                total_words=sum(l['words'] for l in out), total_speak_s=round(sum(l['est_speak_s'] for l in out), 1))
