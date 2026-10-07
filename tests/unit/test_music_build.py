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


def fake_stems(x, rhythm=False):
    """A held tone per stem; with rhythm the drums stem is the song itself (its clicks), so the build has a beat to check."""
    sr = 8000; n = int(len(x) / M.SR * sr); t = np.arange(n) / sr
    mk = lambda f: np.stack([0.3 * np.sin(2 * np.pi * f * t)] * 2, 1).astype(np.float32); st = {k: mk(f) for k, f in zip(ST.NAMES, (100, 200, 300, 400))}
    if rhythm: d = np.interp(t, np.arange(len(x)) / M.SR, x).astype(np.float32); st['drums'] = np.stack([d, d], 1)
    return st, sr


def io():
    store = {}
    def write(p, x, sr): store[p] = (np.array(x), sr); open(p, 'wb').write(b'x')
    return write, lambda p: store[p], store


def test_a_built_track_has_the_length_the_bar_lines_and_the_ending(rd):
    x = song(); write, read, store = io(); st = fake_stems(x)
    s = MB.build(rd, 'music/track.mp3', 40.0, keep_intro=False, decode=lambda p: x, separator=lambda p: st, write=write, read=read)
    assert s['source'] == 'built' and len(s['bars']) == 20 and s['length_s'] == pytest.approx(40.0, abs=0.3) and s['bars'][-2:] == [6, 7] and s['bars'][0] == 0
    assert np.allclose(np.diff(s['downbeats']), BAR, atol=0.05) and json.load(open(os.path.join(rd, 'music', 'built.json')))['bars'] == s['bars']
    assert s['stray_vocal_db'] is None and store[os.path.join(rd, 'music', 'built.flac')][1] == 8000


def test_vocals_play_only_in_the_given_windows(rd):
    x = song(); write, read, store = io(); st = fake_stems(x)
    s = MB.build(rd, 'music/track.mp3', 24.0, windows=[(4, 6)], keep_intro=False, decode=lambda p: x, separator=lambda p: st, write=write, read=read)
    y, sr = store[os.path.join(rd, 'music', 'built.flac')]; assert s['windows'] == [[4, 6]] and s['stray_vocal_db'] < -20                  # the 0.25 s ramp at a window's edge is all that leaks
    inside = np.abs(y[int(9 * sr):int(11 * sr)]).max(); stems_only = MB.layers.layer_gains(np.full(12, 0.5))
    assert inside > 0.3 and stems_only['vocals'].sum() == 0


def test_levels_choose_the_layers_and_the_grid_is_cached(rd):
    x = song(); write, read, _ = io(); st = fake_stems(x); calls = []
    def dec(p): calls.append(1); return x
    MB.build(rd, 'music/track.mp3', 24.0, levels=[0.0] * 6 + [1.0] * 6, decode=dec, separator=lambda p: st, write=write, read=read); n = len(calls)
    MB.build(rd, 'music/track.mp3', 24.0, decode=dec, separator=lambda p: st, write=write, read=read)
    g = json.load(open(os.path.join(rd, 'music', 'grid.json'))); assert g['key']['name'] and len(g['energy']) == len(g['downbeats']) - 1 == len(g['sim']) and len(calls) == n + 1      # the grid, with its bar similarity, is cached: the second build decodes the track only for its beat check


def test_the_bar_count_follows_the_length():
    g = dict(downbeats=[0.0, 2.0, 4.0, 6.0]); assert MB.bar_count(g, 40.0) == (20, 2.0) and MB.bar_count(g, 0.1)[0] == 1


def test_the_opening_is_the_first_build_and_the_break_after_it():
    e = [0, 0, 0, 0, .24, .4, .4, .37, .73, .99, 1, .97, 1, .95, .96, .97, 1, .95, 1, .42, .03, .35, .61, .36]
    assert MB.intro_bars(e) == 22                                                                 # the energy returns at bar 22
    assert MB.intro_bars([0.1, 0.2, 0.3, 0.4]) == 0 and MB.intro_bars([0, 0.9, 0.95, 0.9]) == 0   # no peak, or no break after it


def test_the_opening_plays_as_it_is_with_every_stem_on(rd, monkeypatch):
    x = song(); write, read, store = io(); st = fake_stems(x); monkeypatch.setattr(MB, 'intro_bars', lambda e: 4)
    s = MB.build(rd, 'music/track.mp3', 40.0, levels=[0.0] * 20, decode=lambda p: x, separator=lambda p: st, write=write, read=read)
    assert s['intro_bars'] == 4 and s['bars'][:4] == [0, 1, 2, 3] and s['bars'][-2:] == [6, 7] and s['windows'][0][0] == 0
    assert MB.build(rd, 'music/track.mp3', 40.0, keep_intro=False, decode=lambda p: x, separator=lambda p: st, write=write, read=read)['intro_bars'] == 0


def test_the_ending_is_the_last_loud_bar_not_the_long_fade():
    e = [0.9] * 90 + [0.8, 0.62, 0.3, 0, 0, 0, 0, 0, 0]
    assert MB.quick_end(e) == 91 and MB.quick_end([0.1, 0.2]) == 0


def test_a_quick_ending_cuts_the_track_after_its_last_loud_bar_and_fades(rd):
    x = song(); write, read, store = io(); st = fake_stems(x); kw = dict(keep_intro=False, decode=lambda p: x, separator=lambda p: st, write=write, read=read)
    full = MB.build(rd, 'music/track.mp3', 24.0, **kw); quick = MB.build(rd, 'music/track.mp3', 24.0, ending='quick', fade_s=1.0, **kw)
    y, sr = store[os.path.join(rd, 'music', 'built.flac')]
    assert full['ending'] == 'original' and quick['ending'] in ('quick', 'original')
    if quick['ending'] == 'quick': assert quick['length_s'] <= full['length_s'] and abs(y[-int(0.05 * sr):]).max() < 0.1 * abs(y).max() + 1e-6


def test_a_pin_plays_the_asked_source_bars_at_the_asked_film_bars_with_the_vocals_open(rd):
    x = song(); write, read, store = io(); st = fake_stems(x)
    s = MB.build(rd, 'music/track.mp3', 40.0, keep_intro=False, pins=[(10, 2, 3)], decode=lambda p: x, separator=lambda p: st, write=write, read=read)
    assert s['bars'][10:13] == [2, 3, 4] and [10, 13] in s['windows'] and s['pins'] == [[10, 2, 3]] and len(s['bars']) == 20


def fake_generator(calls, level=0.05):
    def make(sr):
        def gen(items, seeds):
            calls.append([(s['first'], s['end'], s['mode'], seed) for (s, _), seed in zip(items, seeds)])
            return [level * np.asarray(inp['src'], np.float32) for _, inp in items]                                  # the bars it replaces, quieter: the same beat
        return gen
    return make


def test_generated_sections_are_spliced_in_matched_and_checked(rd):
    x = song(); write, read, store = io(); st = fake_stems(x, rhythm=True); calls = []
    s = MB.build(rd, 'music/track.mp3', 40.0, levels=[0.15] * 8 + [0.9] * 12, keep_intro=False, fidelity=0.0, style='rock', generator=fake_generator(calls),
                 decode=lambda p: x, separator=lambda p: st, write=write, read=read, vocals_of=lambda y, sr: 0.001 * y, log=lambda m: None)
    assert [p[:3] for p in calls[0]] == [(0, 8, 'text'), (8, 18, 'text')] and len(calls) == 1                     # the last two bars are the track's own ending
    assert all(p['ok'] and not p.get('kept_original') for p in s['generated']) and s['share_original'] == 0.0 and s['sections'][0]['source'] == 'generate'
    assert s['generated'][1]['gain'] > 5 and s['generated'][1]['takes'][0]['action'] == 'as is'                    # a take at a twentieth of the level, matched to the bars around it
    assert s['check']['length']['ok'] and s['length_s'] == 40.0 and s['check']['grid']['ok'] and s['check']['ok'] and s['generated'][0]['singing_db'] == -60.0


def test_without_a_style_or_a_generator_the_track_plays_and_says_why(rd):
    x = song(); write, read, _ = io(); st = fake_stems(x); kw = dict(levels=[0.15] * 8 + [0.9] * 12, keep_intro=False, fidelity=0.0, decode=lambda p: x, separator=lambda p: st, write=write, read=read)
    s = MB.build(rd, 'music/track.mp3', 40.0, generator=fake_generator([]), **kw); assert all(p['kept_original'] and 'style' in p['why'] for p in s['generated']) and not s['check']['ok']
    s = MB.build(rd, 'music/track.mp3', 40.0, style='rock', **kw); assert 'ACE-Step' in s['generated'][0]['why']
    def broken(sr):
        def gen(items, seeds): raise RuntimeError('ACE-Step failed: CUDA out of memory')
        return gen
    s = MB.build(rd, 'music/track.mp3', 40.0, style='rock', generator=broken, log=lambda m: None, **kw); assert 'out of memory' in s['generated'][0]['why'] and s['length_s'] == 40.0


def test_the_record_generates_nothing_and_a_pin_or_a_sung_moment_keeps_the_original(rd):
    x = song(); write, read, _ = io(); st = fake_stems(x, rhythm=True); calls = []; kw = dict(levels=[0.15] * 8 + [0.9] * 12, keep_intro=False, style='rock', generator=fake_generator(calls), decode=lambda p: x, separator=lambda p: st, write=write, read=read, log=lambda m: None)
    s = MB.build(rd, 'music/track.mp3', 40.0, fidelity=1.0, **kw); assert calls == [] and s['generated'] == [] and s['share_original'] == 1.0
    s = MB.build(rd, 'music/track.mp3', 40.0, fidelity=0.0, section_pins={0: 'original'}, windows=[(10, 12)], **kw)
    assert [p[:2] for p in calls[-1]] == [(8, 10), (12, 18)] and s['section_pins'] == {'0': 'original'} and s['sections'][0]['pinned']


def test_a_chosen_take_is_used_and_a_new_build_lists_what_was_remade(rd):
    x = song(); write, read, _ = io(); st = fake_stems(x, rhythm=True); calls = []; kw = dict(keep_intro=False, style='rock', generator=fake_generator(calls), decode=lambda p: x, separator=lambda p: st, write=write, read=read, log=lambda m: None)
    s = MB.build(rd, 'music/track.mp3', 40.0, levels=[0.15] * 8 + [0.9] * 12, fidelity=0.0, **kw); key = s['generated'][1]['key']; assert s['remade'] == [0, 8]
    s = MB.build(rd, 'music/track.mp3', 40.0, levels=[0.15] * 8 + [0.9] * 12, fidelity=0.0, takes={key: 4}, **kw); assert calls[-1][1][3] == 4 and s['generated'][1]['seed'] == 4 and s['generated'][1]['chosen'] == 4 and s['remade'] == []


def test_at_high_fidelity_a_pinned_section_is_repainted_inside_its_own_bars(rd):
    x = song(); write, read, _ = io(); st = fake_stems(x); seen = []
    def make(sr):
        def gen(items, seeds):
            seen.extend(items); return [np.full((int(round(inp['marks'][-1] * sr)), 2), 0.05, np.float32) for _, inp in items]
        return gen
    s = MB.build(rd, 'music/track.mp3', 60.0, levels=[0.5] * 30, keep_intro=False, fidelity=0.8, section_pins={0: 'generate'}, style='rock', generator=make, decode=lambda p: x, separator=lambda p: st, write=write, read=read, log=lambda m: None)
    spec, inp = seen[0]; sr = 8000
    assert spec['mode'] == 'repaint' and (spec['first'], spec['end']) == (0, 28) and inp['r0'] == 0.0 and inp['r1'] == pytest.approx(56.0, abs=0.1)
    assert len(inp['src']) == pytest.approx(60.0 * sr, abs=sr * 0.1) and len(inp['ref']) == pytest.approx(16.0 * sr, abs=sr * 0.1)            # the context runs on into the ending's bars; the reference is the track's instrumental (it is only 16 s long)
    assert s['generated'][0]['mode'] == 'repaint' and s['generated'][0]['strength'] == 0.72
