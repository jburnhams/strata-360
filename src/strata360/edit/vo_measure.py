"""Measure the spoken voice-over (implementation plan V3; overview 17.1 step 5, 17.2 `vo.json`).

Nothing is squeezed or cut here. Each line of the block script (`script.write_block_script`) is spoken by the synthetic voice, or recorded by you, at its natural length, and then
measured: how long the file is, where the speech starts and ends inside it, the time of every word (the line's text force-aligned to the audio, then snapped to the speech energy, as
for the footage in `audio/align.py`), how well the words fit the audio and how loud it is. The next step (V4, `edit/vo_fit.py`) sizes the film's blocks to these lengths.

Two ways to measure:
  * `measure_take`: one file per line (a synthetic line, or a recording of one line);
  * `measure_recording`: one recording of several lines read in a row, split into lines by aligning all their words at once.
Both report a line that does not match its text: `short` (words missing), `long` (extra or repeated words) or `mismatch` (the words do not fit the audio), and a line with no audio
at all is `missing`. The aligner is a parameter (default: the wav2vec2 aligner of `audio/wordtimes.py`), so the logic is testable without the model.

`vo.json` (in `<project>/voiceover/`): per line, key, block, anchor, text, take ('synth' | 'recorded'), file, natural_s, speech_start_s, speech_end_s, lead_s, trail_s, words, score,
loudness_db, status and a signature. A line is measured again only when its text, its voice or its audio file changed."""
import hashlib, json, os
import numpy as np
from strata360.audio import wordtimes as W

SPEECH_BELOW_DB = 35.0           # speech = hops within this many dB of the file's loudest hop
JOIN_GAP_S = 0.25                # silences shorter than this stay inside one stretch of speech
MIN_SCORE = 0.25                 # aligner confidence below this = the words do not fit the audio (as in audio/align.py)
MIN_ALIGNED = 0.8                # at least this share of the words must be alignable
SHORT_RATIO = 0.45               # speech shorter than this share of the expected time = words missing
LONG_RATIO = 2.2                 # longer than this many times the expected time = extra or repeated words
READ_WPM = 150.0                 # the expected reading speed (the voice at speed 1.0)
EDGE_S = 0.02                    # speech boundaries sit this far outside the energy edge, so no breath of the word is cut


def read_audio(path):
    """(mono float samples, sample rate) of a wav file."""
    from scipy.io import wavfile
    sr, x = wavfile.read(path); x = np.asarray(x)
    if x.dtype.kind in 'iu': x = x.astype(np.float64) / float(np.iinfo(x.dtype).max)
    else: x = x.astype(np.float64)
    return (x.mean(axis=1) if x.ndim > 1 else x), sr


def speech_runs(x, sr, below_db=SPEECH_BELOW_DB, join_gap_s=JOIN_GAP_S):
    """Stretches of speech [(start_s, end_s)]: the hops within `below_db` of the loudest, with gaps under `join_gap_s` closed."""
    t, e = W.energy_envelope(x, sr)
    if len(e) == 0 or float(e.max()) < -80: return []
    on = e >= e.max() - below_db; runs = []; i = 0; hop = t[1] - t[0] if len(t) > 1 else 0.005
    while i < len(on):
        if on[i]:
            j = i
            while j + 1 < len(on) and on[j + 1]: j += 1
            runs.append([t[i] - hop / 2, t[j] + hop / 2]); i = j + 1
        else: i += 1
    out = []
    for a, b in runs:
        if out and a - out[-1][1] < join_gap_s: out[-1][1] = b
        else: out.append([a, b])
    n = len(x) / sr
    return [(max(a - EDGE_S, 0.0), min(b + EDGE_S, n)) for a, b in out]


def loudness_db(x, a, b, sr):
    """RMS level (dBFS) of the speech between a and b."""
    seg = x[int(a * sr):int(b * sr)]
    return round(float(10 * np.log10(np.mean(seg ** 2) + 1e-12)), 1) if len(seg) else -120.0


def expected_s(text, wpm=READ_WPM): return max(len(text.split()), 1) * 60.0 / wpm


def default_aligner(x16, words, lang='en'): return W.force_align(x16, words, lang)


def _to16(x, sr):
    from scipy import signal
    return signal.resample_poly(x, 16000, sr).astype(np.float32) if sr != 16000 else x.astype(np.float32)


def _align(x, sr, a, b, words, aligner):
    """Word times (file seconds, snapped to the energy) of `words` spoken between a and b: [(t0, t1, score) | None]."""
    off = max(a - 0.3, 0.0); seg = x[int(off * sr):int(min(b + 0.3, len(x) / sr) * sr)]
    al = aligner(_to16(seg, sr), words); out = [None if r is None else (r[0] + off, r[1] + off, r[2]) for r in al]
    return W.refine_with_energy(out, x, sr)


def _fit_status(words, al, speech_s):
    """('ok' | 'short' | 'long' | 'mismatch', mean score, share aligned) for a line's words against its audio."""
    good = [r for r in al if r is not None]; frac = len(good) / max(len(words), 1); score = float(np.mean([r[2] for r in good])) if good else 0.0
    exp = expected_s(' '.join(words))
    if speech_s <= 0 or not good: return 'mismatch', round(score, 3), round(frac, 3)
    if speech_s < SHORT_RATIO * exp: st = 'short'
    elif speech_s > LONG_RATIO * exp: st = 'long'
    elif score < MIN_SCORE or frac < MIN_ALIGNED: st = 'mismatch'
    else: st = 'ok'
    return st, round(score, 3), round(frac, 3)


def _word_docs(words, al):
    return [dict(w=w, t0=None if r is None else round(r[0], 3), t1=None if r is None else round(r[1], 3), score=None if r is None else round(r[2], 2)) for w, r in zip(words, al)]


def measure_take(path, text, aligner=None):
    """Measure one line's audio file at its natural length. The result has the file's length, where the speech starts and ends in it, the words with their times in the file, the alignment
    score and the loudness."""
    aligner = aligner or default_aligner; x, sr = read_audio(path); n = len(x) / sr; runs = speech_runs(x, sr); words = text.split()
    if not runs: return dict(natural_s=round(n, 3), speech_start_s=None, speech_end_s=None, lead_s=round(n, 3), trail_s=0.0, words=_word_docs(words, [None] * len(words)), score=0.0, aligned=0.0, loudness_db=-120.0, status='silent')
    a, b = runs[0][0], runs[-1][1]; al = _align(x, sr, a, b, words, aligner) if words else []
    st, score, frac = _fit_status(words, al, b - a)
    return dict(natural_s=round(n, 3), speech_start_s=round(a, 3), speech_end_s=round(b, 3), lead_s=round(a, 3), trail_s=round(n - b, 3), words=_word_docs(words, al), score=score, aligned=frac,
                loudness_db=loudness_db(x, a, b, sr), status=st)


def measure_recording(path, lines, aligner=None):
    """One recording of several lines read in a row. `lines`: [{key, text}] in reading order. Every word is aligned in one pass; a line runs from its first word to its last. Returns a dict
    key -> measurement (times in the recording) and the pauses between consecutive lines, in order. A missing, short or repeated line shows as a status other than 'ok'."""
    aligner = aligner or default_aligner; x, sr = read_audio(path); runs = speech_runs(x, sr)
    if not runs: return {l['key']: dict(status='silent', words=[], speech_start_s=None, speech_end_s=None, score=0.0, aligned=0.0, loudness_db=-120.0) for l in lines}
    a, b = runs[0][0], runs[-1][1]; words = []; owner = []
    for li, l in enumerate(lines):
        for w in l['text'].split(): words.append(w); owner.append(li)
    al = _align(x, sr, a, b, words, aligner); out = {}; prev_end = None
    for li, l in enumerate(lines):
        idx = [i for i, o in enumerate(owner) if o == li]; lw = [words[i] for i in idx]; la = [al[i] for i in idx]; good = [r for r in la if r is not None]
        if not good: out[l['key']] = dict(status='missing', words=_word_docs(lw, la), speech_start_s=None, speech_end_s=None, score=0.0, aligned=0.0, loudness_db=-120.0, pause_before_s=None); continue
        s0, s1 = min(r[0] for r in good), max(r[1] for r in good); st, score, frac = _fit_status(lw, la, s1 - s0)
        out[l['key']] = dict(status=st, words=_word_docs(lw, la), speech_start_s=round(s0, 3), speech_end_s=round(s1, 3), score=score, aligned=frac, loudness_db=loudness_db(x, s0, s1, sr),
                             pause_before_s=None if prev_end is None else round(s0 - prev_end, 3)); prev_end = s1
    return out


# ------------------------------------------------------------------------------------------------------------------------------------------------ the lines of a block script
def line_keys(doc):
    """[(key, line)] for the lines of a block script, in film order. A key is stable while the block, the anchor and the line's place among them do: `003b0` (block 3, before the dialogue, first line)."""
    seen = {}; out = []
    for l in doc.get('lines') or []:
        a = {'before': 'b', 'after': 'a'}.get(l.get('anchor'), 'n'); k = (l['block'], a); n = seen.get(k, 0); seen[k] = n + 1
        out.append((f"{int(l['block']):03d}{a}{n}", l))
    return out


def vo_path(folder):
    from strata360.edit import voiceover as V
    return os.path.join(V.base(folder), 'vo.json')


def load(folder):
    try: return json.load(open(vo_path(folder)))
    except (OSError, ValueError): return None


def save(folder, doc):
    from strata360.edit import voiceover as V
    os.makedirs(V.base(folder), exist_ok=True); tmp = vo_path(folder) + '.tmp'; json.dump(doc, open(tmp, 'w'), indent=1); os.replace(tmp, vo_path(folder))


def _file_sig(path, text, voice):
    st = os.stat(path); return hashlib.sha1(f'{text}|{voice}|{st.st_size}|{int(st.st_mtime)}'.encode()).hexdigest()[:12]


def measure_script(folder, doc, aligner=None, resolve=None, log=None):
    """Speak (or take the recording of) every line of a block script at its natural length, measure it and write `vo.json`. Lines whose text, voice and audio file are unchanged are
    reused, so recording a new take measures only that line. `resolve(key, text) -> (take, path)` can replace the default (the saved recording if there is one, else the synthetic line)."""
    from strata360.edit import voiceover as V
    st = V.load_state(folder); old = {l['key']: l for l in (load(folder) or {}).get('lines', [])}
    if resolve is None:
        st['engine'], st['voice'] = V.pick(st)
        def resolve(key, text):
            rp = V.recorded_path(folder, key)
            if os.path.exists(rp) and st['use'].get(key) != 'synth': return 'recorded', rp
            return 'synth', V.synth_line(folder, key, text, st['engine'], st['voice'], st['rate'])
    out = []; pairs = line_keys(doc)
    for i, (key, l) in enumerate(pairs):
        text = l['text'].strip()
        if not text: continue
        take, path = resolve(key, text)
        if not path or not os.path.exists(path): out.append(dict(key=key, block=l['block'], anchor=l.get('anchor'), text=text, take=take, file=None, status='missing', sig=None)); continue
        sig = _file_sig(path, text, st.get('voice')); prev = old.get(key)
        if prev and prev.get('sig') == sig and prev.get('take') == take: m = prev
        else:
            m = dict(key=key, block=l['block'], anchor=l.get('anchor'), text=text, take=take, file=os.path.relpath(path, V.base(folder)), sig=sig, **measure_take(path, text, aligner))
        out.append(dict(m, block=l['block'], anchor=l.get('anchor')))
        if log: log(i + 1, len(pairs))
    doc_out = dict(schema=1, script_title=doc.get('title'), engine=st.get('engine'), voice=st.get('voice'), rate=st.get('rate'), lines=out,
                   total_speech_s=round(sum((m.get('speech_end_s') or 0) - (m.get('speech_start_s') or 0) for m in out), 3), problems=[dict(key=m['key'], status=m['status']) for m in out if m['status'] != 'ok'])
    save(folder, doc_out); return doc_out
