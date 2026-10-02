"""The user's marks on a clip's transcript, word by word: MUST USE (green) and NEVER USE (red). A word with no mark is "don't care" (white); yellow, "could use and is used", is not stored: it is worked out from the draft script.

`transcript.json` is never changed; marks live beside it in `transcript_marks.json`, keyed like the corrections (`transcript_edits.json`) by `<segment>:<word>` of the RECOGNISED transcript, so a correction of a word keeps its mark:

  {"marks": {"<segment>:<word>": {"state": "must" | "never", "orig": "amazin", "t0": 0.7}}}

A mark applies only while the recognised word at that place is still `orig` (a new transcription makes old marks stale: they are ignored). Marks reach the script writer through script_pack, which splits a transcript line wherever the state changes."""
import copy, json, os

FILE = 'transcript_marks.json'
STATES = ('must', 'never')


def key(si, wi): return f'{int(si)}:{int(wi)}'


def load(d):
    try: return json.load(open(os.path.join(d, FILE))).get('marks', {})
    except (OSError, ValueError): return {}


def save(d, marks):
    p = os.path.join(d, FILE); tmp = p + '.tmp'; json.dump(dict(schema=1, marks=marks), open(tmp, 'w'), indent=1); os.replace(tmp, p)


def _raw(d): return json.load(open(os.path.join(d, 'transcript.json')))


def set_spans(d, spans, state):
    """Mark words. `spans`: [(segment, first word, last word)] (inclusive); `state`: 'must', 'never' or None (no mark). Raises IndexError for a word that does not exist, ValueError for another state."""
    if state is not None and state not in STATES: raise ValueError(f'state: one of {STATES} or None')
    tr = _raw(d); marks = load(d)
    for si, w0, w1 in spans:
        si, w0, w1 = int(si), int(w0), int(w1)
        if w1 < w0: w0, w1 = w1, w0
        segs = tr['segments']
        if not 0 <= si < len(segs) or w0 < 0 or w1 >= len(segs[si].get('words') or []): raise IndexError(f'no such word {si}:{w0}..{w1}')
        for wi in range(w0, w1 + 1):
            if state is None: marks.pop(key(si, wi), None)
            else: marks[key(si, wi)] = dict(state=state, orig=segs[si]['words'][wi]['w'], t0=segs[si]['t0'])
    save(d, marks); return marks


def states(d):
    """{(segment, word): state} for the marks that still match the recognised transcript (stale ones are left out)."""
    marks = load(d)
    if not marks: return {}
    try: segs = _raw(d).get('segments', [])
    except (OSError, ValueError): return {}
    out = {}
    for k, m in marks.items():
        try: si, wi = (int(x) for x in k.split(':'))
        except ValueError: continue
        if si < len(segs) and wi < len(segs[si].get('words') or []) and segs[si]['words'][wi]['w'] == m.get('orig') and abs(segs[si]['t0'] - m.get('t0', segs[si]['t0'])) <= 0.06 and m.get('state') in STATES: out[(si, wi)] = m['state']
    return out


def annotate(tr, d):
    """A copy of a transcript document (usually with corrections applied) whose marked words carry `mark` = 'must' | 'never'."""
    out = copy.deepcopy(tr)
    for (si, wi), st in states(d).items():
        try: out['segments'][si]['words'][wi]['mark'] = st
        except (IndexError, KeyError): pass
    return out
