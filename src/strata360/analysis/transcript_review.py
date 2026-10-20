"""Which phrases of the transcript most need a human ear: a worst-first queue for the review page.

Nothing new is stored by the recogniser's output: every phrase of `transcript.json` already has the model's confidence (`avg_logprob`, `no_speech`, and `p` for each word) and word times, so the speaking rate
(words a second) is worked out here from the word count over the time the words span. A phrase's `priority` adds up what is known to go wrong:

  * low confidence: -avg_logprob (0 sure ... 1+ unsure), and the share of its words the model gave under `LOW_WORD_P`
  * fast speech: words a second over `FAST_WPS` (recognisers drop and merge words when someone talks quickly: slowing the sound down is how a person checks)
  * the recogniser's own flags (low confidence, probably no speech, repetition, a phrase it is known to invent)

What a person has looked at is kept in `transcript_reviewed.json` beside the transcript (`{"reviewed": {"<segment>": {"t0": 3.2, "at": "..."}}}`); like a correction it applies only while the phrase is at the same place
(a new transcription makes old marks stale, so they are ignored). The recogniser's output is never changed."""
import datetime as dt, json, os

FILE = 'transcript_reviewed.json'
FAST_WPS = 4.5                  # words a second above which speech counts as fast (the median phrase of the Legends footage is 3.75)
NORMAL_WPS = 3.5                # the pace the "normalised" player slows fast speech down to
MIN_PACE_WORDS = 4              # a phrase shorter than this has no pace worth the name (two words in half a second is not fast speech)
MIN_RATE = 0.5                  # but never slower than half speed (it smears)
LOW_WORD_P = 0.5
CONTEXT_S = 1.5                 # sound played before the first and after the last word of a phrase, so it is heard in context (the page marks where the phrase itself is)
FLAG_WEIGHT = dict(hallucination_phrase=1.0, probably_no_speech=1.0, repetition=0.5, low_confidence=0.3)


def _now(): return dt.datetime.now().strftime('%Y-%m-%dT%H:%M:%S')


def load(d):
    try: return json.load(open(os.path.join(d, FILE))).get('reviewed', {})
    except (OSError, ValueError): return {}


def save(d, reviewed):
    p = os.path.join(d, FILE); tmp = p + '.tmp'; json.dump(dict(schema=1, reviewed=reviewed), open(tmp, 'w'), indent=1); os.replace(tmp, p)


def set_reviewed(d, si, t0, state=True):
    """Mark the phrase `si` (starting at `t0`) as looked at, or put it back in the queue (state False)."""
    r = load(d)
    if state: r[str(int(si))] = dict(t0=round(float(t0), 2), at=_now())
    else: r.pop(str(int(si)), None)
    save(d, r)


def is_reviewed(r, si, t0):
    e = r.get(str(si)); return bool(e) and abs(e.get('t0', t0) - t0) <= 0.06


def rate(seg):
    """Words a second over the span of the phrase's words (None when it has fewer than `MIN_PACE_WORDS` words)."""
    ws = [w for w in seg.get('words') or [] if w.get('w', '').strip()]
    if len(ws) < MIN_PACE_WORDS: return None
    span = ws[-1]['t1'] - ws[0]['t0']
    return round(len(ws) / span, 2) if span > 0.2 else None


def play_rate(wps):
    """The playback speed that brings a phrase spoken at `wps` words a second to the normal pace (1 when it is not faster than that)."""
    return 1.0 if not wps or wps <= NORMAL_WPS else round(max(MIN_RATE, NORMAL_WPS / wps), 2)


def stats(seg):
    """Confidence and pace of one recognised phrase, and the priority from them: {wps, logprob, no_speech, low_words, n_words, flags, priority}."""
    ws = [w for w in seg.get('words') or [] if w.get('w', '').strip()]; wps = rate(seg); lp = seg.get('avg_logprob')
    low = sum(1 for w in ws if w.get('p') is not None and w['p'] < LOW_WORD_P)
    pr = (min(max(-lp, 0.0), 1.5) if lp is not None else 0.0)                                  # 0 sure ... 1.5 hopeless
    pr += (low / len(ws)) if ws else 0.0
    pr += min(max(((wps or 0) - FAST_WPS) / 2.0, 0.0), 1.0)                                    # 4.5 w/s nothing, 6.5 w/s and over the most
    fl = list(seg.get('flags') or []); pr += sum(FLAG_WEIGHT.get(f, 0.0) for f in fl)
    return dict(wps=wps, logprob=lp, no_speech=seg.get('no_speech'), low_words=low, n_words=len(ws), flags=fl, priority=round(pr, 3))


def queue(clip_dirs, effective, clip_id):
    """Every phrase with words, worst first: [{clip, si, t0, t1, play0, play1, lang, text, words, ...stats, play_rate, reviewed}]. `effective(d)` is the clip's transcript with corrections applied (and the hidden phrases kept, flagged `hidden`), `clip_id(d)` its id.
    The confidence is the recogniser's, so it does not change when a word is corrected (the correction is what `reviewed` records)."""
    out = []
    for d in clip_dirs:
        tr = effective(d)
        if not tr: continue
        r = load(d); cid = clip_id(d)
        for si, s in enumerate(tr.get('segments', [])):
            if not (s.get('text') or '').strip() or not s.get('words'): continue
            st = stats(s); ws = [dict(i=i, w=w['w'], t0=w['t0'], t1=w['t1'], p=w.get('p'), **({'e': w['edit']} if w.get('edit') else {})) for i, w in enumerate(s['words'])]
            out.append(dict(clip=cid, si=si, t0=s['t0'], t1=s['t1'], play0=round(max(s['words'][0]['t0'] - CONTEXT_S, 0.0), 2), play1=round(s['words'][-1]['t1'] + CONTEXT_S, 2), lang=s.get('lang', 'en'),
                            text=s['text'].strip(), words=ws, play_rate=play_rate(st['wps']), reviewed=is_reviewed(r, si, s['t0']), hidden=bool(s.get('hidden')), **st))
    out.sort(key=lambda x: (x['hidden'], x['reviewed'], -x['priority'], x['clip'], x['si']))              # hidden phrases (taken out of the film's transcript) come last of all
    return out
