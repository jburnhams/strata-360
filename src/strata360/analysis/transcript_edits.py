"""Corrections laid over a clip's transcript, word by word, so the recognised timings keep matching.

`transcript.json` is the recogniser's output and is never changed. Corrections live beside it in `transcript_edits.json`:

  {"edits": {"<segment>:<word>": {"orig": "amazin", "t0": 0.7,
                                  "gemini": {"text": "amazing", "why": "...", "model": "...", "at": "..."},
                                  "user":   {"text": "amazing,", "at": "..."}}}}

A word's shown text is the user's correction if there is one, else the model's, else the recogniser's. Each correction replaces one recognised word (a token with its punctuation) and keeps that word's
timing, so every window, cut and subtitle that depends on timing is unaffected. A correction applies only while the recognised word at that place is still `orig` (a new transcription makes old
corrections stale: they are ignored and reported). The user can restore the original (a user entry equal to `orig`, which also overrules the model) or drop their own entry to show the model's again."""
import copy, datetime as dt, json, os

FILE = 'transcript_edits.json'


def _now(): return dt.datetime.now().strftime('%Y-%m-%dT%H:%M:%S')


def key(si, wi): return f'{int(si)}:{int(wi)}'


def load(d):
    try: return json.load(open(os.path.join(d, FILE))).get('edits', {})
    except (OSError, ValueError): return {}


def save(d, edits):
    p = os.path.join(d, FILE); tmp = p + '.tmp'; json.dump(dict(schema=1, edits=edits), open(tmp, 'w'), indent=1); os.replace(tmp, p)


def shown(e):
    """(text, source) of an edit entry: the user's, else the model's, else None."""
    if e.get('user') is not None: return e['user']['text'], 'user'
    if e.get('gemini') is not None: return e['gemini']['text'], 'gemini'
    return None, None


def apply(tr, edits):
    """A copy of the transcript document with the corrections applied. Corrected words carry `edit` = {orig, src, why, user_text, gemini_text}; segments with any carry `edited`; their `text` (and the
    English `text_en` of an English segment) is rebuilt from the words. Returns (document, stale keys)."""
    out = copy.deepcopy(tr); stale = []
    for k, e in edits.items():
        try: si, wi = (int(x) for x in k.split(':'))
        except ValueError: stale.append(k); continue
        segs = out.get('segments', [])
        if si >= len(segs) or wi >= len(segs[si].get('words') or []) or segs[si]['words'][wi]['w'] != e.get('orig') or abs(segs[si]['t0'] - e.get('t0', segs[si]['t0'])) > 0.06: stale.append(k); continue
        text, src = shown(e)
        if text is None: continue
        w = segs[si]['words'][wi]
        w['edit'] = dict(orig=e['orig'], src=src, why=(e.get('gemini') or {}).get('why'), user_text=(e.get('user') or {}).get('text'), gemini_text=(e.get('gemini') or {}).get('text'))
        w['w'] = text; segs[si]['edited'] = True
    for s in out.get('segments', []):
        if s.get('edited'):
            was = s.get('text', ''); s['text'] = ' '.join(w['w'].strip() for w in s['words'] if w['w'].strip())
            if s.get('lang') == 'en' or (s.get('text_en') or '').strip() == was.strip(): s['text_en'] = s['text']
    return out, stale


def load_effective(d):
    """The clip folder's transcript with corrections applied (None when it has no transcript)."""
    p = os.path.join(d, 'transcript.json')
    if not os.path.exists(p): return None
    return apply(json.load(open(p)), load(d))[0]


def _orig(d, si, wi):
    tr = json.load(open(os.path.join(d, 'transcript.json'))); w = tr['segments'][si]['words'][wi]; return w['w'], tr['segments'][si]['t0']


def set_user(d, si, wi, text):
    """The user's correction of one word (text may be empty: the word is hidden). Setting it to the recognised word restores the original and overrules the model."""
    edits = load(d); orig, t0 = _orig(d, int(si), int(wi)); e = edits.setdefault(key(si, wi), dict(orig=orig, t0=t0)); e['user'] = dict(text=text.strip(), at=_now()); save(d, edits); return e


def clear_user(d, si, wi):
    """Drop the user's correction: the model's shows again (or the original, if there is none)."""
    edits = load(d); e = edits.get(key(si, wi))
    if e: e.pop('user', None)
    if e and not e.get('gemini'): edits.pop(key(si, wi), None)
    save(d, edits)


def set_gemini(d, suggestions, model=None):
    """Replace this clip's model corrections with `suggestions` [{seg, word, to, why}]; the user's own corrections are kept. Returns the number stored."""
    edits = load(d); tr = json.load(open(os.path.join(d, 'transcript.json')))
    for k in list(edits):
        edits[k].pop('gemini', None)
        if not edits[k].get('user'): edits.pop(k)
    n = 0
    for s in suggestions:
        try: si, wi = int(s['seg']), int(s['word']); w = tr['segments'][si]['words'][wi]
        except (KeyError, ValueError, IndexError, TypeError): continue
        to = str(s.get('to', '')).strip()
        if to == w['w'].strip() or (s.get('from') is not None and str(s['from']).strip() != w['w'].strip()): continue
        e = edits.setdefault(key(si, wi), dict(orig=w['w'], t0=tr['segments'][si]['t0'])); e['gemini'] = dict(text=to, why=str(s.get('why', ''))[:200], model=model, at=_now()); n += 1
    save(d, edits); return n
