"""Ask a language model for corrections to the recognised words: obvious recognition errors (a word that makes no sense where a similar-sounding one does), using what the project knows: the title,
the notes you wrote, the place names on the route, the neighbouring phrases and the recogniser's confidence in each word. The model only SUGGESTS word substitutions; they are stored as model
corrections (analysis/transcript_edits.py) that show highlighted and that you can overrule word by word."""
import glob, json, os
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
