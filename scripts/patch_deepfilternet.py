"""Patch deepfilternet 0.5.6 for torchaudio >= 2.1, which removed torchaudio.backend.common.AudioMetaData (idempotent).
Usage: python scripts/patch_deepfilternet.py [path/to/venv/python]"""
import subprocess, sys
py = sys.argv[1] if len(sys.argv) > 1 else sys.executable
path = subprocess.check_output([py, '-c', 'import importlib.util as u; print(u.find_spec("df").submodule_search_locations[0])'], text=True).strip() + '/io.py'
s = open(path).read()
old = 'from torchaudio.backend.common import AudioMetaData'
if old not in s: print('already patched or different version:', path); sys.exit(0)
s = s.replace(old, '''try:
    from torchaudio.backend.common import AudioMetaData
except Exception:  # torchaudio >= 2.1 removed this; stand-in type (local patch by strata360: df's own file loaders are not used)
    from dataclasses import dataclass
    @dataclass
    class AudioMetaData:
        sample_rate: int = 0
        num_frames: int = 0
        num_channels: int = 0
        bits_per_sample: int = 0
        encoding: str = \'\'''')
open(path, 'w').write(s); print('patched', path)
