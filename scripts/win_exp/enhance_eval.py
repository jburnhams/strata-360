"""Experiment, step 2 (main venv): score the speech tracks made by enhance_run.py against the project's own audio_clean.flac and the original.

  python scripts/win_exp/enhance_eval.py PROJECT_FOLDER ENH_DIR OUT.json

For every English segment of the transcripts (+-0.25 s) of the clips in ENH_DIR, each system's audio is scored with
  DNSMOS P.835 (no reference: SIG speech quality, BAK background, OVRL overall; Microsoft's non-intrusive model through torchmetrics),
  Whisper large-v3-turbo (the pipeline's recogniser) on that audio: mean word probability and the words per second it finds, and the word error against the Gemini-corrected transcript where there is one."""
import glob, json, os, re, subprocess, sys
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))
from strata360 import hw

SYSTEMS = ['original', 'current', 'MossFormer2_SE_48K', 'MossFormerGAN_SE_16K', 'FRCRN_SE_16K']


def load(path, sr=16000):
    return np.frombuffer(subprocess.run(['ffmpeg', '-v', 'error', '-i', path, '-ac', '1', '-ar', str(sr), '-f', 'f32le', '-'], capture_output=True).stdout, np.float32).copy()


def norm(t): return re.sub(r"[^a-z0-9' ]+", ' ', (t or '').lower()).split()


def main():
    folder, enh, out = sys.argv[1:4]; hw._cuda_dll_dirs()
    import torch, jiwer
    from torchmetrics.functional.audio.dnsmos import deep_noise_suppression_mean_opinion_score as dnsmos
    from faster_whisper import WhisperModel
    d, c = hw.whisper_args(); wm = WhisperModel('large-v3-turbo', device=d, compute_type=c); acc = {s: dict(sig=[], bak=[], ovr=[], prob=[], wps=[], err=0, ref=0) for s in SYSTEMS}
    for cdir in sorted(glob.glob(os.path.join(enh, 'CAM_*'))):
        clip = os.path.basename(cdir); cj = os.path.join(folder, 'strata360', 'clips', clip); tj = json.load(open(os.path.join(cj, 'transcript.json')))
        ep = os.path.join(cj, 'transcript_edits.json'); edits = json.load(open(ep)).get('edits', {}) if os.path.exists(ep) else {}
        wav = {'original': load(os.path.join(cdir, 'original.wav')), 'current': load(os.path.join(cj, 'audio_clean.flac'))}
        for s in SYSTEMS[2:]: wav[s] = load(os.path.join(cdir, s + '.wav'))
        for i, seg in enumerate(tj['segments']):
            if seg['lang'] != 'en' or seg['t1'] - seg['t0'] < 1.0: continue
            ref = ' '.join(((edits.get(f'{i}:{j}') or {}).get('gemini') or {}).get('text', w['w']) if (edits.get(f'{i}:{j}') or {}).get('gemini') else w['w'] for j, w in enumerate(seg['words'])) if seg.get('words') else None
            has_edit = any(k.startswith(f'{i}:') and v.get('gemini') for k, v in edits.items())
            for s in SYSTEMS:
                x = wav[s][max(int((seg['t0'] - 0.25) * 16000), 0):int((seg['t1'] + 0.25) * 16000)]
                if len(x) < 16000: continue
                m = dnsmos(torch.from_numpy(x), 16000, False).numpy(); acc[s]['sig'].append(float(m[1])); acc[s]['bak'].append(float(m[2])); acc[s]['ovr'].append(float(m[3]))
                segs, _ = wm.transcribe(x, language='en', word_timestamps=True, beam_size=5, condition_on_previous_text=False, vad_filter=False); words = [w for sg in segs for w in sg.words]
                if words: acc[s]['prob'].append(float(np.mean([w.probability for w in words]))); acc[s]['wps'].append(len(words) / (len(x) / 16000))
                else: acc[s]['prob'].append(0.0); acc[s]['wps'].append(0.0)
                if has_edit and ref:
                    o = jiwer.process_words(' '.join(norm(ref)), ' '.join(norm(' '.join(w.word for w in words))) or '<e>'); acc[s]['err'] += o.substitutions + o.deletions + o.insertions; acc[s]['ref'] += len(norm(ref))
        print(clip, flush=True)
    res = {s: dict(segments=len(a['ovr']), dnsmos_sig=round(float(np.mean(a['sig'])), 3), dnsmos_bak=round(float(np.mean(a['bak'])), 3), dnsmos_ovrl=round(float(np.mean(a['ovr'])), 3), whisper_word_prob=round(float(np.mean(a['prob'])), 3),
                    whisper_words_per_s=round(float(np.mean(a['wps'])), 3), wer_vs_gemini_on_edited_segments=round(a['err'] / max(a['ref'], 1), 3), ref_words=a['ref']) for s, a in acc.items()}
    json.dump(res, open(out, 'w'), indent=1); print(json.dumps(res, indent=1))


if __name__ == '__main__': main()
