"""Word-boundary accuracy against KNOWN truth (run with the project venv): each word is synthesised separately, trimmed to its audible
extent, and joined with known gaps (0, 40, 100, 200 ms), so the true start and end of every word are exact. Optionally buried in real noise.
Compares: whisper word times, CTC forced alignment, and CTC + energy refinement; and the cut points chosen from each.
  .venv/bin/python spike/test_wordtimes.py"""
import difflib, os, re, subprocess, sys, tempfile, warnings
warnings.filterwarnings('ignore')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import audio as A, wordtimes as W
from faster_whisper import WhisperModel

SR = A.SR; TMP = tempfile.mkdtemp(); rng = np.random.default_rng(7)
SENT = ["Nearly at the summit now, feeling good, the legs are holding up well.", "Aid station in about two kilometres, I will take on some water there.",
        "The weather is turning so I am putting the jacket on before the ridge.", "Absolutely loving this section, the trail is beautiful today.",
        "Kilometre forty five and still smiling, let us keep it moving."]
GAPS = [0.0, 0.0, 0.04, 0.10, 0.20]
LIB = '/Volumes/Expansion/2026-02-19 - Legends'

def say_word(word, voice):
    p = f'{TMP}/{voice}_{re.sub("[^a-z0-9]", "_", word.lower())}.aiff'
    if not os.path.exists(p): subprocess.run(['say', '-v', voice, '-o', p, word], check=True)
    x = A.load_audio(p, 1)[:, 0]
    t, e = W.energy_envelope(x, SR); on = np.where(e > e.max() - 35)[0]
    a, b = int(max(t[on[0]] - 0.0025, 0) * SR), int((t[on[-1]] + 0.0025) * SR)
    return x[a:b] * (10 ** (-20 / 20) / (np.sqrt(np.mean(x[a:b] ** 2)) + 1e-9))

def build(text, voice):
    words = text.split(); parts, truth, pos = [np.zeros(int(0.5 * SR))], [], 0.5
    for i, w in enumerate(words):
        x = say_word(re.sub(r'[^A-Za-z0-9\']', '', w), voice); truth.append((pos, pos + len(x) / SR)); parts.append(x); pos += len(x) / SR
        g = GAPS[rng.integers(len(GAPS))] if i + 1 < len(words) else 0.5
        parts.append(np.zeros(int(g * SR))); pos += g
    return np.concatenate(parts).astype(np.float32), words, truth

def noise_excerpt(kind):
    if kind == 'wind': f, a = 'CAM_20260221081441_0017_D.OSV', 17.4
    else: f, a = 'CAM_20260219165639_0003_D.OSV', 20.9
    return A.load_audio(f'{LIB}/{f}', 1)[:, 0][int(a * SR):int((a + 12) * SR)]

def match(hyp_words, ref_words):
    norm = lambda s: re.sub(r"[^a-z0-9']", '', s.lower())
    h, r = [norm(w) for w in hyp_words], [norm(w) for w in ref_words]
    sm = difflib.SequenceMatcher(a=r, b=h, autojunk=False); pairs = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == 'equal': pairs += list(zip(range(i1, i2), range(j1, j2)))
    return pairs

model = WhisperModel('large-v3-turbo', device='cpu', compute_type='int8')
def whisper_words(x):
    x16 = A.ffmpeg_filter(x, SR, 'anull', out_sr=16000)[:, 0]
    segs, _ = model.transcribe(x16, language='en', word_timestamps=True, beam_size=5, condition_on_previous_text=False, vad_filter=False)
    return x16, [(w.word.strip(), w.start, w.end) for s in segs for w in (s.words or [])]

results = {}; cuts = {}
conds = [('clean', None, None), ('wind +9 dB', 'wind', 9), ('babble +3 dB', 'ambience', 3)]
for cname, nk, snr in conds:
    for si, text in enumerate(SENT):
        x, words, truth = build(text, ['Daniel', 'Samantha'][si % 2])
        if nk:
            nz = noise_excerpt(nk); nz = np.tile(nz, 2)[:len(x)]
            bp = lambda y: A.ffmpeg_filter(y, SR, 'highpass=f=300,lowpass=f=3400')[:, 0]
            x = (x + nz * (np.sqrt(np.mean(bp(x) ** 2)) / np.sqrt(np.mean(bp(nz) ** 2))) * 10 ** (-snr / 20)).astype(np.float32) * 0.6
        x16, hw = whisper_words(x)
        pairs = match([w[0] for w in hw], words)
        if len(pairs) < 0.6 * len(words): continue
        aligned = W.force_align(x16, [w[0] for w in hw], 'en'); vad = W.vad_probabilities(x16)
        refined = W.refine_with_energy(aligned, x16, 16000)
        M = {'whisper': [(w[1], w[2]) for w in hw], 'CTC': [None if a is None else (a[0], a[1]) for a in aligned], 'CTC+energy': [None if a is None else (a[0], a[1]) for a in refined]}
        for meth, ts in M.items():
            for ri, hi in pairs:
                if ts[hi] is None: continue
                d = results.setdefault((cname, meth), {'start': [], 'end': [], 'gap0': [], 'gapN': []})
                es, ee = (ts[hi][0] - truth[ri][0]) * 1e3, (ts[hi][1] - truth[ri][1]) * 1e3
                d['start'].append(es); d['end'].append(ee)
            # cut points: gaps between consecutive matched truth words
            cp = W.cut_points([None if t is None else (t[0], t[1], 0) for t in ts], x16, 16000, vad=vad)
            for (ri, hi), (rj, hj) in zip(pairs, pairs[1:]):
                if rj != ri + 1 or hj != hi + 1 or cp[hi] is None: continue
                a_end, b_start = truth[ri][1], truth[rj][0]; gap = b_start - a_end; tc = cp[hi]['t']
                inside_word = (truth[ri][0] + 0.010 < tc < a_end - 0.010) or (b_start + 0.010 < tc < truth[rj][1] - 0.010)
                c = cuts.setdefault((cname, meth), {'pause_n': 0, 'pause_ok': 0, 'touch_n': 0, 'touch_ok': 0, 'touch_dmg': 0, 'pause_dmg': 0, 'safe_flag_on_pause': 0, 'safe_flag_on_touch': 0})
                if gap >= 0.035:
                    c['pause_n'] += 1; c['pause_ok'] += int(a_end - 0.005 <= tc <= b_start + 0.005); c['pause_dmg'] += int(inside_word); c['safe_flag_on_pause'] += int(cp[hi]['safe'])
                else:
                    c['touch_n'] += 1; c['touch_ok'] += int(abs(tc - a_end) <= 0.020); c['touch_dmg'] += int(inside_word); c['safe_flag_on_touch'] += int(cp[hi]['safe'])
    print(f'  {cname} done', flush=True)
st = lambda v: (np.median(np.abs(v)), np.percentile(np.abs(v), 90), np.percentile(np.abs(v), 95), np.mean(np.abs(v) <= 20) * 100, np.mean(np.abs(v) <= 40) * 100, np.mean(np.abs(v) <= 100) * 100, np.median(v))
print('\nWord boundary error vs truth (ms). median|err|, p90, p95, %within 20 ms, %within 40 ms, %within 100 ms, signed median (+ = late)')
for (cname, meth), d in results.items():
    for which in ('start', 'end'):
        m = st(np.array(d[which])); print(f'{cname:13s} {meth:11s} {which:5s} n={len(d[which]):3d}  med {m[0]:6.0f}  p90 {m[1]:6.0f}  p95 {m[2]:6.0f}   <=20: {m[3]:3.0f}%  <=40: {m[4]:3.0f}%  <=100: {m[5]:3.0f}%   signed {m[6]:+6.0f}')
print('\nCut points: pauses (true gap >= 35 ms): cut inside the true pause / cuts landing inside a word / flagged safe;  touching words: cut within 20 ms of the seam / inside a word / flagged safe')
for (cname, meth), c in cuts.items():
    print(f"{cname:13s} {meth:11s} pauses {c['pause_n']:3d}: in pause {100 * c['pause_ok'] / max(c['pause_n'], 1):3.0f}%  inside word {100 * c['pause_dmg'] / max(c['pause_n'], 1):3.0f}%  flagged safe {100 * c['safe_flag_on_pause'] / max(c['pause_n'], 1):3.0f}%  |  touching {c['touch_n']:3d}: near seam {100 * c['touch_ok'] / max(c['touch_n'], 1):3.0f}%  inside word {100 * c['touch_dmg'] / max(c['touch_n'], 1):3.0f}%  flagged safe {100 * c['safe_flag_on_touch'] / max(c['touch_n'], 1):3.0f}%")
