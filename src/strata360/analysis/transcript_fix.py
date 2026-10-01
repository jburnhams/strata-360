"""Ask a language model for corrections to the recognised words: obvious recognition errors (a word that makes no sense where a similar-sounding one does), using what the project knows: the title,
the notes you wrote, the place names on the route, the neighbouring phrases and the recogniser's confidence in each word. The model only SUGGESTS word substitutions; they are stored as model
corrections (analysis/transcript_edits.py) that show highlighted and that you can overrule word by word."""
import glob, json, os
from strata360.pipeline import config
from strata360.analysis import transcript_edits as TE

SYSTEM = """You correct speech-recognition errors in transcripts of a runner talking to a camera during an ultra-distance race, and of people near them (English, with some French, Dutch, German).
You get numbered phrases; each word has a number and the recogniser's confidence (0-1) in brackets. Suggest a substitution ONLY where a word is clearly wrong: it makes no sense in context and a
similar-sounding word does (for example 'in the ark' for 'in the dark', a wrong name of a place or a race term). Do not rewrite style, grammar, fillers or dialect; do not translate; do not 'improve' correct
words; a low confidence alone is not a reason. Keep the punctuation attached to the word as in the original token (the 'to' text replaces the whole token). To remove a word that was clearly invented by
the recogniser (a repeated or hallucinated word) use an empty 'to'. Prefer few, certain fixes over many guesses.
Answer with JSON only: {"fixes": [{"seg": <phrase number>, "word": <word number>, "from": "<the token as given>", "to": "<replacement token>", "why": "<five words at most>"}]}"""


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


def clip_prompt(folder, clip, tr, clip_note=''):
    rows = []
    for si, s in enumerate(tr['segments']):
        ws = s.get('words') or []
        if not ws or not s.get('text', '').strip(): continue
        rows.append(f"[{si}] ({s['lang']}, {s['t0']:.1f}s) " + ' '.join(f"{wi}:{w['w'].strip()}({w.get('p', 0):.2f})" for wi, w in enumerate(ws)))
    return (context(folder) + (f"\nNote about this clip: {clip_note}" if clip_note else '') + f"\n\nClip {clip}. Phrases:\n" + '\n'.join(rows)) if rows else None


def run(folder, clips=None, provider=None, model=None, progress=None, log=print):
    """Suggest corrections for every clip (or those whose id contains one of `clips`). Returns {clip: number of suggestions stored}."""
    from strata360.edit import script as SC, llm_remote as LR
    from strata360.pipeline import notes as N
    cfg = config.load(folder); llm = cfg.get('llm', {}); provider = provider or llm.get('provider', 'vertex'); model = model or llm.get('model') or LR.PROVIDERS[provider]['default']
    dirs = sorted(glob.glob(os.path.join(config.race_dir(folder), 'clips', '*', ''))); dirs = [d for d in dirs if os.path.exists(d + 'transcript.json') and (not clips or any(c in os.path.basename(d.rstrip('/')) for c in clips))]
    try: nt = N.load(folder)
    except Exception: nt = {'clips': {}}
    out = {}
    for i, d in enumerate(dirs):
        clip = os.path.basename(d.rstrip('/')); tr = json.load(open(d + 'transcript.json')); prompt = clip_prompt(folder, clip, tr, (nt.get('clips') or {}).get(clip, ''))
        if prompt:
            r = SC.run_llm([dict(role='system', content=SYSTEM), dict(role='user', content=prompt)], model=model, max_tokens=4000, temperature=0.2, provider=provider)
            fixes = ((r.get('parsed') or {}).get('fixes')) if isinstance(r.get('parsed'), dict) else None
            out[clip] = TE.set_gemini(d, fixes or [], model=model); log(f'{clip}: {out[clip]} suggestion(s)')
        else: out[clip] = 0
        progress and progress(i + 1, len(dirs), sum(out.values()))
    return out
