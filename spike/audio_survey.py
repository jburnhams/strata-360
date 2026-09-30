"""Survey the audio of every clip in a library: analysis labels + a speech-recogniser pass (voice-activity filtered).
Writes one JSON per clip to the output dir (cached) and prints a table. Run with the project venv:
  .venv/bin/python spike/audio_survey.py "/Volumes/Expansion/2026-02-19 - Legends" OUTDIR [--model small]"""
import glob, json, os, sys, time, warnings
warnings.filterwarnings('ignore')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import audio as A
from faster_whisper import WhisperModel

lib, out = sys.argv[1], sys.argv[2]; model_name = sys.argv[sys.argv.index('--model') + 1] if '--model' in sys.argv else 'small'
os.makedirs(out, exist_ok=True)
model = WhisperModel(model_name, device='cpu', compute_type='int8')
rows = []
for f in sorted(glob.glob(os.path.join(lib, '*.OSV'))):
    name = os.path.basename(f)[:-4]; jp = os.path.join(out, name + '.json')
    if os.path.exists(jp): d = json.load(open(jp))
    else:
        t0 = time.time(); x = A.load_audio(f)
        an = A.analyse_array(x)
        x16 = A.ffmpeg_filter(x.mean(1), A.SR, 'anull', out_sr=16000)[:, 0]
        segs, info = model.transcribe(x16, vad_filter=True, word_timestamps=True, beam_size=5, condition_on_previous_text=False)
        tr = [dict(t0=round(s.start, 2), t1=round(s.end, 2), text=s.text.strip(), avg_logprob=round(s.avg_logprob, 2), no_speech=round(s.no_speech_prob, 2),
                   words=[dict(w=w.word.strip(), t0=round(w.start, 2), p=round(float(w.probability), 2)) for w in (s.words or [])]) for s in segs]
        d = dict(file=name, duration_s=an['summary']['duration_s'], summary=an['summary'], segments=an['segments'], language=info.language, language_prob=round(info.language_probability, 2),
                 transcript=tr, seconds=round(time.time() - t0, 1))
        json.dump(d, open(jp, 'w'), indent=1)
    lab = {}
    for s in d['segments']: lab[s['label']] = lab.get(s['label'], 0) + s['t1_s'] - s['t0_s']
    words = sum(len(t['words']) for t in d['transcript'])
    rows.append((d['file'], d['duration_s'], d['summary']['integrated_lufs'], d['summary']['sample_peak_dbfs'], d['summary']['clipped_samples'], lab, d['language'], words))
    print(f"{d['file'][4:18]} {d['duration_s']:6.1f}s {d['summary']['integrated_lufs']:6.1f} LUFS peak {d['summary']['sample_peak_dbfs']:6.1f} clip {d['summary']['clipped_samples']:4d}  "
          + ' '.join(f"{k}:{v:.0f}s" for k, v in sorted(lab.items())) + f"  | asr {d['language']} {words} words", flush=True)
print('total audio %.1f min' % (sum(r[1] for r in rows) / 60))
