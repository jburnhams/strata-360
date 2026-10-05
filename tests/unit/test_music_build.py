"""edit/music_build.py end to end on a synthetic song with fake decoding, separation and file I/O: length, bar lines, the ending, vocals only in windows, caching."""
import json, os
import numpy as np
import pytest
from strata360.edit import music as M, music_build as MB, stems as ST

BAR = 2.0


def song():
    """Eight bars of clicks (accent on the downbeat), a different chord each pair."""
    sr = M.SR; x = np.zeros(int(8 * BAR * sr), np.float32); chords = [0, 0, 5, 5, 7, 7, 0, 0]
    for b, c in enumerate(chords):
        t = np.arange(int(BAR * sr)) / sr; x[int(b * BAR * sr):int((b + 1) * BAR * sr)] = sum(0.3 * np.sin(2 * np.pi * 220 * 2 ** ((c + k) / 12) * t) for k in (0, 4, 7))
        for beat in range(4):
            a = int((b * BAR + beat * 0.5) * sr); n = int(0.02 * sr); x[a:a + n] += (1.0 if beat == 0 else 0.4) * np.hanning(n) * np.sin(2 * np.pi * (100 if beat == 0 else 3000) * np.arange(n) / sr)
    return x


@pytest.fixture
def rd(tmp_path):
    os.makedirs(tmp_path / 'music'); (tmp_path / 'music' / 'track.mp3').write_bytes(b'abc'); return str(tmp_path)


def fake_stems(x):
    sr = 8000; n = int(len(x) / M.SR * sr); t = np.arange(n) / sr
    mk = lambda f: np.stack([0.3 * np.sin(2 * np.pi * f * t)] * 2, 1).astype(np.float32)
    return {k: mk(f) for k, f in zip(ST.NAMES, (100, 200, 300, 400))}, sr


def io():
    store = {}
    def write(p, x, sr): store[p] = (np.array(x), sr); open(p, 'wb').write(b'x')
    return write, lambda p: store[p], store


def test_a_built_track_has_the_length_the_bar_lines_and_the_ending(rd):
    x = song(); write, read, store = io(); st = fake_stems(x)
    s = MB.build(rd, 'music/track.mp3', 40.0, decode=lambda p: x, separator=lambda p: st, write=write, read=read)
    assert s['source'] == 'built' and len(s['bars']) == 20 and s['length_s'] == pytest.approx(40.0, abs=0.3) and s['bars'][-2:] == [6, 7] and s['bars'][0] == 0
    assert np.allclose(np.diff(s['downbeats']), BAR, atol=0.05) and json.load(open(os.path.join(rd, 'music', 'built.json')))['bars'] == s['bars']
    assert s['stray_vocal_db'] == float('-inf') and store[os.path.join(rd, 'music', 'built.flac')][1] == 8000


def test_vocals_play_only_in_the_given_windows(rd):
    x = song(); write, read, store = io(); st = fake_stems(x)
    s = MB.build(rd, 'music/track.mp3', 24.0, windows=[(4, 6)], decode=lambda p: x, separator=lambda p: st, write=write, read=read)
    y, sr = store[os.path.join(rd, 'music', 'built.flac')]; assert s['windows'] == [[4, 6]] and s['stray_vocal_db'] < -20                  # the 0.25 s ramp at a window's edge is all that leaks
    inside = np.abs(y[int(9 * sr):int(11 * sr)]).max(); stems_only = MB.layers.layer_gains(np.full(12, 0.5))
    assert inside > 0.3 and stems_only['vocals'].sum() == 0


def test_levels_choose_the_layers_and_the_grid_is_cached(rd):
    x = song(); write, read, _ = io(); st = fake_stems(x); calls = []
    def dec(p): calls.append(1); return x
    MB.build(rd, 'music/track.mp3', 24.0, levels=[0.0] * 6 + [1.0] * 6, decode=dec, separator=lambda p: st, write=write, read=read); n = len(calls)
    MB.build(rd, 'music/track.mp3', 24.0, decode=dec, separator=lambda p: st, write=write, read=read)
    g = json.load(open(os.path.join(rd, 'music', 'grid.json'))); assert g['key']['name'] and len(g['energy']) == len(g['downbeats']) - 1 and len(calls) == n + 1      # the second build decodes once for its bar features, not again for the grid


def test_the_bar_count_follows_the_length():
    g = dict(downbeats=[0.0, 2.0, 4.0, 6.0]); assert MB.bar_count(g, 40.0) == (20, 2.0) and MB.bar_count(g, 0.1)[0] == 1
