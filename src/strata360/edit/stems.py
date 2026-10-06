"""Stems of the uploaded music track (Milestone G0b, docs/ai-music.md 4.6): drums, bass, other and vocals, separated once and kept next to music.json under music/stems/, keyed by the track's signature so a replaced track separates again.

  stems_for(rd, rel, separator=None, write=None, read=None) -> (dict name -> float32 array (samples, 2), sr)
  separator(path) -> (dict name -> array, sr) is demucs by default (`demucs_separator`, htdemucs_ft on the GPU when there is one, samples decoded by ffmpeg so torchaudio's removed file loading is never used); a test passes a fake.
  write(path, array, sr) / read(path) -> (array, sr) are ffmpeg (FLAC) by default."""
import json, os, subprocess
import numpy as np

NAMES = ('drums', 'bass', 'other', 'vocals'); MODEL = 'htdemucs_ft'; VERSION = 1


def _sig(path): st = os.stat(path); return [st.st_size, st.st_mtime_ns]


def decode_stereo(path, sr):
    r = subprocess.run(['ffmpeg', '-v', 'error', '-i', path, '-vn', '-ac', '2', '-ar', str(sr), '-f', 'f32le', '-'], capture_output=True)
    if r.returncode or not r.stdout: raise RuntimeError('could not read the audio: ' + r.stderr.decode(errors='ignore')[-200:])
    return np.frombuffer(r.stdout, np.float32).reshape(-1, 2)


def ffmpeg_write(path, x, sr):
    r = subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'f32le', '-ar', str(sr), '-ac', '2', '-i', '-', path], input=np.ascontiguousarray(x, np.float32).tobytes(), capture_output=True)
    if r.returncode: raise RuntimeError('could not write ' + path + ': ' + r.stderr.decode(errors='ignore')[-200:])


def ffmpeg_read(path, sr=44100): return decode_stereo(path, sr), sr


def demucs_separator(path):
    """Separate with demucs's model API on samples ffmpeg decoded (pin demucs in the music environment). Needs torch and demucs; GPU when hw.gpu_device() says so."""
    import torch
    from demucs.pretrained import get_model
    from demucs.apply import apply_model
    from strata360 import hw
    m = get_model(MODEL); dev = hw.gpu_device() or 'cpu'; x = torch.from_numpy(decode_stereo(path, m.samplerate).T.copy())[None]
    with torch.no_grad(): y = apply_model(m, x, device=dev, split=True, overlap=0.25)[0].cpu().numpy()
    return {n: y[i].T.astype(np.float32) for i, n in enumerate(m.sources)}, m.samplerate


def stems_for(rd, rel, separator=None, write=None, read=None):
    """The stems of the track `rel` in race dir `rd`: read from music/stems/ when stems.json there is for this file's signature, else separated and saved."""
    p = os.path.join(rd, rel); d = os.path.join(rd, 'music', 'stems'); meta = os.path.join(d, 'stems.json'); write = write or ffmpeg_write; read = read or ffmpeg_read; sig = _sig(p)
    try:
        m = json.load(open(meta))
        if m.get('version') == VERSION and m.get('sig') == sig and m.get('file') == rel and all(os.path.exists(os.path.join(d, n + '.flac')) for n in NAMES):
            out = {}
            for n in NAMES: out[n], sr = read(os.path.join(d, n + '.flac'))
            return out, m['sr']
    except (OSError, ValueError, KeyError): pass
    stems, sr = (separator or demucs_separator)(p); missing = [n for n in NAMES if n not in stems]
    if missing: raise RuntimeError('the separator did not return ' + ', '.join(missing))
    os.makedirs(d, exist_ok=True)
    for n in NAMES: write(os.path.join(d, n + '.flac'), stems[n], sr)
    json.dump(dict(version=VERSION, file=rel, sig=sig, sr=sr, model=MODEL), open(meta, 'w'), indent=1)
    return {n: np.asarray(stems[n], np.float32) for n in NAMES}, sr
