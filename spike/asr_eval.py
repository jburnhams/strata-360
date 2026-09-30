"""Word-error-rate evaluation of the speech chain variants (run with the project venv).
Known sentences (macOS `say`) buried in REAL noise excerpts from the survey library at several speech-band SNRs, transcribed with
faster-whisper. Usage: .venv/bin/python spike/asr_eval.py SURVEY_DIR LIBRARY_DIR OUT.json [--quick]"""
import glob, json, os, sys, time, warnings, subprocess
warnings.filterwarnings('ignore')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import audio as A
import test_audio as T
from faster_whisper import WhisperModel

survey, lib, outp = sys.argv[1], sys.argv[2], sys.argv[3]; quick = '--quick' in sys.argv
MODEL = sys.argv[sys.argv.index('--model') + 1] if '--model' in sys.argv else 'small'
ONLY = sys.argv[sys.argv.index('--variants') + 1].split(',') if '--variants' in sys.argv else None
SR = A.SR
# ---- pick real noise excerpts by label from the survey (8 s, clips of at least that long, no speech words in the range)
def excerpt(label, want=8.0, exclude_speech=True):
    best = None
    for jp in sorted(glob.glob(f'{survey}/*.json')):
        d = json.load(open(jp))
        words = [w['t0'] for t in d['transcript'] for w in t['words']]
        for s in d['segments']:
            if s['label'] == label and s['t1_s'] - s['t0_s'] >= want:
                a, b = s['t0_s'], s['t0_s'] + want
                if exclude_speech and any(a - 1 <= w <= b + 1 for w in words): continue
                score = s['t1_s'] - s['t0_s']
                if best is None or score > best[0]: best = (score, d['file'], a, b)
    return best
noises = {}
for label in ('wind', 'crowd', 'ambience'):
    e = excerpt(label)
    if e:
        x = A.load_audio(f'{lib}/{e[1]}.OSV', 1)[:, 0]; noises[label] = (x[int(e[2] * SR):int((e[2] + 8) * SR)], e[1], e[2])
print('noise excerpts:', {k: (v[1], round(v[2], 1)) for k, v in noises.items()}, flush=True)
sent = T.SENT[:3] if quick else T.SENT[:5]; voices = ['Daniel', 'Samantha', 'Karen', 'Fred', 'Moira']
snrs = [0, 8] if quick else [-3, 3, 9]
bp = lambda x: A.ffmpeg_filter(x, SR, 'highpass=f=300,lowpass=f=3400')[:, 0]
model = WhisperModel(MODEL, device='cpu', compute_type='int8'); print('whisper model:', MODEL, flush=True)
def transcribe(x16):
    segs, _ = model.transcribe(x16.astype(np.float32), language='en', beam_size=5, condition_on_previous_text=False, vad_filter=False)
    return ' '.join(s.text for s in segs)
VARIANTS = {
    'raw': None,
    'classical (hp+afftdn+eq+norm)': dict(denoise='afftdn'),
    'norm only (hp+eq+norm)': dict(denoise='none'),
    'DeepFilterNet3 + eq+norm': dict(denoise='dfn'),
    'DeepFilterNet3 (atten 20 dB) + eq+norm': dict(denoise='dfn', atten_lim_db=20),
    'MossFormer2 48k + eq+norm': dict(denoise='mossformer'),
}
if ONLY: VARIANTS = {k: v for k, v in VARIANTS.items() if any(k.startswith(o) for o in ONLY)}
rows = []; t0 = time.time()
for nlab, (noise, nf, ns) in noises.items():
    nb = np.sqrt(np.mean(bp(noise) ** 2))
    for si, text in enumerate(sent):
        sp = T.scale_to_rms_db(T.tts(text, voices[si % len(voices)]), -20)
        sp = np.pad(sp, (int(1.0 * SR), max(len(noise) - len(sp) - int(1.0 * SR), 0)))[:len(noise)]
        spb = np.sqrt(np.mean(bp(sp) ** 2))
        for snr in snrs:
            mix = (noise + sp * (nb / spb) * 10 ** (snr / 20)).astype(np.float32) * 0.5
            for vn, kw in VARIANTS.items():
                if kw is None: y = A.ffmpeg_filter(mix, SR, 'anull', out_sr=16000)[:, 0]
                else: y = A.enhance_speech(mix, SR, 'asr', **kw)
                hyp = transcribe(y); rows.append(dict(noise=nlab, sent=si, snr=snr, variant=vn, wer=A.wer(text, hyp), hyp=hyp))
        print(f'  {nlab} sentence {si + 1}/{len(sent)} done ({time.time() - t0:.0f} s)', flush=True)
json.dump(rows, open(outp, 'w'), indent=1)
print('\nmean WER (lower is better) by variant and input speech-band SNR:')
print(f'{"variant":42s}' + ''.join(f'{s:>+8d} dB' for s in snrs) + '     all')
for vn in VARIANTS:
    r = [x for x in rows if x['variant'] == vn]
    print(f'{vn:42s}' + ''.join(f"{np.mean([x['wer'] for x in r if x['snr'] == s]):11.2f}" for s in snrs) + f"{np.mean([x['wer'] for x in r]):9.2f}")
print('\nmean WER by noise type (all SNRs):')
for nlab in noises:
    print(f'{nlab:10s}' + ''.join(f"  {vn.split(' ')[0][:12]}:{np.mean([x['wer'] for x in rows if x['variant'] == vn and x['noise'] == nlab]):.2f}" for vn in VARIANTS))
