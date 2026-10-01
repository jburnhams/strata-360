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
        try: si, wi = int(s['seg']), int(s['word']); words = tr['segments'][si]['words']; wj = int(s.get('through', wi)); w = words[wi]
        except (KeyError, ValueError, IndexError, TypeError): continue
        if wj < wi or wj >= len(words): continue
        to = str(s.get('to', '')).strip(); old = ' '.join(x['w'].strip() for x in words[wi:wj + 1])
        if not to or to == old or (s.get('from') is not None and wi == wj and str(s['from']).strip() != w['w'].strip()): continue
        for k, ww in enumerate(words[wi:wj + 1]):                                       # a run of words becomes one corrected text on the first word, the rest are hidden: every word keeps its timing
            e = edits.setdefault(key(si, wi + k), dict(orig=ww['w'], t0=tr['segments'][si]['t0']))
            e['gemini'] = dict(text=to if k == 0 else '', why=str(s.get('why', ''))[:200] + ('' if k == 0 else ' (part of the correction of the word before)'), model=model, at=_now(), votes=s.get('votes'))
        n += 1
    save(d, edits); return n


# ---- long phrases are shown (and played) in parts ------------------------------------------------------------------------------------------------------------------------------------------------
MAX_PHRASE_S = 10.0; MIN_PART_S = 5.0; PLAY_PAD = (0.1, 0.3)       # whisper's word times run about 0.15 s early: play a little before the first word and after the last
SENTENCE_END = ('.', '?', '!', '…')
CLOSERS = '"\')”’'                                                  # quotes and brackets that may follow the full stop


def split_points(words, max_s=MAX_PHRASE_S, min_s=MIN_PART_S):
    """Where to break a phrase of timed words into parts: only after a sentence end, and only if every resulting part is longer than `min_s` seconds; a phrase of `max_s` or less is left whole.
    Returns the list of (first word, last word + 1) index ranges."""
    n = len(words)
    if not n or words[-1]['t1'] - words[0]['t0'] <= max_s: return [(0, n)]
    cuts = []; start = 0
    for k in range(n - 1):
        w = words[k]['w'].strip().rstrip(CLOSERS)
        if not w.endswith(SENTENCE_END): continue
        if words[k]['t1'] - words[start]['t0'] > min_s and words[-1]['t1'] - words[k + 1]['t0'] > min_s: cuts.append(k + 1); start = k + 1
    b = [0] + cuts + [n]; return [(b[i], b[i + 1]) for i in range(len(b) - 1)]


def parts(seg):
    """The pieces of one (corrected) transcript segment for display and playback: [{w0, w1, t0, t1, play0, play1, text, words}], words carrying their index `i` in the whole phrase. Phrases in another
    language (their English translation is not word-aligned) are not split."""
    ws = seg.get('words') or []
    foreign = seg.get('lang', 'en') != 'en' and seg.get('text_en') and seg['text_en'].strip() != (seg.get('text') or '').strip()
    rng = [(0, len(ws))] if (foreign or not ws) else split_points(ws); out = []
    for a, b in rng:
        w = ws[a:b]; t0 = w[0]['t0'] if w else seg['t0']; t1 = w[-1]['t1'] if w else seg['t1']
        out.append(dict(w0=a, w1=b, t0=round(t0, 2), t1=round(t1, 2), play0=round(max(t0 - PLAY_PAD[0], 0.0), 2), play1=round(t1 + PLAY_PAD[1], 2), words=[dict(w, i=a + j) for j, w in enumerate(w)]))
    return out
