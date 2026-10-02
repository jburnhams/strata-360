"""The words in the music track (implementation plan V7, step L1): where it is sung, so the film can keep the voice-over and the runner's speech out of the singing, and so the script writer can be told what the music says and when.

  build(folder) -> the status dict; writes `<project>/lyrics.json` (what the recogniser heard, untouched) and nothing else. Your corrections live in `lyrics_edits.json`, so finding the lyrics again keeps them.
  view(folder)  -> the record with your corrections applied, and `vocal_spans` (where it is sung, in seconds from the start of the track) worked out from the phrases that are neither doubtful nor deleted.

Speech recognition on music is rough: it hears the words of a rapped or clearly sung verse well enough to tell WHEN it is sung, and gets some words wrong (and invents a repeated line over a quiet stretch). So the times are the product, the text is a guide, and each phrase has a confidence
(`exp(avg log probability) * (1 - no_speech / 2)`); under `DOUBT` it is marked doubtful and does not count as sung. Delete a phrase, or correct its text, and the vocal spans follow. The recogniser runs without its voice-activity filter: with music
under the voice the filter hears nothing and the track comes back empty (found on the Legends track)."""
import hashlib, json, math, os, time

from strata360.pipeline import config

VERSION = 1                   # bump when the way the record is made changes what it says
MODEL = 'small'               # faster-whisper model (the speech stage's engine)
DOUBT = 0.30                  # a phrase below this confidence is not counted as sung
PAD_S = 0.3                   # a sung stretch is wider than its words by this much each side
JOIN_S = 1.5                  # sung stretches closer than this are one
MIN_SUNG_S = 5.0              # less than this much singing in the whole track: it is instrumental


def path_of(folder): return os.path.join(config.race_dir(folder), 'lyrics.json')


def edits_path(folder): return os.path.join(config.race_dir(folder), 'lyrics_edits.json')


def _load(p, default):
    try: return json.load(open(p))
    except (OSError, ValueError): return default


def _write(p, doc):
    os.makedirs(os.path.dirname(p), exist_ok=True); tmp = p + '.tmp'; json.dump(doc, open(tmp, 'w'), indent=1, ensure_ascii=False); os.replace(tmp, p)


def track_of(folder):
    """(absolute path, signature) of the project's music track from music.json, or (None, None)."""
    rec = _load(os.path.join(config.race_dir(folder), 'music.json'), None)
    if not rec or not rec.get('file'): return None, None
    p = os.path.join(config.race_dir(folder), rec['file']); return (p, rec.get('sig')) if os.path.exists(p) else (None, None)


def key_of(sig): return hashlib.sha1(json.dumps([VERSION, MODEL, sig]).encode()).hexdigest()[:12]


def confidence(avg_logprob, no_speech): return round(math.exp(min(float(avg_logprob), 0.0)) * (1.0 - 0.5 * min(max(float(no_speech), 0.0), 1.0)), 3)


def phrase_key(t0, t1): return f'{round(float(t0), 1)}-{round(float(t1), 1)}'


def vocal_spans(phrases, pad=PAD_S, join=JOIN_S):
    """[(a, b)] seconds where it is sung: the phrases that count (not doubtful, not deleted) widened by `pad`, joined when closer than `join`."""
    out = []
    for p in sorted((p for p in phrases if p['counts']), key=lambda p: p['t0']):
        a, b = max(p['t0'] - pad, 0.0), p['t1'] + pad
        if out and a - out[-1][1] <= join: out[-1][1] = max(out[-1][1], b)
        else: out.append([a, b])
    return [(round(a, 2), round(b, 2)) for a, b in out]


def view(folder):
    """The lyrics record with your corrections applied (None when there is no record): each phrase has `key`, `conf`, `doubtful`, `deleted`, `edited`, `text` (yours when you changed it) and `counts` (sung and trusted); plus `vocal_spans`, `sung_s`, `instrumental`."""
    doc = _load(path_of(folder), None)
    if not doc: return None
    ed = _load(edits_path(folder), {}); phrases = []
    for i, p in enumerate(doc['phrases']):
        k = phrase_key(p['t0'], p['t1']); e = ed.get(k) or {}; conf = confidence(p['avg_logprob'], p['no_speech']); doubtful = conf < DOUBT; deleted = bool(e.get('deleted')); text = e.get('text') or p['text']
        phrases.append(dict(p, key=k, id=f'L{i + 1:02d}', text=text, heard=p['text'], conf=conf, doubtful=doubtful, deleted=deleted, edited=bool(e.get('text')), counts=not deleted and (not doubtful or bool(e.get('keep')))))
    spans = vocal_spans(phrases); sung = round(sum(b - a for a, b in spans), 1)
    return dict(doc, phrases=phrases, vocal_spans=spans, sung_s=sung, instrumental=sung < MIN_SUNG_S)


def status(folder):
    """{has_track, exists, stale, instrumental, phrases, sung_s, duration_s, made_at, language}: whether there is a track to listen to, whether a record exists and whether it was made from another track or settings."""
    p, sig = track_of(folder); v = view(folder); stale = bool(v and p and v.get('key') != key_of(sig))
    return dict(has_track=bool(p), exists=bool(v), stale=stale, instrumental=bool(v and v['instrumental']), phrases=len(v['phrases']) if v else 0, sung_s=v['sung_s'] if v else None, duration_s=v.get('duration_s') if v else None,
                made_at=v.get('made_at') if v else None, language=v.get('language') if v else None)


def _transcribe(path):
    """faster-whisper on the track, word times on, no voice-activity filter: ([{t0, t1, text, avg_logprob, no_speech, words}], {language, language_probability, duration_s})."""
    from faster_whisper import WhisperModel
    segs, info = WhisperModel(MODEL, device='cpu', compute_type='int8').transcribe(path, word_timestamps=True, vad_filter=False, beam_size=5, condition_on_previous_text=False)
    out = [dict(t0=round(s.start, 2), t1=round(s.end, 2), text=s.text.strip(), avg_logprob=round(s.avg_logprob, 3), no_speech=round(s.no_speech_prob, 3),
                words=[dict(w=w.word.strip(), t0=round(w.start, 2), t1=round(w.end, 2), p=round(w.probability, 2)) for w in (s.words or [])]) for s in segs if s.text.strip()]
    return out, dict(language=info.language, language_probability=round(info.language_probability, 2), duration_s=round(info.duration, 1))


def build(folder, log=print, transcriber=None):
    """Listen to the track and write lyrics.json (your corrections are kept). Raises RuntimeError with the reason when there is no track."""
    path, sig = track_of(folder)
    if not path: raise RuntimeError('there is no music track yet: add one first')
    log('listening to the track'); t0 = time.time(); phrases, info = (transcriber or _transcribe)(path)
    _write(path_of(folder), dict(key=key_of(sig), version=VERSION, model=MODEL, track_sig=sig, made_at=time.strftime('%Y-%m-%dT%H:%M:%S'), seconds=round(time.time() - t0, 1), phrases=phrases, **info))
    s = status(folder); log(f"lyrics: {s['phrases']} phrases, {s['sung_s']} s sung" + (' (instrumental)' if s['instrumental'] else '')); return s


def edit(folder, key, text=None, deleted=None, keep=None):
    """Correct a phrase: new `text`, `deleted` (it is not sung / not a lyric), `keep` (count it as sung although the recogniser doubted it). Passing text '' or deleted/keep False undoes that correction. Returns the phrase, or None when there is no such phrase."""
    v = view(folder)
    if not v or not any(p['key'] == key for p in v['phrases']): return None
    ed = _load(edits_path(folder), {}); e = ed.setdefault(key, {})
    if text is not None: e['text'] = text.strip() or None
    if deleted is not None: e['deleted'] = bool(deleted)
    if keep is not None: e['keep'] = bool(keep)
    e = {k: v_ for k, v_ in e.items() if v_}; ed = {k: v_ for k, v_ in dict(ed, **{key: e}).items() if v_}; _write(edits_path(folder), ed)
    return next(p for p in view(folder)['phrases'] if p['key'] == key)


def reset(folder, corrections=False):
    """Forget the record (and, with `corrections`, your corrections too); returns whether there was one."""
    had = False
    for p in [path_of(folder)] + ([edits_path(folder)] if corrections else []):
        if os.path.exists(p): os.remove(p); had = True
    return had
