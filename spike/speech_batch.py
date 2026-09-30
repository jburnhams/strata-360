"""Run multilingual transcription + translation over every OSV in a folder, model loaded once (project venv).
  .venv/bin/python spike/speech_batch.py LIBRARY_DIR OUT_DIR [--model large-v3-turbo] [--languages en,fr,nl,de]
Writes OUT_DIR/<clip>.transcript.json (README 5.11) and prints a summary. Outputs contain other people's speech: keep them out of git."""
import glob, json, os, sys, time, warnings
warnings.filterwarnings('ignore')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import audio as A, speech as S

lib, out = sys.argv[1], sys.argv[2]
model_name = sys.argv[sys.argv.index('--model') + 1] if '--model' in sys.argv else 'large-v3-turbo'
langs = sys.argv[sys.argv.index('--languages') + 1].split(',') if '--languages' in sys.argv else S.ALLOWED
os.makedirs(out, exist_ok=True)
m, tm = S.load_models(model_name)
tot = {}; n_clips = 0
for f in sorted(glob.glob(os.path.join(lib, '*.OSV'))):
    name = os.path.basename(f)[:-4]; jp = os.path.join(out, name + '.transcript.json')
    if os.path.exists(jp): d = json.load(open(jp))
    else:
        t0 = time.time(); x = A.load_audio(f, 1)[:, 0]; x16 = A.ffmpeg_filter(x, A.SR, 'anull', out_sr=16000)[:, 0]
        segs = S.transcribe_multilingual(x16, m, tm, langs)
        d = dict(source=name + '.OSV', model=model_name, translate_model='opus-mt', denoise='none', languages=langs, seconds=round(time.time() - t0, 1), segments=segs)
        json.dump(d, open(jp, 'w'), ensure_ascii=False, indent=1)
    good = [s for s in d['segments'] if not s['suspect']]
    lc = {}
    for s in good: lc[s['lang']] = lc.get(s['lang'], 0) + len(s['words'])
    for k, v in lc.items(): tot[k] = tot.get(k, 0) + v
    n_clips += 1
    print(f"{name[4:18]} {len(d['segments']):3d} segments ({len(d['segments']) - len(good)} suspect)  words by language {lc}  [{d['seconds']} s]", flush=True)
print('total words by language (suspect segments excluded):', tot)
