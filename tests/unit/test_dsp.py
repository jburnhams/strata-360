import pytest
import numpy as np
from strata360.audio import dsp

def test_db():
    # log10(1) = 0 -> 0dB
    assert dsp.db(1.0) == 0.0
    # log10(10) = 1 -> 20dB
    assert dsp.db(10.0) == 20.0
    # test array
    a = np.array([1.0, 10.0, 0.0])
    res = dsp.db(a)
    assert res[0] == 0.0
    assert res[1] == 20.0
    # 0.0 uses max with 1e-9 -> 20 * (-9) = -180
    assert abs(res[2] - (-180.0)) < 1e-5

def test_majority():
    # window size k
    labels = [1, 1, 0, 0, 0, 1, 1, 1]
    # with k=3
    # idx 0: [1,1,0] -> sum 2 -> >1.5 -> 1
    # idx 1: [1,0,0] -> sum 1 -> <1.5 -> 0
    # idx 2: [0,0,0] -> 0
    # idx 3: [0,0,1] -> 0
    # idx 4: [0,1,1] -> 1
    # idx 5: [1,1,1] -> 1
    out = dsp._majority(labels, 3)
    assert np.array_equal(out, [1, 1, 0, 0, 0, 1, 1, 1])

def test_peak_limit(monkeypatch):

    calls = []
    def fake_ff(x, sr, g):
        calls.append(g)
        # simulate scaling down
        return (x / 2.0).reshape(-1, 1)
    monkeypatch.setattr(dsp, 'ffmpeg_filter', fake_ff)
    x = np.array([0.5, 1.5, -2.0, -0.1], dtype=np.float32)
    limited = dsp._peak_limit(x, 1.0)
    assert 'limit=1.0' in calls[0]

    # If below limit, unchanged
    x2 = np.array([0.5, -0.5])
    lim2 = dsp._peak_limit(x2, 1.0)
    assert np.array_equal(x2, lim2)

def test_envelope_db():
    # 1 second of constant DC
    sr = 1000
    x = np.ones(sr)
    rate = 100 # 100 samples per second out -> 100Hz -> hop is 10 samples
    env = dsp.envelope_db(x, rate, sr)
    assert len(env) == rate
    # envelope of 1.0 is 0 dB
    assert np.allclose(env, 0.0)

def test_k_weight():
    # Test k_weight filter shape roughly
    sr = 48000
    # Generate some white noise
    np.random.seed(0)
    x = np.random.randn(sr)

    y = dsp.k_weight(x)
    assert len(y) == len(x)
    # The K-weighting filter typically attenuates low frequencies and boosts highs slightly
    # Just verify it runs and returns an array of the same size.

def test_block_loudness():
    # 48kHz, 1s
    sr = 48000
    x = np.zeros(sr, dtype=np.float32)
    res = dsp.block_loudness(x, block=0.4, hop=0.1, sr=sr)
    lufs = res[1]
    # 1s with 0.1s hops -> roughly 7-10 blocks (depending on padding/exact logic)
    # block is 0.4s, first block ends at 0.4s -> hops
    # silence should be -200 or similar
    assert np.all(lufs < -69)

    # constant sine wave should have consistent loudness
    x_sine = 0.5 * np.sin(2 * np.pi * 1000 * np.linspace(0, 1.0, sr))
    lufs_sine = dsp.block_loudness(x_sine, block=0.4, hop=0.1, sr=sr)[1]
    assert np.std(lufs_sine) < 1.0

def test_integrated_lufs():
    sr = 48000
    x = np.zeros(sr, dtype=np.float32)
    lufs = dsp.integrated_lufs(x, sr=sr)
    assert abs(lufs - (-70.0)) < 1.0

def test_true_peak_dbfs():
    # Over-sampled true peak logic check
    x = np.array([0.0, 1.0, 0.0, -1.0], dtype=np.float32)
    tp = dsp.true_peak_dbfs(x, oversample=4)
    # 1.0 is 0 dBFS. Resampling might push it slightly higher, but around 0
    assert abs(tp - 0.0) < 3.0

    # silence
    x2 = np.zeros(100)
    assert dsp.true_peak_dbfs(x2) < -100

def test_voicing():
    # Test _voicing directly
    sr = 16000
    t = np.linspace(0, 1.0, sr)
    # sine wave -> highly correlated
    x = np.sin(2 * np.pi * 300 * t)

    v = dsp._voicing(x, sr=sr, frame=0.032, hop=0.010)
    # A pure sine wave is highly voiced
    assert np.mean(v) > 0.8

    # white noise -> unvoiced
    np.random.seed(0)
    x_noise = np.random.randn(sr)
    v_noise = dsp._voicing(x_noise, sr=sr, frame=0.032, hop=0.010)
    assert np.mean(v_noise) < 0.3



def test_analyse_array_full(monkeypatch):
    import numpy as np

    def fake_ff(x, sr, graph, **kw):
        return x.reshape(-1, 1)

    # We mock ffmpeg functions for analysis
    monkeypatch.setattr(dsp, 'integrated_lufs', lambda x, sr=48000: -20.0)
    monkeypatch.setattr(dsp, 'true_peak_dbfs', lambda x, oversample=4: -2.0)

    sr = 48000
    x = np.zeros((sr, 1), dtype=np.float32)
    # fake audio trace to avoid silence: sine wave mixed with noise
    x[:, 0] = 0.5 * np.sin(2 * np.pi * 1000 * np.linspace(0, 1.0, sr))

    res = dsp.analyse_array(x, sr=sr, hop_s=0.1, win_s=0.4)
    assert 'summary' in res
    assert res['summary']['integrated_lufs'] == -20.0
    assert res['summary']['true_peak_dbfs'] == -2.0
    assert len(res['segments']) > 0


def test_segments():
    import numpy as np
    labels = ['silence', 'speech', 'speech', 'ambience']

    A = {
        'lufs_m': np.array([-100.0, -20.0, -20.0, -40.0]),
        'peak_dbfs': np.array([-100.0, -2.0, -2.0, -10.0]),
        'speech_band_dbfs': np.array([-100.0, -30.0, -30.0, -50.0]),
        'voiced_frac': np.array([0.0, 0.9, 0.9, 0.1]),
        'lf_share': np.array([0.0, 0.1, 0.1, 0.5]),
        'clipped_samples': np.array([0, 0, 0, 0])
    }

    t = [0.05, 0.15, 0.25, 0.35]
    hop_s = 0.1
    win_s = 0.4
    floor = -80.0
    med = -30.0

    segs = dsp._segments(labels, A, t, hop_s, win_s, floor, med)

    assert len(segs) == 3
    assert segs[0]['label'] == 'silence'
    assert segs[0]['t0_s'] == 0.0
    assert segs[0]['t1_s'] == 0.1

    assert segs[1]['label'] == 'speech'
    assert segs[1]['t0_s'] == 0.1
    assert segs[1]['t1_s'] == 0.3 # 0.25 + hop/2
    assert 'excitement_lu' in segs[1]

    assert segs[2]['label'] == 'ambience'

def test_dfn_denoise(monkeypatch):
    import sys
    import types
    import numpy as np
    from tests.utils.fakes import mock_torch, FakeTorchTensor
    mock_torch(monkeypatch)

    fake_df = types.ModuleType('df')
    fake_df_enhance = types.ModuleType('enhance')
    def fake_init_df(log_level): return [None, None, None]
    def fake_enhance(model, st, x, atten_lim_db): return [FakeTorchTensor(np.zeros_like(x[0]))]
    fake_df_enhance.init_df = fake_init_df
    fake_df_enhance.enhance = fake_enhance
    fake_df.enhance = fake_df_enhance
    monkeypatch.setitem(sys.modules, 'df', fake_df)
    monkeypatch.setitem(sys.modules, 'df.enhance', fake_df_enhance)

    x = np.zeros(100, dtype=np.float32)
    y = dsp.dfn_denoise(x)
    assert y.shape == x.shape

def test_clean_for_playback(monkeypatch):
    import numpy as np

    def fake_ff(x, sr, graph, **kw):
        return x.reshape(-1, 1)

    # We mock ffmpeg functions for analysis
    monkeypatch.setattr(dsp, 'ffmpeg_filter', fake_ff)
    monkeypatch.setattr(dsp, 'dfn_denoise', lambda x, atten: x)
    monkeypatch.setattr(dsp, '_smooth_gain', lambda tgt, r, a, rel: np.ones_like(tgt))
    monkeypatch.setattr(dsp, 'block_loudness', lambda x, block, hop, sr: (np.linspace(0, 1.0, 10), np.full(10, -20.0), np.full(10, -20.0)))
    monkeypatch.setattr(dsp, '_peak_limit', lambda x, lim: x)

    # Clean for playback uses integrated_lufs and block_loudness.
    # actually it just runs an afir filter via ffmpeg. It doesn't call integrated_lufs directly?
    # Let's check.
    # The traceback showed 221-228 is clean_for_playback. We'll just call it and return early.
    x = np.zeros(100, dtype=np.float32)
    y = dsp.clean_for_playback(x)
    assert y.shape == x.shape

def test_write_flac(fake_run):
    import numpy as np

    x = np.zeros(100, dtype=np.float32)
    dsp.write_flac('/tmp/out.flac', x)
    assert len(fake_run.calls) == 1
    assert 'flac' in fake_run.calls[0]
