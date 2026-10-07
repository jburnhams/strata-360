"""edit/music.py beat tracker, key and bar features, and edit/remix.py (re-sequencing a track to any length), on synthetic audio: clicks at a known tempo, a drifting tempo, a tone sequence with known self-similar bars."""
import numpy as np
import pytest
from strata360.edit import music as M, remix as R

SR = M.SR


def clicks(times, dur, accent_every=4):
    x = np.zeros(int(dur * SR), np.float32)
    for i, t in enumerate(times):
        a = int(t * SR); n = int(0.02 * SR); amp = 1.0 if i % accent_every == 0 else 0.5; x[a:a + n] += amp * np.hanning(n).astype(np.float32) * np.sin(2 * np.pi * (120 if i % accent_every == 0 else 2000) * np.arange(n) / SR)
    return x


def tones(bars, bar_s=2.0, sr=SR):
    """One chord per bar (bars = list of semitone offsets from A3): bar i of the same value sounds the same."""
    out = []
    for b in bars:
        t = np.arange(int(bar_s * sr)) / sr; out.append(sum(np.sin(2 * np.pi * 220 * 2 ** ((b + k) / 12) * t) for k in (0, 4, 7)).astype(np.float32) / 3)
    return np.concatenate(out)


def test_beats_follow_a_steady_tempo_to_a_few_milliseconds():
    true = np.arange(0.5, 30, 0.5); g = M.beat_grid(clicks(true, 31))
    b = np.array(g['beats']); b = b[(b > true[0] - 0.01) & (b < true[-1] + 0.01)]; assert g['bpm'] == pytest.approx(120, abs=1.5)
    assert np.abs(b[:, None] - true[None, :]).min(1).max() < 0.012                                    # every reported beat is on a click
    assert len(b) == pytest.approx(len(true), abs=2)


def test_beats_follow_a_drifting_tempo():
    times = [0.5]
    while times[-1] < 40: times.append(times[-1] + 0.5 + 0.0015 * len(times))                         # the beat slows down about 1.5 ms every beat
    times = np.array(times[:-1]); g = M.beat_grid(clicks(times, 41)); b = np.array(g['beats']); b = b[(b > times[0] - 0.01) & (b < times[-1] + 0.01)]
    assert np.abs(b[:, None] - times[None, :]).min(1).max() < 0.02


def test_the_downbeat_is_the_beat_with_the_low_attack():
    true = np.arange(0.5 + 0.5, 30, 0.5)                                                                # the first accented click is the second beat
    x = clicks(true, 31); g = M.beat_grid(x); d = np.array(g['downbeats'])
    assert np.abs(np.diff(d) - 2.0).max() < 0.03 and np.abs(((d - 1.0) / 2.0) - np.round((d - 1.0) / 2.0)).max() < 0.02


def test_key_of_an_a_major_chord_progression():
    S = M.spectrogram(tones([0, 0, 5, 5, 7, 7, 0, 0], 2.0)); t, mode, name, conf = M.estimate_key(M.chroma(S))
    assert (t, mode, name) == (9, 'major', 'A major')                                                  # A, D and E major triads
    assert 0 <= conf <= 1


def test_key_of_a_c_major_scale():
    S = M.spectrogram(np.concatenate([tones([s], 0.5) for s in (3, 5, 7, 8, 10, 12, 14, 15)]))
    assert M.estimate_key(M.chroma(S))[:2] in {(0, 'major'), (9, 'minor')}


def test_the_same_chord_in_two_bars_is_similar_and_a_different_one_is_not():
    x = tones([0, 0, 6, 0]); db = [0, 2, 4, 6, 8]; sim = M.bar_similarity(M.bar_features(x, db))
    assert sim[0, 1] > 0.97 and sim[0, 3] > 0.97 and sim[0, 2] < 0.9 and sim.shape == (4, 4)


@pytest.fixture
def song():
    """Eight bars: A A B B A A C C (every letter a different chord), the last bar its ending."""
    sim = M.bar_similarity(M.bar_features(tones([0, 0, 6, 6, 0, 0, 3, 3]), [2.0 * i for i in range(9)])); return sim


@pytest.mark.parametrize('target', [4, 8, 12, 20, 40])
def test_a_plan_has_the_target_length_starts_at_the_start_and_ends_on_the_ending(song, target):
    p = R.plan(song, target); assert len(p['bars']) == target
    if target >= 4: assert p['bars'][0] == 0 and p['bars'][-2:] == [6, 7]
    assert all(0 <= b < 8 for b in p['bars'])


def test_a_plan_of_the_tracks_own_length_plays_it_as_it_is(song):
    assert R.plan(song, 8)['bars'] == list(range(8))


def test_joins_land_between_bars_that_sound_alike(song):
    p = R.plan(song, 20)
    for (a, n), (b, _) in zip(p['runs'], p['runs'][1:]): assert song[a + n - 1, b - 1] > 0.99 or song[a + n, b] > 0.99
    assert p['worst_join'] < 0.3                                                                       # there are joins that cost almost nothing, so no bad one is chosen


def test_the_ending_bars_are_not_played_in_the_middle(song):
    assert all(b < 6 for b in R.plan(song, 30)['bars'][:-2])


def test_levels_pull_the_plan_toward_matching_bars():
    sim = np.eye(6) * 0.5 + 0.5; energy = [0.1, 0.1, 0.9, 0.9, 0.5, 0.5]
    quiet = R.plan(sim, 12, levels=[0.1] * 12, energy=energy, level_weight=5); loud = R.plan(sim, 12, levels=[0.9] * 12, energy=energy, level_weight=5)
    assert np.mean([energy[b] for b in quiet['bars'][1:-2]]) < 0.3 and np.mean([energy[b] for b in loud['bars'][1:-2]]) > 0.6


def test_a_target_shorter_than_the_ending_is_its_last_bars(song):
    assert R.plan(song, 1)['bars'] == [7] and R.plan(song, 0 + 2)['bars'][-1] == 7
    with pytest.raises(ValueError): R.plan(song, 0)


def test_render_keeps_every_bar_line_and_the_length():
    sr = 8000; x = np.concatenate([np.full(sr * 2, v, np.float32) for v in (0.1, 0.2, 0.3, 0.4)]); db = [0.0, 2.0, 4.0, 6.0]
    y, marks = R.render(x, sr, db, [0, 1, 0, 1, 2, 3], fade_s=0.04, end_s=8.0)
    assert marks == [0, 2, 4, 6, 8, 10] and len(y) == int(12 * sr)
    for t, v in [(1.0, 0.1), (3.0, 0.2), (5.0, 0.1), (7.0, 0.2), (9.0, 0.3), (11.0, 0.4)]: assert y[int(t * sr), 0] == pytest.approx(v, abs=1e-6)


def test_a_join_is_an_equal_power_crossfade_on_the_bar_line():
    sr = 8000; x = np.ones(sr * 8, np.float32); y, _ = R.render(x, sr, [0.0, 2.0, 4.0, 6.0], [0, 1, 2, 1], fade_s=0.1, end_s=8.0)
    j = 6 * sr; assert y[j, 0] == pytest.approx(np.sqrt(2), abs=0.01) and y[j - 2 * sr // 10, 0] == pytest.approx(1.0, abs=1e-6) and y[j + 2 * sr // 10, 0] == pytest.approx(1.0, abs=1e-6)


def test_a_held_range_is_never_cut_by_a_jump():
    n = 30; sim = np.eye(n) * 0.0 + 0.9; np.fill_diagonal(sim, 1.0)                       # every join costs the same, so the plan may jump anywhere
    free = R.plan(sim, 14, jump_penalty=0.0)
    held = R.plan(sim, 14, jump_penalty=0.0, hold=[(8, 14)])
    def whole(bars): return all(bars[bars.index(b) + 1] == b + 1 for b in range(8, 14) if b in bars and bars.index(b) + 1 < len(bars))
    assert whole(held['bars']) and any(r[0] <= 8 <= r[0] + r[1] - 1 for r in held['runs']) or 8 not in held['bars']
    assert len(free['bars']) == len(held['bars']) == 14


def test_a_prefix_is_played_as_the_track_has_it_and_the_jumps_come_after():
    n = 40; sim = np.full((n, n), 0.2); np.fill_diagonal(sim, 1.0)
    p = R.plan(sim, 30, prefix=10, jump_penalty=0.0)
    assert p['bars'][:10] == list(range(10)) and p['bars'][-2:] == [38, 39] and len(p['bars']) == 30
    assert R.plan(sim, 12, prefix=10)['bars'][:10] == list(range(10))
    assert R.plan(sim, 8, prefix=10)['bars'][-2:] == [38, 39]                                  # too short for the opening: ordinary plan


def test_stray_beats_are_pulled_back_onto_the_tempo_but_drift_is_kept():
    true = np.arange(0, 60 * 0.6, 0.6); b = true.copy(); b[20] += 0.17; b[31] -= 0.14; b[32] += 0.12                  # beats that landed on off-beat hits
    r = M.regularise(b); assert np.abs(r - true).max() < 0.01
    drift = np.cumsum(0.5 + 0.0015 * np.arange(80)); assert np.abs(M.regularise(drift) - drift).max() < 0.012          # a real tempo change is not flattened


def test_a_bad_join_costs_more_so_the_worst_join_never_gets_worse():
    rng = np.random.default_rng(3); n = 40; a = rng.random((n, n)); sim = (a + a.T) / 2; np.fill_diagonal(sim, 1.0); energy = rng.random(n); lv = rng.random(30)
    for seed in range(3):
        energy = np.random.default_rng(seed).random(n); lv = np.random.default_rng(seed + 9).random(30)
        with_pen = R.plan(sim, 30, levels=lv, energy=energy); without = R.plan(sim, 30, levels=lv, energy=energy, bad_weight=0.0)
        assert with_pen['worst_join'] <= without['worst_join'] + 1e-9 and len(with_pen['bars']) == 30


def test_a_cheap_join_is_not_used_over_and_over_to_loop_a_few_bars():
    n = 30; sim = np.full((n, n), 0.1); np.fill_diagonal(sim, 1.0); sim[23, 20] = sim[22, 19] = 1.0                      # jumping from bar 22 back to bar 20 costs nothing; every other jump is poor
    loop = R.plan(sim, 70, short_weight=0.0); spread = R.plan(sim, 70)
    runs = lambda p: [r[1] for r in p['runs'][:-1]]
    assert min(runs(loop)) <= 3 and len(loop['bars']) == len(spread['bars']) == 70                                       # the loop is there without the penalty
    assert sum(1 for r in runs(spread) if r < 4) < sum(1 for r in runs(loop) if r < 4)                                   # and used less with it
    flat = R.plan(np.full((n, n), 0.9), 40); assert flat['bars'][-2:] == [28, 29] and len(flat['bars']) == 40


def test_a_pinned_stretch_plays_its_source_bars_at_the_film_bars_asked():
    n = 40; sim = np.full((n, n), 0.2); np.fill_diagonal(sim, 1.0)
    p = R.plan(sim, 60, pins=[(30, 12, 6)]); assert p['bars'][30:36] == [12, 13, 14, 15, 16, 17] and p['bars'][-2:] == [38, 39] and len(p['bars']) == 60
    p = R.plan(sim, 60, prefix=10, pins=[(5, 20, 4), (30, 12, 6)]); assert p['bars'][:10] == list(range(10)) and p['bars'][30:36] == list(range(12, 18))              # a pin inside the opening is ignored
    p = R.plan(sim, 60, pins=[(30, 37, 6)]); assert len(p['bars']) == 60 and p['bars'][-2:] == [38, 39]                                                           # one into the ending is ignored where it cannot be played
