"""An independent transcript from Gemini 3.5 Transcribe (a dedicated speech model: no instructions, no JSON; audio in, text out), laid over Whisper's words as per-word corrections.

Big requests. The free tier counts REQUESTS, not tokens, and this model takes about an hour of audio per request (98k input tokens, 25 per second); the paid key is billed, so requests are kept to about two minutes of speech: the speech of a clip (or of several short ones) goes in one request: the
speech-only excerpts of the clips (analysis/transcript_fix.chunks, from the cleaned audio) joined with 2 s of silence, as lossless FLAC (Opus saved space but changed 12% of the words), up to
`MAX_BYTES` / `MAX_AUDIO_S` per request. The model is deterministic (the same audio gives the same text, whatever the prompt), so one request per batch is all there is to ask.

From text to corrections. The text of a batch is aligned to the concatenated Whisper words of the same excerpts (difflib on normalised words). One word for one word becomes a correction of that word;
a different number of words in a run becomes a correction of the run (stored on its first word, the rest hidden); words only one side has are reported, never applied (spoken repeats are real).
Because it needs no instructions, it is a vote of a different KIND from the prompted models: its errors are not theirs."""
import base64, difflib, hashlib, json, os, re, time, urllib.error, urllib.request
import numpy as np
from strata360.pipeline import config
from strata360.analysis import transcript_fix as TF, transcribe_gemini as TG, transcript_edits as TE

MODEL = 'gemini-3.5-transcribe'
URL = 'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent'
GAP_S = 2.0
FILLERS = {'um', 'uh', 'er', 'erm', 'uhm', 'hmm', 'mm', 'ah', 'eh'}   # this model writes them, Whisper leaves them out: not corrections
MIN_LIKE = 0.5                                                        # the correction must look like the word it replaces (where the two transcripts drift apart, words get paired with unrelated ones)
MAX_RUN = 3                                                           # a replaced run longer than this (either side) is a different reading of the whole stretch, not a correction
MAX_BYTES = 16 * 1024 * 1024          # inline request limit is about 20 MB with the base64 overhead
MAX_AUDIO_S = 120.0                    # about two minutes of speech a request (the paid key: not huge requests)
SR = 16000


def items(folder, clips=None):
    """Everything with speech, in clip order: [{clip, dir, tr, audio, chunks}]."""
    out = []
    for d in sorted(__import__('glob').glob(os.path.join(config.race_dir(folder), 'clips', '*', ''))):
        clip = os.path.basename(d.rstrip('/'))
        if clips and not any(c in clip for c in clips): continue
        if not os.path.exists(d + 'transcript.json') or not os.path.exists(d + 'clip.json'): continue
        au = next((d + n for n in ('audio_clean.flac', 'audio_original.flac') if os.path.exists(d + n)), None)
        tr = json.load(open(d + 'transcript.json')); cj = json.load(open(d + 'clip.json')); chs = TF.chunks(tr, cj['video']['source_frames'] / cj['video']['nominal_fps'])
        if au and chs: out.append(dict(clip=clip, dir=d, tr=tr, audio=au, chunks=chs))
    return out


def batches(its, max_audio_s=MAX_AUDIO_S, max_bytes=MAX_BYTES):
    """Group excerpts into requests: [[(item index, excerpt index)]] in order; a batch is closed when the next excerpt would pass the audio or size limit (FLAC of speech is about 2.2 MB a minute)."""
    out, cur, secs = [], [], 0.0
    for i, it in enumerate(its):
        for j, ch in enumerate(it['chunks']):
            d = ch['a1'] - ch['a0'] + GAP_S
            if cur and (secs + d > max_audio_s or (secs + d) * 2.2e6 / 60 > max_bytes): out.append(cur); cur, secs = [], 0.0
            cur.append((i, j)); secs += d
    if cur: out.append(cur)
    return out


def build_audio(its, batch):
    """FLAC bytes of the batch's excerpts (16 kHz mono) with GAP_S of silence between them."""
    from strata360.audio import dsp
    import subprocess
    cache = {}; parts = []
    for i, j in batch:
        it = its[i]
        if i not in cache: cache[i] = dsp.load_audio(it['audio'], 1, sr=SR)[:, 0]
        ch = it['chunks'][j]; parts.append(cache[i][int(ch['a0'] * SR):int(ch['a1'] * SR)]); parts.append(np.zeros(int(GAP_S * SR), np.float32))
    x = np.concatenate(parts).astype(np.float32)
    return subprocess.run(['ffmpeg', '-v', 'error', '-f', 'f32le', '-ar', str(SR), '-ac', '1', '-i', '-', '-c:a', 'flac', '-f', 'flac', '-'], input=x.tobytes(), capture_output=True, check=True).stdout


def draft_words(its, batch):
    """The Whisper words of the batch's excerpts in order: [(clip index, segment, word, text)]."""
    out = []
    for i, j in batch:
        tr = its[i]['tr']
        for si in its[i]['chunks'][j]['segs']:
            for wi, w in enumerate(tr['segments'][si].get('words') or []): out.append((i, si, wi, w['w']))
    return out


def transcribe(audio_bytes, cache_dir=None, usage=None, log=print):
    """One request: the text, from the cache when this exact audio was sent before. Raises LLMBusy on overload or quota (retryable)."""
    from strata360.edit import llm_remote as LR
    key = hashlib.sha1(audio_bytes + MODEL.encode()).hexdigest()[:16]; cp = os.path.join(cache_dir, key + '.json') if cache_dir else None
    if cp and os.path.exists(cp):
        try: return json.load(open(cp))['text'], True
        except (OSError, ValueError, KeyError): pass
    body = dict(contents=[dict(role='user', parts=[dict(inlineData=dict(mimeType='audio/flac', data=base64.b64encode(audio_bytes).decode())), dict(text='Transcribe this audio.')])]); t0 = time.time()
    r, tier = LR.gemini_post(MODEL, body, timeout=600)                                     # the free key first, the paid key when the free one is at its limit
    parts = (r.get('candidates') or [{}])[0].get('content', {}).get('parts', []); text = ' '.join(p.get('audioTranscription', {}).get('text', '') or p.get('text', '') for p in parts).strip()
    if not text: raise LR.LLMBusy('the transcription model returned nothing (will retry)')
    u = r.get('usageMetadata', {})
    if cp:
        os.makedirs(cache_dir, exist_ok=True); json.dump(dict(key=key, model=MODEL, text=text, tokens=u.get('promptTokenCount'), seconds=round(time.time() - t0, 1), kb=round(len(audio_bytes) / 1024), tier=tier, at=time.time()), open(cp + '.tmp', 'w'), indent=1); os.replace(cp + '.tmp', cp)
    if usage:
        try: open(usage, 'a').write(json.dumps(dict(at=time.time(), model=MODEL, tier=tier, tokens=dict(input=u.get('promptTokenCount'), output=0), seconds=round(time.time() - t0, 1), audio_kb=round(len(audio_bytes) / 1024))) + '\n')
        except OSError: pass
    return text, False


def align(draft, text):
    """Corrections from aligning the transcript `text` to `draft` [(item, seg, word, token)]: {item: [fix]} where a fix is {seg, word, through, to, from, why} (the format of the other checks), plus counts of what could not be applied."""
    gw = [w for w in text.split() if TG.norm(w) and TG.norm(w) not in FILLERS]; a = [TG.norm(d[3]) for d in draft]; b = [TG.norm(w) for w in gw]
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False); fixes = {}; skipped = dict(insert=0, delete=0, cross=0, equal=0)
    def add(i0, i1, to):
        s = draft[i0][:2]
        if difflib.SequenceMatcher(None, ''.join(TG.norm(d[3]) for d in draft[i0:i1]), ''.join(TG.norm(w) for w in to.split())).ratio() < MIN_LIKE: skipped['unlike'] = skipped.get('unlike', 0) + 1; return
        if any(draft[k][:2] != s for k in range(i0, i1)): skipped['cross'] += 1; return                      # a run across phrases (or clips): not one correction
        it, si, wi, _ = draft[i0]; fixes.setdefault(it, []).append(dict(seg=si, word=wi, through=draft[i1 - 1][2], to=to, **{'from': ' '.join(d[3] for d in draft[i0:i1])}, why='the transcription model heard this', model=MODEL))
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == 'equal': skipped['equal'] += i2 - i1
        elif op == 'replace':
            if i2 - i1 == j2 - j1:
                for k in range(i2 - i1): add(i1 + k, i1 + k + 1, gw[j1 + k])
            elif max(i2 - i1, j2 - j1) <= MAX_RUN: add(i1, i2, ' '.join(gw[j1:j2]))
            else: skipped['long'] = skipped.get('long', 0) + 1
        elif op == 'insert': skipped['insert'] += j2 - j1
        elif op == 'delete': skipped['delete'] += i2 - i1
    return fixes, skipped


def draft_hash(tr):
    return hashlib.sha1(json.dumps([[w['w'] for w in (s.get('words') or [])] for s in tr['segments']]).encode()).hexdigest()[:12]


def load(clip_dir, tr):
    """The corrections the transcription model implies for a clip (None when there are none for the current Whisper words)."""
    try: d = json.load(open(os.path.join(clip_dir, 'transcribe35.json')))
    except (OSError, ValueError): return None
    return d['fixes'] if d.get('draft') == draft_hash(tr) else None


def ensure(folder, clip, log=print):
    """Make sure the batch pass has been made for this clip: when its file is missing, ALL clips lacking one are transcribed together (big requests), once, whichever clip asks first."""
    import fcntl
    cd = os.path.join(config.race_dir(folder), 'clips', clip)
    if not os.path.exists(cd + '/transcript.json'): return
    tr = json.load(open(cd + '/transcript.json'))
    if load(cd, tr) is not None: return
    lock = os.path.join(config.race_dir(folder), 'transcribe35.lock'); os.makedirs(os.path.dirname(lock), exist_ok=True)
    with open(lock, 'w') as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        if load(cd, tr) is None: run(folder, None, log=log, only_missing=True)


def run(folder, clips=None, log=print, progress=None, only_missing=False):
    """Transcribe every clip's speech in big batches and store, per clip, the corrections it implies in `<clip>/transcribe35.json`. Requests already made are never repeated (cached on disk). Returns a summary."""
    its = items(folder, clips)
    if only_missing: its = [it for it in its if load(it['dir'], it['tr']) is None]
    bs = batches(its); cache = os.path.join(config.race_dir(folder), 'transcribe35'); usage = TF.usage_log_path(folder); per = {i: [] for i in range(len(its))}; made = reused = 0; failed = []
    for n, batch in enumerate(bs):
        try: audio = build_audio(its, batch); text, cached = transcribe(audio, cache, usage, log)
        except Exception as e:
            if not getattr(e, 'retryable', False): raise
            failed.append(str(e)); log(f'batch {n + 1}/{len(bs)}: {e}'); continue
        made += 0 if cached else 1; reused += 1 if cached else 0
        fx, sk = align(draft_words(its, batch), text)
        for i, lst in fx.items(): per[i].extend(lst)
        for i in {i for i, _ in batch}: json.dump(dict(model=MODEL, draft=draft_hash(its[i]['tr']), fixes=sorted(per[i], key=lambda f: (f['seg'], f['word'])), skipped=sk, batch=n, at=time.time()), open(its[i]['dir'] + 'transcribe35.json', 'w'), indent=1)
        log(f'batch {n + 1}/{len(bs)}: {sum(len(v) for v in fx.values())} corrections ({sk["insert"]} inserted and {sk["delete"]} missing words not applied), {"cached" if cached else "new request"}')
        progress and progress(n + 1, len(bs))
    if failed:
        from strata360.pipeline.retry import RetryLater
        raise RetryLater(f'{len(failed)} of {len(bs)} batches failed for now ({failed[0][:100]}); {made + reused} done and kept', progress=made > 0)
    return dict(batches=len(bs), clips=len(its), made=made, reused=reused, corrections=sum(len(v) for v in per.values()))


def apply_clip(folder, clip, log=print):
    """Store the transcription model's corrections for one clip as its Gemini corrections (the transcription-only way of the `transcript_check` stage). Returns a summary document."""
    cd = os.path.join(config.race_dir(folder), 'clips', clip); tr = json.load(open(cd + '/transcript.json'))
    ensure(folder, clip, log=log); fx = load(cd, tr) or []
    n = TE.set_gemini(cd, fx, model=MODEL)
    return dict(settings=dict(mode='transcribe', model=MODEL), proposed=len(fx), stored=n, kept=fx)
