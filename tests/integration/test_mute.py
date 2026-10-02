"""The mute filter really silences the marked seconds of a sound and leaves the rest alone (ffmpeg)."""
import subprocess
import numpy as np
from strata360.render import preview as PV


def test_the_marked_seconds_are_silent_and_the_rest_is_untouched():
    chain = 'volume=1.0' + PV.mute_filter([(1.0, 1.5)]) + ',aresample=8000'
    raw = subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-t', '2', '-i', 'sine=frequency=440:sample_rate=8000', '-af', chain, '-f', 's16le', '-ac', '1', '-'], capture_output=True, check=True).stdout
    x = np.frombuffer(raw, np.int16).astype(float) / 32768; rms = lambda a, b: float(np.sqrt(np.mean(x[int(a * 8000):int(b * 8000)] ** 2)))
    assert rms(1.05, 1.45) < 1e-4 and rms(0.2, 0.9) > 0.05 and rms(1.6, 1.9) > 0.05
