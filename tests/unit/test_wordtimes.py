import pytest
import numpy as np
from strata360.audio import wordtimes

def test_norm_word():
    vocab = {'A': 1, 'B': 2, 'C': 3}
    assert wordtimes._norm_word('abc', vocab) == 'ABC'
    assert wordtimes._norm_word('a b c d', vocab) == 'ABC' # ignores D, spaces

    # special tokens are ignored
    vocab_special = {'A': 1, 'B': 2, '|': 3, '<pad>': 4}
    assert wordtimes._norm_word('A|B<pXd>', vocab_special) == 'AB'


def test_energy_envelope():
    # Generate a dummy signal
    sr = 16000
    t = np.linspace(0, 1.0, sr) # 1 second

    # Sine wave within band (1000 Hz)
    x = 0.1 * np.sin(2 * np.pi * 1000 * t)

    times, e_db = wordtimes.energy_envelope(x, sr, hop_s=0.01)

    # 1 second with 0.01s hops = 100 hops
    assert len(times) == 100
    assert len(e_db) == 100
    assert times[0] == 0.005 # centered hop

    # Check that energy is relatively consistent for a constant sine wave
    assert np.all(e_db > -40) # Should not be completely silent
    assert np.std(e_db) < 5 # Should be stable

    # Test silence
    x_silent = np.zeros_like(x)
    _, e_silent = wordtimes.energy_envelope(x_silent, sr, hop_s=0.01)
    # Energy should be at the lower limit (very small e -> highly negative dB)
    assert np.all(e_silent < -100)

def test_refine_with_energy(monkeypatch):
    import numpy as np
    # Mock energy envelope to return a single peak of energy at time 0.5
    times = np.linspace(0, 1.0, 100) # 0.01s steps
    energy = np.full(100, -50.0) # silence
    # Add a burst of energy from 0.4s to 0.6s
    energy[40:60] = 0.0

    monkeypatch.setattr(wordtimes, 'energy_envelope', lambda x, sr, **kw: (times, energy))

    # Word starts too early (0.1) and ends too late (0.9), peak is at 0.4-0.6
    # It should snap to the active energy bounds ~0.4 and ~0.6
    words = [(0.1, 0.9, 1.0)]
    refined = wordtimes.refine_with_energy(words, None, 16000)

    assert len(refined) == 1
    w = refined[0]
    assert abs(w[0] - 0.39) < 0.02 # max(t[active[0]] - 0.0025, a - max_shift_s) -> max(0.4-0.0025, 0.1) -> 0.3975
    assert abs(w[1] - 0.59) < 0.02 # min(t[active[-1]] + 0.0025, b + max_shift_s) -> min(0.59+0.0025, 0.9) -> 0.5925
    assert w[2] == 1.0

    # Word with None
    words = [None, (0.45, 0.55, 1.0)]
    refined = wordtimes.refine_with_energy(words, None, 16000)
    assert len(refined) == 2
    assert refined[0] is None
    # 0.45-0.55 is fully within the peak, should remain unchanged (within margins)
    assert abs(refined[1][0] - 0.40) < 0.02
    assert abs(refined[1][1] - 0.59) < 0.02

def test_vad_probabilities(monkeypatch):
    import types
    import numpy as np

    class FakeVadModel:
        def __call__(self, x):
            # Return an array of probs, say one prob per 512 samples
            # x is length n. return a tensor-like array
            n_frames = len(x) // 512
            return np.ones((n_frames, 1)) * 0.8

    fake_fw = types.ModuleType('faster_whisper')
    fake_vad = types.ModuleType('vad')
    fake_vad.get_vad_model = lambda: FakeVadModel()
    fake_fw.vad = fake_vad

    import sys
    monkeypatch.setitem(sys.modules, 'faster_whisper.vad', fake_vad)
    monkeypatch.setitem(sys.modules, 'faster_whisper', fake_fw)

    # 1 second of audio at 16kHz
    x = np.zeros(16000, dtype=np.float32)
    t, p = wordtimes.vad_probabilities(x)

    # 16000 / 512 = 31.25 -> 32 frames (due to padding)
    assert len(t) == 32
    assert len(p) == 32
    assert t[0] == 0.5 * 512 / 16000
    assert p[0] == 0.8

def test_refine_with_energy_order(monkeypatch):
    import numpy as np
    times = np.linspace(0, 1.0, 100) # 0.01s steps
    energy = np.full(100, 0.0)

    monkeypatch.setattr(wordtimes, 'energy_envelope', lambda x, sr, **kw: (times, energy))

    # words that overlap
    words = [(0.1, 0.5, 1.0), (0.4, 0.8, 1.0)]
    refined = wordtimes.refine_with_energy(words, None, 16000)

    # 0.4 and 0.5 overlap. Midpoint is 0.45.
    assert abs(refined[0][1] - 0.45) < 0.001
    assert abs(refined[1][0] - 0.45) < 0.001

def test_refine_with_energy_empty(monkeypatch):
    import numpy as np
    times = np.linspace(0, 1.0, 100)
    energy = np.full(100, -100.0) # all silence below threshold
    monkeypatch.setattr(wordtimes, 'energy_envelope', lambda x, sr, **kw: (times, energy))

    # word with no energy peak
    words = [(0.1, 0.5, 1.0)]
    refined = wordtimes.refine_with_energy(words, None, 16000)

    assert len(refined) == 1
    # Returns original
    assert refined[0][0] <= words[0][0]
    assert refined[0][1] >= words[0][1]

def test_cut_points(monkeypatch):
    import numpy as np

    times = np.linspace(0, 1.0, 100)
    energy = np.full(100, -50.0)
    # fake audio trace to have some zero crossings
    x = np.sin(2 * np.pi * 100 * np.linspace(0, 1.0, 16000))
    sr = 16000

    monkeypatch.setattr(wordtimes, 'energy_envelope', lambda x, sr, **kw: (times, energy))

    # Gap between 0.3 and 0.5
    words = [(0.1, 0.3, 1.0), (0.5, 0.7, 1.0)]

    # With no VAD
    cuts = wordtimes.cut_points(words, x, sr)
    assert len(cuts) == 1
    c = cuts[0]
    assert 0.3 <= c['t'] <= 0.5
    assert not c['safe'] # gap is < drop threshold in our dummy energy array

    # With VAD
    vad_t = np.linspace(0, 1.0, 30)
    vad_p = np.full(30, 0.9)
    # pause in VAD between 0.3 and 0.5 -> prob 0.1
    vad_p[10:15] = 0.1

    cuts = wordtimes.cut_points(words, x, sr, vad=(vad_t, vad_p))
    assert len(cuts) == 1
    c = cuts[0]
    assert 0.3 <= c['t'] <= 0.5
    assert c['safe']
    assert c['pause_s'] > 0

    # No gap / words touching
    words = [(0.1, 0.3, 1.0), (0.3, 0.5, 1.0)]
    cuts = wordtimes.cut_points(words, x, sr)
    assert len(cuts) == 1
    assert not cuts[0]['safe']


def test_force_align(monkeypatch):
    import sys
    import types
    import numpy as np

    class FakeTokenizer:
        def get_vocab(self):
            return {'A': 1, 'B': 2, '|': 3}

        @property
        def pad_token_id(self):
            return 0

    class FakeProc:
        def __init__(self):
            self.tokenizer = FakeTokenizer()

    # Fake load to return our proc
    monkeypatch.setattr(wordtimes, '_load', lambda lang: (FakeProc(), None))

    # Fake emissions (frames, vocab)
    # vocab size is 4 (0=pad, 1=A, 2=B, 3=|)
    # Let's create an emission matrix that perfectly spells 'A' then '|' then 'B'
    T = 10
    em = np.full((T, 4), -np.inf)
    em[0:3, 0] = 0.0 # pad
    em[3, 1] = 0.0   # A
    em[4:6, 0] = 0.0 # pad
    em[6, 3] = 0.0   # |
    em[7:9, 0] = 0.0 # pad
    em[9, 2] = 0.0   # B

    monkeypatch.setattr(wordtimes, 'emissions', lambda x, lang: em)

    # We should get a match
    aligned = wordtimes.force_align(None, ['A', 'B'])

    assert len(aligned) == 2
    # aligned word 0 is 'A' (frame 3) -> 0.06 to 0.08
    assert abs(aligned[0][0] - 0.06) < 1e-4
    assert abs(aligned[0][1] - 0.08) < 1e-4
    assert aligned[0][2] == 1.0

    # aligned word 1 is 'B' (frame 9) -> 0.18 to 0.20
    assert abs(aligned[1][0] - 0.18) < 1e-4
    assert abs(aligned[1][1] - 0.20) < 1e-4
    assert aligned[1][2] == 1.0

    # Unmatchable word
    aligned = wordtimes.force_align(None, ['X'])
    assert len(aligned) == 1
    assert aligned[0] is None

def test_load_and_emissions(monkeypatch):
    import numpy as np
    from fakes import mock_torch, mock_transformers
    mock_torch(monkeypatch)
    mock_transformers(monkeypatch)

    # Force _load
    wordtimes._M.clear()

    x16 = np.zeros(16000)
    em = wordtimes.emissions(x16, 'en')
    assert em.shape == (10, 4)
    assert 'en' in wordtimes._M
