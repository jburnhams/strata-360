"""Experiment: NVIDIA Parakeet-TDT-0.6B-v3 and Canary-1B-v2 (ONNX int8, onnx-asr) against the project's Whisper large-v3-turbo transcripts, per existing segment.

  python scripts/win_exp/asr_compare.py PROJECT_FOLDER OUT.json [--clips PATTERN]

Reference texts: the pipeline's own transcript (Whisper large-v3-turbo, `text`), and the same with the Gemini corrections applied (`transcript_edits.json`, the votes of the transcript check). Each existing segment
(+-0.25 s) is cut from audio_original.flac and given to each model; Canary also gets the segment's detected language and translates to English (against `text_en`, OPUS-MT's translation of Whisper's).
Reports word agreement (1 - WER after lower-casing and dropping punctuation) between each pair, how many Gemini corrections each model reproduces, and the time taken."""
import argparse, glob, json, os, re, subprocess, sys, time
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))
from strata360 import hw

CANARY_LANGS = {'bg', 'cs', 'da', 'de', 'el', 'en', 'es', 'et', 'fi', 'fr', 'hr', 'hu', 'it', 'lt', 'lv', 'mt', 'nl', 'pl', 'pt', 'ro', 'ru', 'sk', 'sl', 'sv', 'uk'}


def norm(t): return re.sub(r"[^a-z0-9' ]+", ' ', (t or '').lower().replace('�', '')).split()


def wer_counts(ref, hyp):
    import jiwer
    r, h = ' '.join(ref), ' '.join(hyp)
    if not r: return (0, len(hyp))
    o = jiwer.process_words(r, h if h else '<empty>'); return (o.substitutions + o.deletions + o.insertions, len(ref))


def audio16(path):
    return np.frombuffer(subprocess.run(['ffmpeg', '-v', 'error', '-i', path, '-ac', '1', '-ar', '16000', '-f', 'f32le', '-'], capture_output=True).stdout, np.float32).copy()


def corrected(seg_i, seg, edits):
    out = []
    for j, w in enumerate(seg.get('words') or []):
        e = edits.get(f'{seg_i}:{j}')
        g = (e or {}).get('gemini')
        out.append(w['w'] if not g else g['text'])
    return ' '.join(out) if seg.get('words') else seg['text']


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('folder'); ap.add_argument('out'); ap.add_argument('--clips', default='*'); a = ap.parse_args()
    hw._cuda_dll_dirs(); import onnx_asr, onnxruntime
    prov = ['CUDAExecutionProvider', 'CPUExecutionProvider'] if 'CUDAExecutionProvider' in onnxruntime.get_available_providers() else ['CPUExecutionProvider']
    root = os.path.join(os.path.dirname(__file__), '..', '..', 'models', 'exp')
    pk = onnx_asr.load_model('nemo-parakeet-tdt-0.6b-v3', os.path.join(root, 'parakeet-tdt-0.6b-v3-onnx'), quantization='int8', providers=prov)
    cn = onnx_asr.load_model('nemo-canary-1b-v2', os.path.join(root, 'canary-1b-v2-onnx'), quantization='int8', providers=prov)
    T = dict(parakeet=0.0, canary=0.0, canary_en=0.0); audio_s = 0.0; rows = []; errs = {k: [0, 0] for k in ('whisper_vs_parakeet', 'whisper_vs_canary', 'gemini_vs_whisper', 'gemini_vs_parakeet', 'gemini_vs_canary', 'trans_vs_canary_en')}; hit = dict(whisper=0, parakeet=0, canary=0, n=0)
    for cdir in sorted(glob.glob(os.path.join(a.folder, 'strata360', 'clips', a.clips))):
        tj = json.load(open(os.path.join(cdir, 'transcript.json'))); ep = os.path.join(cdir, 'transcript_edits.json'); edits = json.load(open(ep)).get('edits', {}) if os.path.exists(ep) else {}
        if not tj['segments']: continue
        wav = audio16(os.path.join(cdir, 'audio_original.flac'))
        for i, s in enumerate(tj['segments']):
            seg = wav[max(int((s['t0'] - 0.25) * 16000), 0):int((s['t1'] + 0.25) * 16000)]
            if len(seg) < 1600: continue
            audio_s += len(seg) / 16000; lang = s['lang'] if s['lang'] in CANARY_LANGS else 'en'
            t = time.time(); p = str(pk.recognize(seg)); T['parakeet'] += time.time() - t
            t = time.time(); c = str(cn.recognize(seg, language=lang)); T['canary'] += time.time() - t
            t = time.time(); ce = str(cn.recognize(seg, language=lang, target_language='en')) if lang != 'en' else c; T['canary_en'] += time.time() - t
            w, g = norm(s['text']), norm(corrected(i, s, edits)); pn, cnn = norm(p), norm(c)
            for k, (r, h) in dict(whisper_vs_parakeet=(w, pn), whisper_vs_canary=(w, cnn), gemini_vs_whisper=(g, w), gemini_vs_parakeet=(g, pn), gemini_vs_canary=(g, cnn), trans_vs_canary_en=(norm(s['text_en']), norm(ce))).items():
                e, n = wer_counts(r, h); errs[k][0] += e; errs[k][1] += n
            for j, wd in enumerate(s.get('words') or []):
                ed = edits.get(f'{i}:{j}'); gm = (ed or {}).get('gemini')
                if gm and gm['text'] and norm(gm['text']) != norm(wd['w']):
                    hit['n'] += 1; gw = set(norm(gm['text'])); hit['whisper'] += bool(gw & set(w) and False); hit['parakeet'] += bool(gw <= set(pn)); hit['canary'] += bool(gw <= set(cnn))
            rows.append(dict(clip=os.path.basename(cdir), seg=i, t0=s['t0'], t1=s['t1'], lang=s['lang'], whisper=s['text'], gemini=corrected(i, s, edits), parakeet=p, canary=c, canary_en=ce, text_en=s['text_en']))
        print(os.path.basename(cdir), len(rows), 'segments so far', flush=True)
    summary = {k: dict(wer=round(e / max(n, 1), 4), words=n) for k, (e, n) in errs.items()}
    summary['gemini_corrections'] = hit; summary['audio_seconds'] = round(audio_s, 1); summary['seconds'] = {k: round(v, 1) for k, v in T.items()}; summary['providers'] = prov
    json.dump(dict(summary=summary, rows=rows), open(a.out, 'w'), indent=1, ensure_ascii=False); print(json.dumps(summary, indent=1))


if __name__ == '__main__': main()
