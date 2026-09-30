"""Add accurate word times and safe cut points to existing transcript.json files (no re-transcription; project venv).
For every non-suspect segment in a language that has an alignment model (English now; fr/nl/de need larger models, see wordtimes.LANGUAGE_MODELS),
run CTC forced alignment on the segment audio, refine, and compute the cut point for every gap between consecutive words.
Adds to each word: a0, a1 (aligned start/end, clip-relative seconds), a_score; and to each segment: cuts[] (per gap i between word i and i+1:
t, pause_s, safe). Whisper's own w.t0/w.t1 are kept unchanged, and should NOT be used for edit points (they are early by 120-190 ms).
  .venv/bin/python spike/align_transcripts.py LIBRARY_DIR ANALYSIS_DIR [--langs en]"""
import glob, json, os, sys, warnings
warnings.filterwarnings('ignore')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import audio as A, wordtimes as W

lib, ana = sys.argv[1], sys.argv[2]
langs = sys.argv[sys.argv.index('--langs') + 1].split(',') if '--langs' in sys.argv else ['en']
tot = dict(words=0, safe=0, gaps=0)
for jp in sorted(glob.glob(os.path.join(ana, '*.transcript.json'))):
    d = json.load(open(jp)); name = d['source']; todo = [s for s in d['segments'] if not s['suspect'] and s['lang'] in langs and s['words']]
    if not todo: continue
    x = A.load_audio(os.path.join(lib, name), 1)[:, 0]; x16 = A.ffmpeg_filter(x, A.SR, 'anull', out_sr=16000)[:, 0]
    for s in todo:
        a = max(s['t0'] - 0.5, 0.0); b = min(s['t1'] + 0.5, len(x16) / 16000)
        seg = x16[int(a * 16000):int(b * 16000)]
        al = W.force_align(seg, [w['w'] for w in s['words']], s['lang'])
        rf = W.refine_with_energy(al, seg, 16000); vad = W.vad_probabilities(seg)
        cuts = W.cut_points([None if r is None else (r[0], r[1], 0) for r in rf], seg, 16000, vad=vad)
        for w, r, q in zip(s['words'], rf, al):
            if r is not None: w['a0'], w['a1'], w['a_score'] = round(a + r[0], 3), round(a + r[1], 3), round(q[2], 2)
        s['cuts'] = [None if c is None else dict(t=round(a + c['t'], 3), pause_s=c['pause_s'], safe=c['safe']) for c in cuts]
        tot['words'] += len(s['words']); tot['gaps'] += sum(c is not None for c in cuts); tot['safe'] += sum(bool(c and c['safe']) for c in cuts)
    d['alignment'] = dict(model={l: W.LANGUAGE_MODELS[l] for l in langs}, method='CTC forced alignment + energy refinement; cuts from Silero VAD pauses', note='use a0/a1 and cuts[], not w.t0/t1')
    json.dump(d, open(jp, 'w'), ensure_ascii=False, indent=1)
    print(f"{name[4:18]}: {len(todo)} segments aligned", flush=True)
print(f"aligned {tot['words']} words; {tot['gaps']} word gaps, {tot['safe']} flagged safe cut points ({100 * tot['safe'] / max(tot['gaps'], 1):.0f}%)")
