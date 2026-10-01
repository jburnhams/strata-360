"""The sound without the speech: the clip's background as its own track (for the sound classifier and for the final mix).

TIGER-DnR (Xu, Li, Chen, Hu, Tsinghua; ICLR 2025; model weights Apache-2.0, code MIT) splits a mixture into dialogue, effects and music (trained on the Divide-and-Remaster set). We use its EFFECTS model:
everything that is not clear speech and not music, so wind, footsteps, nature and the murmur of a crowd stay and the person talking goes. (On a 5 s piece of a clip with a voice the sound classifier's speech score
fell from 0.52 to nothing, and what it still heard was the place: animals, a bicycle, hooves.)

The model code is not part of this repository: `ensure()` fetches it, at a pinned commit, into models/tiger-dnr/ (like the weights, which come from Hugging Face `JusperLee/TIGER-DnR`, 17 MB).
Speed: 4 M parameters but heavy attention over 12 s windows: on the CPU about 6 s per second of audio, on the Apple GPU about 1 s per second (set STRATA_GPU=1: the pipeline keeps the GPU free by default).
Windows of 12 s overlap by half, added together."""
import os, subprocess, sys, types
import numpy as np

REPO = 'https://github.com/JusperLee/TIGER.git'
PIN = '9f18d4a10a7137e1ce8052cfb62215179f1287b6'
WEIGHTS = 'JusperLee/TIGER-DnR'
SR_MODEL = 44100
WINDOW_S = 12.0; HOP_S = 6.0
_M = {}


def model_dir(): return os.environ.get('STRATA360_TIGER') or os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..', 'models', 'tiger-dnr')


def ensure(log=print):
    """Fetch the model code (pinned commit) and the weights when they are not there yet."""
    src = os.path.join(model_dir(), 'src')
    if not os.path.exists(os.path.join(src, 'look2hear', 'models', 'tiger_dnr.py')):
        log('fetching the TIGER-DnR model code (pinned commit) ...'); os.makedirs(src, exist_ok=True)
        for cmd in (['init', '-q'], ['fetch', '-q', '--depth', '1', REPO, PIN], ['checkout', '-q', 'FETCH_HEAD']): subprocess.run(['git', '-C', src] + cmd, check=True)
    return src


def _device():
    import torch
    if os.environ.get('STRATA_GPU') == '1':
        if torch.cuda.is_available(): return 'cuda'
        if torch.backends.mps.is_available(): return 'mps'
    return 'cpu'


def load(log=print):
    if 'model' in _M: return _M['model'], _M['dev']
    import torch
    src = ensure(log); dev = _device(); sys.path.insert(0, src)
    from packaging.version import Version
    if 'distutils' not in sys.modules:                                      # the model code imports LooseVersion from distutils, which Python 3.12 removed
        try: import distutils.version  # noqa
        except ImportError:
            d = types.ModuleType('distutils'); dv = types.ModuleType('distutils.version'); dv.LooseVersion = lambda v: v; d.version = dv; sys.modules['distutils'] = d; sys.modules['distutils.version'] = dv
    pk = types.ModuleType('look2hear.utils'); pk.__path__ = [os.path.join(src, 'look2hear', 'utils')]; sys.modules['look2hear.utils'] = pk      # not its __init__: it pulls in the training stack
    import look2hear.models as m
    if dev == 'mps':                                                        # the one operation the Apple GPU cannot do when the sizes do not divide: on the CPU
        F = torch.nn.functional; _ap = F.adaptive_avg_pool1d
        F.adaptive_avg_pool1d = lambda x, output_size: _ap(x.cpu(), output_size).to(x.device) if x.device.type == 'mps' and x.shape[-1] % output_size else _ap(x, output_size)
    model = m.TIGERDNR.from_pretrained(WEIGHTS, cache_dir=os.path.join(model_dir(), 'weights')).eval().to(dev)
    _M['model'], _M['dev'] = model, dev; log(f'TIGER-DnR loaded on {dev}'); return model, dev


def separate(x48, log=print, progress=None):
    """x48: mono float32 at 48 kHz -> the effects stem (everything but speech and music) as mono float32 at 48 kHz, the same length."""
    import torch
    from strata360.audio import dsp
    model, dev = load(log); x = dsp.ffmpeg_filter(np.asarray(x48, np.float32), dsp.SR, 'anull', out_sr=SR_MODEL)[:, 0]
    with torch.no_grad(): y = model.wav_chunk_inference(model.effect, torch.from_numpy(x)[None, None].to(dev), target_length=WINDOW_S, hop_length=HOP_S)[1]
    y = y.reshape(-1).cpu().numpy()[:len(x)]
    out = dsp.ffmpeg_filter(y.astype(np.float32), SR_MODEL, 'anull', out_sr=dsp.SR)[:, 0]
    return out[:len(x48)] if len(out) >= len(x48) else np.pad(out, (0, len(x48) - len(out)))
