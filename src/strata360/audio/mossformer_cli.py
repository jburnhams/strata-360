"""Run MossFormer2_SE_48K (ClearerVoice-Studio) on a WAV file. Lives in its own venv (.venv-cv) because clearvoice pins numpy<2 and
an old opencv. Usage: .venv-cv/bin/python spike/mossformer_cli.py in.wav out.wav"""
import sys, warnings
warnings.filterwarnings('ignore')
from clearvoice import ClearVoice
cv = ClearVoice(task='speech_enhancement', model_names=['MossFormer2_SE_48K'])
out = cv(input_path=sys.argv[1], online_write=False)
cv.write(out, output_path=sys.argv[2])
