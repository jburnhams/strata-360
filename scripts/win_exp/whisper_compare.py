"""Experiment: Whisper large-v3-turbo (the pipeline's model) against the full large-v3 on the existing segments, on the GPU.

  python scripts/win_exp/whisper_compare.py PROJECT_FOLDER OUT.json
Per segment (+-0.25 s of audio_original.flac, the detected language): both models' text, the seconds each took, the word difference between them, and how many of the Gemini corrections each reproduces."""
import glob, json, os, re, subprocess, sys, time
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))
from strata360 import hw


def norm(t): return re.sub(r"[^a-z0-9' ]+", ' ', (t or '').lower()).split()


def main():
    folder, out = sys.argv[1:3]; hw._cuda_dll_dirs(); import jiwer
    from faster_whisper import WhisperModel
    d, c = hw.whisper_args(); M = {n: WhisperModel(n, device=d, compute_type=c) for n in ('large-v3-turbo', 'large-v3')}; T = dict.fromkeys(M, 0.0); rows = []; E = dict(diff=0, ref=0); hit = {n: 0 for n in M}; nedit = 0; audio_s = 0.0
    for cdir in sorted(glob.glob(os.path.join(folder, 'strata360', 'clips', '*'))):
        tj = json.load(open(os.path.join(cdir, 'transcript.json')))
        if not tj['segments']: continue
        ep = os.path.join(cdir, 'transcript_edits.json'); edits = json.load(open(ep)).get('edits', {}) if os.path.exists(ep) else {}
        wav = np.frombuffer(subprocess.run(['ffmpeg', '-v', 'error', '-i', os.path.join(cdir, 'audio_original.flac'), '-ac', '1', '-ar', '16000', '-f', 'f32le', '-'], capture_output=True).stdout, np.float32).copy()
        for i, s in enumerate(tj['segments']):
            x = wav[max(int((s['t0'] - 0.25) * 16000), 0):int((s['t1'] + 0.25) * 16000)]
            if len(x) < 1600: continue
            audio_s += len(x) / 16000; txt = {}
            for n, m in M.items():
                t = time.time(); segs, _ = m.transcribe(x, language=s['lang'], beam_size=5, condition_on_previous_text=False, vad_filter=False); txt[n] = ' '.join(sg.text for sg in segs).strip(); T[n] += time.time() - t
            a, b = norm(txt['large-v3-turbo']), norm(txt['large-v3'])
            if a:
                o = jiwer.process_words(' '.join(a), ' '.join(b) or '<e>'); E['diff'] += o.substitutions + o.deletions + o.insertions; E['ref'] += len(a)
            for j, w in enumerate(s.get('words') or []):
                g = ((edits.get(f'{i}:{j}') or {}).get('gemini') or {}).get('text')
                if g and norm(g) and norm(g) != norm(w['w']):
                    nedit += 1
                    for n in M: hit[n] += set(norm(g)) <= set(norm(txt[n]))
            rows.append(dict(clip=os.path.basename(cdir), seg=i, lang=s['lang'], pipeline=s['text'], **txt))
    res = dict(segments=len(rows), audio_s=round(audio_s, 1), seconds={k: round(v, 1) for k, v in T.items()}, word_difference_turbo_vs_v3=round(E['diff'] / max(E['ref'], 1), 3), gemini_corrections=nedit, reproduced=hit)
    json.dump(dict(summary=res, rows=rows), open(out, 'w'), indent=1, ensure_ascii=False); print(json.dumps(res, indent=1))


if __name__ == '__main__': main()
