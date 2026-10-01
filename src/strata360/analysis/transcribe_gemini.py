"""Transcribing a clip with Gemini from its AUDIO (not just correcting text): the original or the cleaned sound, with everything the project knows about the clip as context (what the runner wrote, where
and when it is, what the camera sees, who is talking), optionally with the recogniser's draft to correct. Gemini gives no word timings, so its transcript is turned into corrections of the recogniser's
words (analysis/transcript_edits.py) by aligning the two word sequences: the recogniser keeps the timing, Gemini decides the words."""
import base64, datetime as dt, difflib, json, os, re, subprocess
from strata360.pipeline import config

SYSTEM = """You transcribe speech from a recording made by a runner wearing a 360 camera during an ultra-distance race in Belgium, plus the people near them (mostly English, some French, Dutch, German).
Transcribe VERBATIM exactly what is said: keep fillers (um, uh), repeated words, false starts, dialect and ungrammatical speech; do not tidy, summarise or translate; do not invent words that are not
there; write numbers the way they are spoken. Use the context given (names, places, the runner's notes, what the camera sees) only to choose between similar-sounding words, never to add content.
Mark who is speaking: "wearer" is the runner wearing the camera (the nearest, loudest voice, talking to the camera or themselves); "other" is anyone else. Give each phrase's approximate start
time in seconds from the start of the recording and its language (en, fr, nl, de).
Answer with JSON only: {"phrases": [{"start_s": <number>, "speaker": "wearer"|"other", "lang": "en", "text": "<the words>"}]}"""


def prepare_audio(path, out):
    """Mono 16 kHz FLAC (what the model hears anyway): small enough to send in one request."""
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', path, '-ac', '1', '-ar', '16000', '-c:a', 'flac', out], check=True); return out


def context(folder, clip):
    """Everything we know about the clip, as text for the model."""
    from strata360.pipeline import meta, notes as N
    from strata360.gps import context as X, track as TRK
    rd = config.race_dir(folder); cd = os.path.join(rd, 'clips', clip); lines = []; J = lambda n: json.load(open(os.path.join(cd, n))) if os.path.exists(os.path.join(cd, n)) else None
    try: lines.append('Film / race: ' + meta.describe(folder))
    except Exception: pass
    nt = N.load(folder)
    if nt.get('folder'): lines.append("The runner's notes about the whole race: " + nt['folder'].strip()[:1500])
    if (nt.get('clips') or {}).get(clip): lines.append("The runner's note for this clip: " + nt['clips'][clip].strip())
    c = J('clip.json'); t0 = dt.datetime.fromisoformat(c['time']['start_utc'].replace('Z', '+00:00')); dur = c['video']['source_frames'] / c['video']['nominal_fps']
    from zoneinfo import ZoneInfo
    lines.append(f"This recording: {dur:.0f} seconds, starting {t0.astimezone(ZoneInfo('Europe/Brussels')).strftime('%A %d %B, %H:%M')} local time.")
    try:
        cfg = config.load(folder); tp = config.track_path(folder, cfg)
        if tp: lines.append('Track data: ' + X.describe(X.context_at(TRK.load(tp), t0.timestamp(), t0.timestamp() + dur, 'Europe/Brussels')))
    except Exception: pass
    pl = J('places.json')
    if pl and pl.get('covered') and pl.get('summary'): lines.append('Place: ' + pl['summary']['text'] + (f", on {pl['summary']['road']}" if pl['summary'].get('road') else '') + '. Nearby names (for spelling): ' + ', '.join(sorted({n['name'] for p in pl['points'] for n in (p.get('nearby') or [])[:5] if n.get('name')})[:25]))
    sc = J('scenes.json')
    if sc:
        its = [i for i in sc['items'] if i.get('ok') and i.get('view') == 'front' and i.get('description')]; step = max(1, len(its) // 8)
        lines.append('What the camera sees over time: ' + ' | '.join(f"{i['t_s']:.0f}s {i['setting']}: {i['description']}" for i in its[::step][:8]))
    sp = J('speakers.json')
    if sp: lines.append("Voice detector (who spoke when, approximate): " + '; '.join(f"{s['t0']:.0f}-{s['t1']:.0f}s {s.get('label') or '?'}" for s in sp['segments'])[:1200])
    idn = J('identity.json')
    if idn: lines.append('People in view (count by time): ' + ' '.join(f"{r['t_s']:.0f}s:{r['n_people']}" for r in idn['samples'][::max(1, len(idn['samples']) // 12)]))
    return '\n'.join(lines)


def whisper_draft(folder, clip):
    tr = json.load(open(os.path.join(config.race_dir(folder), 'clips', clip, 'transcript.json')))
    return '\n'.join(f"[{s['t0']:.1f}s] {s['text'].strip()}" for s in tr['segments'] if s.get('text', '').strip())


def parse_phrases(text):
    """The phrases from the model's reply: strict JSON if it is, else every complete {...} phrase object found in it (a reply cut off or wrapped in text still gives what it said)."""
    try:
        d = json.loads(text)
        if isinstance(d, dict) and isinstance(d.get('phrases'), list): return [p for p in d['phrases'] if isinstance(p, dict) and p.get('text')]
        if isinstance(d, list): return [p for p in d if isinstance(p, dict) and p.get('text')]
    except ValueError: pass
    out = []
    for m in re.finditer(r'\{[^{}]*"text"\s*:\s*"(?:[^"\\]|\\.)*"[^{}]*\}', text):
        try: out.append(json.loads(m.group(0)))
        except ValueError: continue
    return out


def transcribe(folder, clip, audio_path, with_draft=False, provider='vertex', model=None, extra_context=True):
    """One Gemini call; returns dict(phrases, text, seconds, tokens, raw)."""
    from strata360.edit import llm_remote as LR, script as SC
    data = base64.b64encode(open(audio_path, 'rb').read()).decode(); ctx = context(folder, clip) if extra_context else ''
    prompt = ('CONTEXT ABOUT THIS RECORDING:\n' + ctx if ctx else 'Transcribe this recording.') + ("\n\nA speech recogniser's DRAFT transcript (it makes mistakes; the audio decides):\n" + whisper_draft(folder, clip) if with_draft else '') + '\n\nTranscribe the audio now.'
    msgs = [dict(role='system', content=SYSTEM), dict(role='user', content=[dict(inlineData=dict(mimeType='audio/flac', data=data)), dict(text=prompt)])]
    r = LR.chat(msgs, model or LR.PROVIDERS[provider]['default'], 32000, 0.1, timeout=900, provider=provider, thinking='low'); ph = parse_phrases(r['text'])
    return dict(phrases=ph, text=' '.join(p.get('text', '') for p in ph), seconds=r['seconds'], tokens=r.get('tokens'), model=r.get('model'), finish=r.get('finish'), raw=r['text'])


# ---- comparing and turning into edits ----------------------------------------------------------------------------------------------------------------------------------------------------------
def norm(w): return re.sub(r"[^\w']+", '', w.lower().replace('’', "'"))


def tokens(text): return [norm(w) for w in text.split() if norm(w)]


def wer(ref, hyp):
    a, b = tokens(ref), tokens(hyp)
    if not a: return None
    d = list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        p, d[0] = d[0], i
        for j in range(1, len(b) + 1): p, d[j] = d[j], min(d[j] + 1, d[j - 1] + 1, p + (a[i - 1] != b[j - 1]))
    return d[len(b)] / len(a)


def edits_against(recognised_words, gemini_text):
    """Align Gemini's words to the recogniser's: {'subs': [(index, from, to)], 'insert': [(before index, words)], 'delete': [(index, word)], 'multi': [...]}. A substitution is a one-for-one swap of
    a word, which can be stored as a correction with the recogniser's timing; the rest is reported (a different number of words cannot keep one word's timing)."""
    a = [norm(w) for w in recognised_words]; gw = [w for w in gemini_text.split() if norm(w)]; b = [norm(w) for w in gw]; sm = difflib.SequenceMatcher(None, a, b, autojunk=False); out = dict(subs=[], insert=[], delete=[], multi=[])
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == 'replace' and i2 - i1 == j2 - j1: out['subs'] += [(i1 + k, recognised_words[i1 + k], gw[j1 + k]) for k in range(i2 - i1)]
        elif op == 'replace': out['multi'].append((i1, recognised_words[i1:i2], gw[j1:j2]))
        elif op == 'insert': out['insert'].append((i1, gw[j1:j2]))
        elif op == 'delete': out['delete'] += [(k, recognised_words[k]) for k in range(i1, i2)]
    return out
