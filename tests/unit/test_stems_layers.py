"""edit/stems.py (cache, separator contract) and edit/layers.py (per-bar gains, mixing, vocal windows, the stray-vocal check) with fake separation and synthetic stems."""
import json, os
import numpy as np
import pytest
from strata360.edit import stems as ST, layers as L

SR = 8000


def stem_set(n=4, bar=SR):
    t = np.arange(n * bar) / SR
    return {k: (np.stack([np.sin(2 * np.pi * f * t)] * 2, 1) * 0.5).astype(np.float32) for k, f in zip(ST.NAMES, (100, 200, 300, 400))}


def npy_io():
    store = {}
    def write(p, x, sr): store[p] = (np.array(x), sr); open(p, "wb").write(b"x")
    def read(p): return store[p]
    return write, read, store


@pytest.fixture
def rd(tmp_path):
    os.makedirs(tmp_path / 'music'); (tmp_path / 'music' / 'track.mp3').write_bytes(b'abc'); return str(tmp_path)


def test_stems_are_separated_once_and_then_read_back(rd):
    write, read, store = npy_io(); calls = []
    def sep(path): calls.append(path); return stem_set(), SR
    a, sr = ST.stems_for(rd, 'music/track.mp3', sep, write, read); b, _ = ST.stems_for(rd, 'music/track.mp3', sep, write, read)
    assert len(calls) == 1 and sr == SR and set(a) == set(ST.NAMES) == set(b) and len(store) == 4
    assert json.load(open(os.path.join(rd, 'music', 'stems', 'stems.json')))['file'] == 'music/track.mp3'
    assert np.allclose(a['bass'], b['bass'])


def test_a_replaced_track_is_separated_again(rd):
    write, read, _ = npy_io(); calls = []
    sep = lambda p: (calls.append(1), (stem_set(), SR))[1]
    ST.stems_for(rd, 'music/track.mp3', sep, write, read); open(os.path.join(rd, 'music', 'track.mp3'), 'wb').write(b'longer file'); ST.stems_for(rd, 'music/track.mp3', sep, write, read)
    assert len(calls) == 2


def test_a_separator_that_misses_a_stem_is_an_error(rd):
    write, read, _ = npy_io(); s = stem_set(); del s['drums']
    with pytest.raises(RuntimeError, match='drums'): ST.stems_for(rd, 'music/track.mp3', lambda p: (s, SR), write, read)


def test_gains_follow_the_level_in_phrases():
    g = L.layer_gains([0.0] * 4 + [1.0] * 4 + [0.0, 1.0, 0.0, 1.0], phrase_bars=4)
    assert g['drums'][:4].tolist() == [0] * 4 and g['drums'][4:8].tolist() == [1] * 4 and len(set(g['drums'][8:].tolist())) == 1     # a flickering phrase does not flicker the stem
    assert g['other'][0] == L.FLOORS['other'] and g['other'][4] == 1 and not g['vocals'].any()
    assert g['bass'][0] == 0 and g['bass'][4] == 1


def test_a_middle_level_brings_in_the_bass_before_the_drums():
    g = L.layer_gains([0.3] * 4); assert 0 < g['bass'][0] < 1 and g['drums'][0] == 0


def test_vocals_open_only_in_the_windows():
    g = L.open_vocals(L.layer_gains([0.5] * 8), [(2, 4), (6, 20)]); assert g['vocals'].tolist() == [0, 0, 1, 1, 0, 0, 1, 1]


def test_the_mix_sums_stems_under_their_gains_and_keeps_the_bar_lines():
    s = stem_set(4); db = [0.0, 1.0, 2.0, 3.0]; bars = [0, 1, 2, 3]; g = {n: np.zeros(4) for n in ST.NAMES}; g['bass'] = np.array([1, 1, 0, 0.0]); g['vocals'] = np.array([0, 0, 0, 1.0])
    y, marks = L.mix(s, SR, db, bars, g, end_s=4.0); assert marks == [0, 1, 2, 3] and len(y) == 4 * SR
    assert np.abs(y[int(0.3 * SR):int(0.9 * SR)]).max() > 0.4 and np.abs(y[int(2.3 * SR):int(2.8 * SR)]).max() < 1e-6
    bass_only = np.abs(y[int(0.3 * SR):int(0.9 * SR)] - s['bass'][int(0.3 * SR):int(0.9 * SR)]).max(); assert bass_only < 1e-5
    assert np.allclose(y[int(3.3 * SR):int(3.9 * SR)], s['vocals'][int(3.3 * SR):int(3.9 * SR)], atol=1e-5)


def test_a_gain_change_ramps_instead_of_clicking():
    s = {'bass': np.ones((4 * SR, 2), np.float32)}; y, _ = L.mix(s, SR, [0.0, 1.0, 2.0, 3.0], [0, 1, 2, 3], {'bass': np.array([1, 0, 0, 0.0])}, ramp_s=0.25, end_s=4.0)
    assert np.abs(np.diff(y[:, 0])).max() < 0.001 and y[int(0.8 * SR), 0] == 1 and y[int(1.2 * SR), 0] == 0 and y[SR, 0] == pytest.approx(0.5, abs=0.01)


def test_the_vocal_check_hears_leaks_outside_the_windows_only():
    v = np.zeros((4 * SR, 2), np.float32); v[SR:2 * SR] = 0.5; marks = [0.0, 1.0, 2.0, 3.0]
    assert L.stray_vocal_db(v, SR, marks, [(1, 2)]) == float('-inf')
    v[3 * SR:] = 0.005; assert L.stray_vocal_db(v, SR, marks, [(1, 2)]) == pytest.approx(-40, abs=0.1)
    assert L.stray_vocal_db(np.zeros((4 * SR, 2), np.float32), SR, marks, []) == float('-inf')
