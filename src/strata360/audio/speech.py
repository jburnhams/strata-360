"""Multilingual speech transcription with per-segment language identification and English translation (run with the project venv).

  1. voice-activity detection splits the audio into speech chunks (Silero VAD bundled with faster-whisper), close chunks merged
  2. each chunk gets its OWN language identification, restricted to the languages plausible for the event (default en, fr, nl, de;
     Belgium), so a clip that mixes languages, or a one-word clip, is not forced into a single wrong language
  3. each chunk is transcribed in its detected language (with word timestamps and confidence)
  4. every non-English segment is translated to English with a dedicated translation model (Helsinki-NLP OPUS-MT, fr/nl/de -> en),
     applied to the native transcript; the original text is always kept. (Whisper's own "translate" task was tried first and is
     unreliable: it summarises and drifts on noisy speech, see docs/progress.md.)
Output (transcript.json body): segments [{t0, t1, lang, lang_prob, lang_scores, text, text_en, avg_logprob, no_speech, words:[{w,t0,t1,p}]}].
All times are clip-relative seconds. Everything runs locally; nothing is uploaded.

  .venv/bin/python spike/speech.py CAM.OSV out.json [--model small] [--translate-model small] [--languages en,fr,nl,de] [--denoise none|dfn|mossformer]
"""
import argparse, json, os, sys, time, warnings
warnings.filterwarnings('ignore')
import numpy as np
from strata360.audio import dsp as A

ALLOWED = ['en', 'fr', 'nl', 'de']
# Phrases whisper is known to invent over silence, music and noise (subtitle credits, sign-offs). Matching segments are flagged, not deleted.
HALLUCINATION_PATTERNS = [r'sous-?titr', r'subtitles? (by|from)', r'amara\.org', r'thanks? for watching', r'thank you for watching', r"merci d'avoir regard",
                          r'ondertitel', r'untertitel', r'subscribe', r'like and subscribe', r'transcription by', r'vertaling door', r'copyright', r'www\.', r'\.com\b']


def flag_segment(seg):
    import re
    flags = []
    if any(re.search(p, seg['text'], re.I) for p in HALLUCINATION_PATTERNS): flags.append('hallucination_phrase')
    if seg['avg_logprob'] < -1.0: flags.append('low_confidence')
    if seg['no_speech'] > 0.6: flags.append('probably_no_speech')
    if seg['words']:
        rep_ratio = 1 - len({w['w'].lower() for w in seg['words']}) / len(seg['words'])
        if len(seg['words']) >= 6 and rep_ratio > 0.6: flags.append('repetition')
    return flags
_MT = {}


def translate_text(text, lang):
    """Translate `text` from `lang` (fr, nl, de, ...) to English with OPUS-MT (MarianMT, runs locally; models download on first use)."""
    if lang == 'en' or not text.strip(): return text
    from transformers import MarianMTModel, MarianTokenizer
    if lang not in _MT:
        name = f'Helsinki-NLP/opus-mt-{lang}-en'
        _MT[lang] = (MarianTokenizer.from_pretrained(name), MarianMTModel.from_pretrained(name).eval())
    tok, mdl = _MT[lang]
    import torch
    with torch.no_grad():
        out = mdl.generate(**tok([text], return_tensors='pt', truncation=True, max_length=256), num_beams=4, max_new_tokens=256)
    return tok.decode(out[0], skip_special_tokens=True)


def load_models(model='small', translate_model=None):
    from faster_whisper import WhisperModel
    m = WhisperModel(model, device='cpu', compute_type='int8')
    return m, (m if translate_model in (None, model) else WhisperModel(translate_model, device='cpu', compute_type='int8'))


def speech_chunks(x16, max_len=18.0, merge_gap=0.6, pad=0.25):
    from faster_whisper.vad import get_speech_timestamps, VadOptions
    ts = get_speech_timestamps(x16, VadOptions(min_silence_duration_ms=400, speech_pad_ms=int(pad * 1000)))
    chunks = []
    for t in ts:
        a, b = t['start'] / 16000, t['end'] / 16000
        if chunks and a - chunks[-1][1] <= merge_gap and b - chunks[-1][0] <= max_len: chunks[-1][1] = b
        else: chunks.append([a, b])
    return chunks


def identify_language(model, audio, allowed):
    lang, prob, scores = model.detect_language(audio)[:3]
    sc = {l: float(p) for l, p in scores}
    best = max(allowed, key=lambda l: sc.get(l, 0.0))
    tot = sum(sc.get(l, 0.0) for l in allowed) + 1e-9
    return best, sc.get(best, 0.0) / tot, {l: round(sc.get(l, 0.0), 3) for l in allowed}, lang


def transcribe_multilingual(x16, model, translate_model=None, allowed=ALLOWED, translate=True, whisper_translate=False):
    """Segments: one per whisper segment (a phrase, typically 2-8 s), each with the language identified for its VAD chunk."""
    out = []
    for a, b in speech_chunks(x16):
        seg = x16[int(a * 16000):int(b * 16000)].astype(np.float32)
        if len(seg) < 0.3 * 16000: continue
        lang, lp, scores, raw_lang = identify_language(model, seg, allowed)
        segs, _ = model.transcribe(seg, language=lang, word_timestamps=True, beam_size=5, condition_on_previous_text=False, vad_filter=False)
        for s in segs:
            text = s.text.strip()
            if not text: continue
            words = [dict(w=w.word.strip(), t0=round(a + w.start, 2), t1=round(a + w.end, 2), p=round(float(w.probability), 2)) for w in (s.words or [])]
            d = dict(t0=round(a + s.start, 2), t1=round(a + s.end, 2), lang=lang, lang_prob=round(lp, 2), lang_scores=scores, whisper_top_lang=raw_lang, text=text,
                     text_en=translate_text(text, lang) if translate else text, avg_logprob=round(float(s.avg_logprob), 2), no_speech=round(float(s.no_speech_prob), 2), words=words)
            if whisper_translate and lang != 'en':      # kept only for comparison
                ts, _ = (translate_model or model).transcribe(seg, language=lang, task='translate', beam_size=5, condition_on_previous_text=False, vad_filter=False)
                d['text_en_whisper_chunk'] = ' '.join(t.text.strip() for t in ts).strip()
            d['flags'] = flag_segment(d); d['suspect'] = bool(set(d['flags']) & {'hallucination_phrase', 'probably_no_speech', 'repetition'})
            out.append(d)
    return out


if __name__ == '__main__':
    ap = argparse.ArgumentParser(); ap.add_argument('media'); ap.add_argument('out')
    ap.add_argument('--model', default='small'); ap.add_argument('--translate-model', default=None)
    ap.add_argument('--languages', default=','.join(ALLOWED)); ap.add_argument('--denoise', default='none', choices=['none', 'dfn', 'mossformer', 'afftdn'])
    a = ap.parse_args(); t0 = time.time()
    x = A.load_audio(a.media, 1)[:, 0]
    if a.denoise != 'none': x16 = A.enhance_speech(x, A.SR, 'asr', denoise=a.denoise)
    else: x16 = A.ffmpeg_filter(x, A.SR, 'anull', out_sr=16000)[:, 0]
    m, tm = load_models(a.model, a.translate_model)
    segs = transcribe_multilingual(x16, m, tm, a.languages.split(','))
    json.dump(dict(source=os.path.basename(a.media), model=a.model, translate_model=a.translate_model or a.model, denoise=a.denoise, languages=a.languages.split(','),
                   seconds=round(time.time() - t0, 1), segments=segs), open(a.out, 'w'), ensure_ascii=False, indent=1)
    for s in segs: print(f"{s['t0']:6.1f}-{s['t1']:6.1f} [{s['lang']} {s['lang_prob']:.2f}] {s['text']}" + (f"\n{'':17s}-> {s['text_en']}" if s['lang'] != 'en' else ''))
