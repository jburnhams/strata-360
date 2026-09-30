"""Accurate word times and safe cut points for a transcript (README 5.11), with a consistency gate.

Forced alignment can go wrong around fillers ("um"), overlapping speech and mumbling: in the Belgian library a segment's first four words
came out 500-900 ms early. Each aligned word is therefore checked against whisper's own time (whisper is systematically 120-190 ms early but
never hundreds of ms out) and against the aligner's confidence; words that fail are marked `ok: false`, and any cut point next to such a word
is never marked safe. Nothing unreliable is silently trusted."""
import numpy as np
from strata360.audio import dsp as A, wordtimes as W

MAX_DISAGREE_S = 0.40      # aligned word start may differ from whisper's by at most this
MIN_SCORE = 0.25           # aligner confidence (mean character probability)


def align_transcript(osv, transcript, langs, log=None):
    """Returns the alignment.json body: per eligible segment, aligned words (a0, a1, score, ok) and cuts (t, pause_s, safe)."""
    x = A.load_audio(osv, 1)[:, 0]; x16 = A.ffmpeg_filter(x, A.SR, 'anull', out_sr=16000)[:, 0]
    out, tot = [], dict(segments=0, words=0, ok=0, gaps=0, safe=0)
    for si, s in enumerate(transcript['segments']):
        if s.get('suspect') or s['lang'] not in langs or not s['words']: continue
        a = max(s['t0'] - 0.5, 0.0); b = min(s['t1'] + 0.5, len(x16) / 16000)
        seg = x16[int(a * 16000):int(b * 16000)]
        al = W.force_align(seg, [w['w'] for w in s['words']], s['lang'])
        rf = W.refine_with_energy(al, seg, 16000); vad = W.vad_probabilities(seg)
        cuts = W.cut_points([None if r is None else (r[0], r[1], 0) for r in rf], seg, 16000, vad=vad)
        words = []
        for w, r, q in zip(s['words'], rf, al):
            if r is None: words.append(dict(a0=None, a1=None, score=None, ok=False)); continue
            a0, a1 = a + r[0], a + r[1]
            ok = abs(a0 - w['t0']) <= MAX_DISAGREE_S and q[2] >= MIN_SCORE
            words.append(dict(a0=round(a0, 3), a1=round(a1, 3), score=round(q[2], 2), ok=bool(ok)))
        cl = []
        for i, c in enumerate(cuts):
            if c is None: cl.append(None); continue
            safe = bool(c['safe'] and words[i]['ok'] and words[i + 1]['ok'])
            cl.append(dict(t=round(a + c['t'], 3), pause_s=c['pause_s'], safe=safe))
        out.append(dict(index=si, t0=s['t0'], t1=s['t1'], lang=s['lang'], quality=round(float(np.mean([w['ok'] for w in words])), 2), words=words, cuts=cl))
        tot['segments'] += 1; tot['words'] += len(words); tot['ok'] += sum(w['ok'] for w in words)
        tot['gaps'] += sum(c is not None for c in cl); tot['safe'] += sum(bool(c and c['safe']) for c in cl)
        if log: log(f"    segment {si}: {len(words)} words, quality {out[-1]['quality']:.2f}")
    return dict(model={l: W.LANGUAGE_MODELS[l] for l in langs if l in W.LANGUAGE_MODELS}, method='CTC forced alignment + energy refinement; cut points from Silero VAD pauses',
                gate=dict(max_disagree_s=MAX_DISAGREE_S, min_score=MIN_SCORE), note="use a0/a1 and cuts[] (times are clip-relative seconds); whisper's own word times are early by 120-190 ms and must not be used for edit points",
                summary=tot, segments=out)
