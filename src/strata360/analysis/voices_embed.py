"""Speaker embeddings for the speech segments of one clip (SpeechBrain ECAPA-TDNN, local), run inside `.venv-vision`.

  python -m strata360.analysis.voices_embed OSV SEGMENTS_JSON OUT_NPY OUT_JSON [--model models/ecapa]

SEGMENTS_JSON is a list of {"t0", "t1"} (clip-relative seconds). Writes one 192-d embedding per segment (OUT_NPY, float16) and per-segment level statistics (OUT_JSON): RMS dBFS,
peak dBFS and the 5th-95th percentile spread of 50 ms frame levels (a close talker has a steady high level; a distant crowd is quieter and flatter)."""
import argparse, json, os, subprocess
import numpy as np

SR = 16000


def load_audio(osv):
    raw = subprocess.run(['ffmpeg', '-v', 'error', '-i', osv, '-map', '0:a:0', '-ac', '1', '-ar', str(SR), '-f', 'f32le', '-'], stdout=subprocess.PIPE, check=True).stdout
    return np.frombuffer(raw, np.float32)


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('osv'); ap.add_argument('segments'); ap.add_argument('out_npy'); ap.add_argument('out_json')
    ap.add_argument('--model', default=os.path.join(os.path.dirname(__file__), '..', '..', '..', 'models', 'ecapa')); a = ap.parse_args()
    import torch
    from speechbrain.inference.speaker import EncoderClassifier
    segs = json.load(open(a.segments)); y = load_audio(a.osv); embs = []; stats = []
    if segs:
        m = os.path.abspath(a.model); clf = EncoderClassifier.from_hparams(source=m, savedir=m, run_opts={'device': 'cpu'})
    for s in segs:
        x = y[int(max(s['t0'], 0) * SR):int(s['t1'] * SR)]
        if len(x) < SR * 0.5: x = np.pad(x, (0, int(SR * 0.5) - len(x)))
        with torch.no_grad(): e = clf.encode_batch(torch.from_numpy(x)[None]).squeeze().numpy()
        embs.append(e.astype(np.float16)); n = SR // 20; fr = x[:len(x) // n * n].reshape(-1, n); lv = 20 * np.log10(np.sqrt((fr ** 2).mean(1)) + 1e-9) if len(fr) else np.array([-90.0])
        stats.append(dict(rms_db=round(float(20 * np.log10(np.sqrt((x ** 2).mean()) + 1e-9)), 1), peak_db=round(float(20 * np.log10(np.abs(x).max() + 1e-9)), 1), spread_db=round(float(np.percentile(lv, 95) - np.percentile(lv, 5)), 1)))
    np.save(a.out_npy, np.array(embs, np.float16).reshape(-1, 192)); json.dump(stats, open(a.out_json, 'w')); print(len(segs), 'segments')


if __name__ == '__main__':
    main()
