"""Experiment, step 1 (run in .venv-cv): enhance the speech of some clips with ClearerVoice models, on the GPU, for comparison with the project's own audio_clean.flac (DeepFilterNet3 capped, dsp.clean_for_playback).

  .venv-cv/Scripts/python scripts/win_exp/enhance_run.py PROJECT_FOLDER OUT_DIR CLIP_PATTERN [CLIP_PATTERN ...]

Writes OUT_DIR/<clip>/original.wav (mono, 48 kHz, the recogniser's input) and <model>.wav for each model, with the seconds each took. Step 2 (scripts/win_exp/enhance_eval.py) scores them."""
import json, os, subprocess, sys, time, warnings
warnings.filterwarnings('ignore')
import numpy as np
import soundfile as sf
from clearvoice import ClearVoice

MODELS = ['MossFormer2_SE_48K', 'MossFormerGAN_SE_16K', 'FRCRN_SE_16K']


def main():
    folder, out = sys.argv[1], sys.argv[2]; times = {}
    cvs = {m: ClearVoice(task='speech_enhancement', model_names=[m]) for m in MODELS}
    for pat in sys.argv[3:]:
        import glob
        for cdir in sorted(glob.glob(os.path.join(folder, 'strata360', 'clips', pat))):
            clip = os.path.basename(cdir); d = os.path.join(out, clip); os.makedirs(d, exist_ok=True); wav = os.path.join(d, 'original.wav')
            subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', os.path.join(cdir, 'audio_original.flac'), '-ac', '1', '-ar', '48000', wav], check=True)
            for m, cv in cvs.items():
                t = time.time(); y = cv(input_path=wav, online_write=False); cv.write(y, output_path=os.path.join(d, m + '.wav')); times[f'{clip}/{m}'] = round(time.time() - t, 1); print(clip, m, times[f'{clip}/{m}'], 's', flush=True)
    json.dump(times, open(os.path.join(out, 'times.json'), 'w'), indent=1)


if __name__ == '__main__': main()
