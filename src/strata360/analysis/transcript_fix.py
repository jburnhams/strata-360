"""Ask a language model for corrections to the recognised words: obvious recognition errors (a word that makes no sense where a similar-sounding one does), using what the project knows: the title,
the notes you wrote, the place names on the route, the neighbouring phrases and the recogniser's confidence in each word. The model only SUGGESTS word substitutions; they are stored as model
corrections (analysis/transcript_edits.py) that show highlighted and that you can overrule word by word."""
import glob, hashlib, json, os
from strata360.pipeline import config
from strata360.analysis import transcript_edits as TE

SYSTEM = """You correct speech-recognition errors in transcripts of a runner talking to a camera during an ultra-distance race, and of people near them (English, with some French, Dutch, German).
This is SPOKEN language, transcribed exactly as said. People repeat words, stutter, restart sentences, use fillers, speak ungrammatically, trail off and use dialect or slang: all of that is real and
intended, so NEVER change it. Do not fix grammar, do not remove repeated words, do not tidy or rephrase, do not 'improve' anything that was actually said, and do not delete words.
The ONLY thing to correct is a word the recogniser MISHEARD: it makes no sense where it stands, and a similar-sounding word (or a place name or race term from the context given) clearly does
(for example 'in the ark' for 'in the dark', 'wave across the river' for 'wade across the river', a wrong name of a place). A low confidence number alone is not a reason.
You get several clips (numbered), each with numbered phrases; each word has a number and the recogniser's confidence (0-1) in brackets. Keep the punctuation attached to the word as in the original
token (the 'to' text replaces the whole token, with exactly one replacement word). Prefer few, certain fixes over many guesses; if in doubt, leave it.
Answer with JSON only: {"fixes": [{"clip": <clip number>, "seg": <phrase number>, "word": <word number>, "from": "<the token as given>", "to": "<replacement token>", "why": "<five words at most>"}]}"""


def context(folder):
    """What the model is told about the project: title, your notes, place names."""
    from strata360.pipeline import meta, notes as N
    lines = []
    try:
        lines.append(meta.describe(folder))
    except Exception: pass
    try:
        nt = N.load(folder)
        if nt.get('folder'): lines.append('Notes by the runner: ' + nt['folder'][:1500])
    except Exception: pass
    try:
        loc = json.load(open(os.path.join(config.race_dir(folder), 'locations.json'))); names = set()
        for c in loc.get('clips') or []:
            names.update((c.get('summary') or {}).get('places') or [])
            for p in c.get('points') or []: names.update(n['name'] for n in (p.get('nearby') or [])[:3] if n.get('name'))
        if names: lines.append('Places on the route: ' + ', '.join(sorted(names)[:60]) + '.')
    except Exception: pass
    return '\n'.join(lines)


MAX_WORDS = 4000        # words per request: clips are batched together up to this many (most of a race fits in one request, and the model sees the neighbouring clips)


def clip_block(n, clip, tr, clip_note=''):
    """(text, word count) of one clip for the prompt, or (None, 0) when it has no speech. Phrases are written as [clip:phrase]."""
    rows = []; words = 0
    for si, s in enumerate(tr['segments']):
        ws = s.get('words') or []
        if not ws or not s.get('text', '').strip(): continue
        words += len(ws); rows.append(f"[{n}:{si}] ({s['lang']}, {s['t0']:.1f}s) " + ' '.join(f"{wi}:{w['w'].strip()}({w.get('p', 0):.2f})" for wi, w in enumerate(ws)))
    if not rows: return None, 0
    return f"Clip {n} ({clip})" + (f", note: {clip_note}" if clip_note else '') + ':\n' + '\n'.join(rows), words


def run(folder, clips=None, provider=None, model=None, progress=None, log=print):
    """Suggest corrections for every clip with speech (or those whose id contains one of `clips`), batched by word count. Returns {clip: number of suggestions stored}."""
    from strata360.edit import script as SC, llm_remote as LR
    from strata360.pipeline import notes as N
    cfg = config.load(folder); llm = cfg.get('llm', {}); provider = provider or llm.get('provider', 'vertex'); model = model or llm.get('model') or LR.PROVIDERS[provider]['default']
    dirs = sorted(glob.glob(os.path.join(config.race_dir(folder), 'clips', '*', ''))); dirs = [d for d in dirs if os.path.exists(d + 'transcript.json') and (not clips or any(c in os.path.basename(d.rstrip('/')) for c in clips))]
    try: nt = N.load(folder)
    except Exception: nt = {'clips': {}}
    items = []                                                                          # (clip id, dir)
    for d in dirs:
        clip = os.path.basename(d.rstrip('/')); tr = json.load(open(d + 'transcript.json'))
        if any(s.get('words') and s.get('text', '').strip() for s in tr['segments']): items.append((clip, d, tr))
    batches = []; cur = []; cw = 0
    for clip, d, tr in items:
        w = sum(len(s.get('words') or []) for s in tr['segments'] if s.get('text', '').strip())
        if cur and cw + w > MAX_WORDS: batches.append(cur); cur = []; cw = 0
        cur.append((clip, d, tr)); cw += w
    if cur: batches.append(cur)
    out = {}; ctx = context(folder)
    for b in batches:
        blocks = [clip_block(n, clip, tr, (nt.get('clips') or {}).get(clip, ''))[0] for n, (clip, d, tr) in enumerate(b, 1)]
        r = SC.run_llm([dict(role='system', content=SYSTEM), dict(role='user', content=ctx + '\n\n' + '\n\n'.join(x for x in blocks if x))], model=model, max_tokens=8000, temperature=0.2, provider=provider)
        fixes = ((r.get('parsed') or {}).get('fixes')) if isinstance(r.get('parsed'), dict) else None
        by = {}
        for f in fixes or []:
            try: by.setdefault(int(f['clip']), []).append(f)
            except (KeyError, ValueError, TypeError): continue
        for n, (clip, d, tr) in enumerate(b, 1):
            out[clip] = TE.set_gemini(d, by.get(n, []), model=model); log(f'{clip}: {out[clip]} suggestion(s)')
        progress and progress(len(out), len(items), sum(out.values()))
    return out


# ---- from the AUDIO: speech-only excerpts of 30-60 s, the recogniser's numbered words as the draft ---------------------------------------------------------------------------------------------
SYSTEM_AUDIO = """You check a speech recogniser's transcript against the AUDIO it was made from. The recording is from a runner wearing a camera during an ultra-distance race in Belgium, and the people near
them (mostly English, some French, Dutch, German). You get a short audio excerpt, a DRAFT transcript with numbered phrases and numbered words (the recogniser's confidence 0-1 in brackets), and context.
This is SPOKEN language, transcribed as said: repeated words, stutters, fillers, restarts, ungrammatical sentences and dialect are real and intended, so NEVER change or remove them, and do not tidy
or rephrase. Listen, and correct ONLY words the recogniser MISHEARD (the audio clearly says something else), or a short word or filler it clearly MISSED. Use the context (names, places, the runner's
notes) only to choose between similar-sounding words. If you cannot hear the difference, leave the draft alone: few certain fixes beat many guesses.
Each fix replaces one word or a run of words of the draft: "seg" is the phrase number, "word" the first word number, "through" (optional) the last word number of a run, and "to" is the replacement
text (it may be several words, or one word plus a missed filler); keep the punctuation attached as in the draft. "from" is the draft's words you replace, exactly as given.
Answer with JSON only: {"fixes": [{"seg": <n>, "word": <n>, "through": <n or omit>, "from": "<draft words>", "to": "<replacement>", "why": "<five words at most>"}]}"""
ISLAND_GAP_S = 4.0       # a silence this long is cut out: the audio is the speech only


def chunks(tr, dur, min_s=30.0, max_s=60.0, pad=0.5, island_gap=ISLAND_GAP_S):
    """Speech-only excerpts of a clip: [{segs: [segment numbers], t0, t1, a0, a1}] (t = first/last spoken word, a = the audio to cut, with `pad` seconds either side). Phrases are grouped into
    stretches of speech separated by silences of `island_gap` seconds or more (the silence is not sent); a stretch longer than `max_s` is broken at the natural pause (preferring a sentence end) that
    leaves pieces of `min_s` to `max_s`; a shorter stretch is one excerpt."""
    segs = [(si, s) for si, s in enumerate(tr['segments']) if s.get('words') and s.get('text', '').strip()]
    if not segs: return []
    t0 = lambda s: s['words'][0]['t0']; t1 = lambda s: s['words'][-1]['t1']; islands = [[segs[0]]]
    for a, b in zip(segs, segs[1:]):
        if t0(b[1]) - t1(a[1]) >= island_gap: islands.append([])
        islands[-1].append(b)
    out = []
    def emit(group): out.append(dict(segs=[si for si, _ in group], t0=round(t0(group[0][1]), 2), t1=round(t1(group[-1][1]), 2), a0=round(max(t0(group[0][1]) - pad, 0.0), 2), a1=round(min(t1(group[-1][1]) + pad, dur), 2)))
    for isl in islands:
        i = 0
        while i < len(isl):
            if t1(isl[-1][1]) - t0(isl[i][1]) <= max_s: emit(isl[i:]); break
            best = None
            for j in range(i, len(isl) - 1):                                              # a break after phrase j
                L = t1(isl[j][1]) - t0(isl[i][1])
                if L > max_s: break
                if L < min_s or t1(isl[-1][1]) - t0(isl[j + 1][1]) < min_s * 0.5: continue
                gap = t0(isl[j + 1][1]) - t1(isl[j][1]); end = isl[j][1]['text'].strip().endswith(('.', '?', '!', '…')); score = gap + (0.6 if end else 0.0)
                if best is None or score > best[0]: best = (score, j)
            if best is None:                                                              # no break leaves a decent piece: as long as is allowed
                j = i
                while j + 1 < len(isl) and t1(isl[j + 1][1]) - t0(isl[i][1]) <= max_s: j += 1
                best = (0, j)
            emit(isl[i:best[1] + 1]); i = best[1] + 1
    return out


def excerpt_prompt(ctx, tr, ch):
    rows = []
    for si in ch['segs']:
        s = tr['segments'][si]; rows.append(f"[{si}] ({s['lang']}, {s['words'][0]['t0']:.1f}s) " + ' '.join(f"{wi}:{w['w'].strip()}({w.get('p', 0):.2f})" for wi, w in enumerate(s['words'])))
    return f"{ctx}\n\nThis audio excerpt is {ch['a0']:.1f}-{ch['a1']:.1f} s of the recording.\nDRAFT transcript:\n" + '\n'.join(rows) + '\n\nListen and answer with the fixes.'


PROMPT_VERSION = 1       # bump when SYSTEM_AUDIO or the excerpt prompt changes: cached replies are for one prompt


def call_key(ch, audio_path, prompt, model, thinking, run):
    """Identity of one request: the prompt text and version, the model, thinking level, which of the repeated checks it is, and the audio excerpt (file, size, time, range)."""
    st = os.stat(audio_path); h = hashlib.sha1(json.dumps([PROMPT_VERSION, model, thinking, run, ch['a0'], ch['a1'], os.path.basename(audio_path), st.st_size, int(st.st_mtime), prompt], sort_keys=True).encode()).hexdigest()[:16]
    return h


def usage_log_path(folder): return os.path.join(config.race_dir(folder), 'gemini_usage.jsonl')


def check_chunk(folder, clip, tr, ch, audio_path, ctx, provider='vertex', model=None, thinking='low', run=0, cache_dir=None, log=None):
    """One request for one excerpt: returns (fixes, info). The audio is the excerpt of `audio_path`, mono 16 kHz FLAC. Every reply is kept on disk (`cache_dir`): asking the same thing again costs
    nothing, whatever is changed afterwards (voting rules, which fixes are applied); each NEW call is logged with its token counts in <project>/gemini_usage.jsonl."""
    import base64, subprocess, time
    from strata360.edit import llm_remote as LR, script as SC
    model = model or LR.PROVIDERS[provider]['default']; prompt = excerpt_prompt(ctx, tr, ch); key = call_key(ch, audio_path, prompt, model, thinking, run); cp = os.path.join(cache_dir, key + '.json') if cache_dir else None
    if cp and os.path.exists(cp):
        try:
            c = json.load(open(cp)); return c['fixes'], dict(c['info'], cached=True)
        except (OSError, ValueError, KeyError): pass
    raw = subprocess.run(['ffmpeg', '-v', 'error', '-ss', f"{ch['a0']:.2f}", '-t', f"{ch['a1'] - ch['a0']:.2f}", '-i', audio_path, '-ac', '1', '-ar', '16000', '-c:a', 'flac', '-f', 'flac', '-'], capture_output=True, check=True).stdout
    msgs = [dict(role='system', content=SYSTEM_AUDIO), dict(role='user', content=[dict(inlineData=dict(mimeType='audio/flac', data=base64.b64encode(raw).decode())), dict(text=prompt)])]
    r = LR.chat(msgs, model, 16000, 0.1, timeout=600, provider=provider, thinking=thinking); parsed = SC._parse_json(r['text'])
    fixes = (parsed or {}).get('fixes') if isinstance(parsed, dict) else None; fixes = fixes or []
    info = dict(seconds=r['seconds'], tokens=r.get('tokens'), finish=r.get('finish'), audio_kb=round(len(raw) / 1024), parsed=isinstance(parsed, dict), cached=False)
    if cp and isinstance(parsed, dict):                                                    # a reply that could not be read is not kept: it is worth asking again
        os.makedirs(cache_dir, exist_ok=True); json.dump(dict(key=key, clip=clip, excerpt=[ch['a0'], ch['a1']], model=model, thinking=thinking, run=run, prompt_version=PROMPT_VERSION, fixes=fixes, info=info, raw=r['text'], at=time.time()), open(cp + '.tmp', 'w'), indent=1); os.replace(cp + '.tmp', cp)
    try: open(usage_log_path(folder), 'a').write(json.dumps(dict(at=time.time(), clip=clip, model=model, thinking=thinking, run=run, tokens=r.get('tokens'), seconds=r['seconds'], audio_kb=info['audio_kb'])) + '\n')
    except OSError: pass
    return fixes, info


# ---- the full pass: every excerpt checked several times, only fixes the checks agree on are kept ---------------------------------------------------------------------------------------------
def vote(runs, min_votes=2):
    """runs: a list (one per check) of fix lists for ONE excerpt. A fix is its words (seg, first word, last word) and replacement text; it is kept when at least `min_votes` checks gave it. When
    checks give different replacements for the same words, the one most checks gave wins; fixes that overlap other words already taken are dropped. Returns [{seg, word, through, to, from, why, votes, runs}]."""
    cnt = {}; n = len(runs)
    for fixes in runs:
        seen = set()
        for f in fixes or []:
            try: k = (int(f['seg']), int(f['word']), int(f.get('through', f['word'])), ' '.join(str(f['to']).split()))
            except (KeyError, ValueError, TypeError): continue
            if k in seen: continue
            seen.add(k); e = cnt.setdefault(k, dict(votes=0, why=[], frm=f.get('from')))
            e['votes'] += 1
            if f.get('why'): e['why'].append(str(f['why']))
    out = []; taken = set()
    for (seg, w0, w1, to), e in sorted(cnt.items(), key=lambda kv: (-kv[1]['votes'], kv[0])):
        if e['votes'] < min_votes or any((seg, w) in taken for w in range(w0, w1 + 1)): continue
        taken.update((seg, w) for w in range(w0, w1 + 1))
        out.append(dict(seg=seg, word=w0, through=w1, to=to, **{'from': e['frm']}, why=(e['why'][0] if e['why'] else 'misheard') + f" (checked by Gemini from the audio: {e['votes']} of {n} agree)", votes=e['votes'], runs=n))
    return sorted(out, key=lambda f: (f['seg'], f['word']))


def check_clip(folder, clip, runs=3, min_votes=2, thinking='low', provider=None, model=None, workers=4, progress=None, log=print):
    """The whole audio check of ONE clip: its speech-only excerpts, each checked `runs` times (replies cached on disk, so only calls never made before are paid for), the fixes at least `min_votes`
    checks agree on stored as Gemini corrections. Returns a document for the stage's output: settings, per-excerpt results, kept corrections, and how many calls were made or reused."""
    from concurrent.futures import ThreadPoolExecutor
    from strata360.edit import llm_remote as LR
    from strata360.analysis import transcribe_gemini as TG
    cfg = config.load(folder); llm = cfg.get('llm', {}); provider = provider or llm.get('provider', 'vertex'); model = model or llm.get('model') or LR.PROVIDERS[provider]['default']
    d = os.path.join(config.race_dir(folder), 'clips', clip); tr = json.load(open(os.path.join(d, 'transcript.json'))); cj = json.load(open(os.path.join(d, 'clip.json'))); dur = cj['video']['source_frames'] / cj['video']['nominal_fps']
    au = next((os.path.join(d, n) for n in ('audio_clean.flac', 'audio_original.flac') if os.path.exists(os.path.join(d, n))), None)
    if au is None: raise RuntimeError('the clip has no stored audio yet (the audio_extract stage)')
    chs = chunks(tr, dur); doc = dict(settings=dict(runs=runs, min_votes=min_votes, thinking=thinking, model=model, prompt_version=PROMPT_VERSION, audio=os.path.basename(au)), excerpts=[], kept=[], calls=dict(made=0, reused=0), tokens=dict(input=0, output=0))
    if not chs: TE.set_gemini(d, [], model=model); return doc
    ctx = TG.context(folder, clip); cache = os.path.join(d, 'gemini_checks'); jobs = [(i, r) for i in range(len(chs)) for r in range(runs)]; res = {i: [None] * runs for i in range(len(chs))}; n = [0]
    def one(job):
        i, r = job
        try: fx, info = check_chunk(folder, clip, tr, chs[i], au, ctx, provider=provider, model=model, thinking=thinking, run=r, cache_dir=cache)
        except Exception as e: log(f'{clip} excerpt {i} check {r}: {type(e).__name__}: {e}'); fx, info = None, dict(error=str(e), retryable=getattr(e, 'retryable', False), exc=e)
        res[i][r] = (fx, info); n[0] += 1; progress and progress(n[0], len(jobs))
    with ThreadPoolExecutor(workers) as ex: list(ex.map(one, jobs))
    bad = [x[1] for i in res for x in res[i] if x and x[0] is None]; fresh = sum(1 for i in res for x in res[i] if x and x[0] is not None and not x[1].get('cached'))
    if bad:                                                                                 # a failed check is never replaced by a smaller vote: nothing is stored until all checks have been made
        fatal = [b for b in bad if not b.get('retryable')]
        if fatal: raise fatal[0]['exc']
        from strata360.pipeline.retry import RetryLater
        raise RetryLater(f"{len(bad)} of {len(jobs)} Gemini checks failed for now ({str(bad[0].get('error'))[:120]}); {len(jobs) - len(bad)} are done and kept", progress=fresh > 0)
    for i, ch in enumerate(chs):
        got = [x for x in res[i] if x and x[0] is not None]; kept = [f for f in vote([x[0] for x in got], min_votes) if f['seg'] in ch['segs']]
        for _, info in got:
            doc['calls']['reused' if info.get('cached') else 'made'] += 1
            for k in ('input', 'output'): doc['tokens'][k] += int(((info.get('tokens') or {}).get(k)) or 0) if not info.get('cached') else 0
        doc['excerpts'].append(dict(segs=[ch['segs'][0], ch['segs'][-1]], audio=[ch['a0'], ch['a1']], checks=len(got), failed=runs - len(got), kept=len(kept))); doc['kept'].extend(kept)
    if all(not [x for x in res[i] if x and x[0] is not None] for i in range(len(chs))): raise RuntimeError('every check failed (see the log): nothing stored')
    doc['stored'] = TE.set_gemini(d, doc['kept'], model=f'{model} (audio, {runs} checks)'); return doc


def run_audio(folder, clips=None, **kw):
    """check_clip for every clip with speech (CLI helper); returns {clip: corrections stored}."""
    out = {}
    for d in sorted(glob.glob(os.path.join(config.race_dir(folder), 'clips', '*', ''))):
        clip = os.path.basename(d.rstrip('/'))
        if not os.path.exists(d + 'transcript.json') or (clips and not any(c in clip for c in clips)): continue
        out[clip] = check_clip(folder, clip, **kw).get('stored', 0)
    return out
