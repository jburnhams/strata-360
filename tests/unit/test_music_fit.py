"""edit/music_fit.py (G5) on synthetic clicks: the grid check, the tempo fit of a generated take, loudness matching, splicing on the downbeat, the film's length, stale sections and the repair loop. The beat tracker runs for real on clicks; the stretch is a fake (no ffmpeg)."""
import numpy as np
import pytest
from strata360.edit import music as M, music_fit as MF

SR = M.SR


def clicks(bpm, bars, start=0.0, sr=SR, per_bar=4, tail=0.5):
    """A click on every beat (a low thump on the downbeat), beginning `start` seconds in."""
    beat = 60.0 / bpm; n = int((start + bars * per_bar * beat + tail) * sr); x = np.zeros(n, np.float32); k = int(0.02 * sr)
    for i in range(bars * per_bar):
        a = int((start + i * beat) * sr); f = 100 if i % per_bar == 0 else 2500
        x[a:a + k] += (1.0 if i % per_bar == 0 else 0.5) * np.hanning(k) * np.sin(2 * np.pi * f * np.arange(k) / sr)
    return x


def resample_stretch(y, sr, factor):
    """Play y `factor` times faster (pitch moves too, which clicks do not mind)."""
    n = int(round(len(y) / factor)); return np.interp(np.arange(n) * factor, np.arange(len(y)), y).astype(np.float32)


def test_a_build_on_the_grid_passes_and_a_shifted_one_fails():
    x = clicks(120, 8); marks = [2.0 * k for k in range(8)]
    r = MF.grid_check(x, SR, marks, beat_s=0.5, end_s=16.0); assert r['ok'] and r['worst_ms'] < 15 and r['off_bars'] == [] and r['judged'] == 8
    late = MF.grid_check(x, SR, [m + 0.1 for m in marks[:7]], beat_s=0.5, end_s=14.1); assert not late['ok'] and len(late['off_bars']) == 7 and late['worst_ms'] > 60


def test_the_grid_check_reads_a_take_at_another_rate():
    x = clicks(120, 8, sr=44100); r = MF.grid_check(np.stack([x, x], 1), 44100, [2.0 * k for k in range(8)], beat_s=0.5, end_s=16.0); assert r['ok']


def test_a_take_a_little_slow_is_stretched_to_the_grid():
    bar_s = 4 * 60 / 97; x = clicks(95.5, 8)                                                               # 1.5% slow
    y, r = MF.tempo_fit(x, SR, 8, bar_s, stretch=resample_stretch)
    assert r['action'] == 'stretched' and 1.01 < r['ratio'] < 1.02 and len(y) == int(round(8 * bar_s * SR)) and r['worst_ms'] <= 40
    assert MF.grid_check(y, SR, [k * bar_s for k in range(8)], beat_s=bar_s / 4)['ok']


def test_a_take_in_time_is_used_as_it_is():
    bar_s = 4 * 60 / 97; y, r = MF.tempo_fit(clicks(97, 8), SR, 8, bar_s, stretch=lambda *a: pytest.fail('no stretch needed')); assert r['action'] == 'as is' and r['judged'] >= 7


def test_the_wrong_tempo_is_made_again_and_a_take_off_the_beat_is_repainted():
    bar_s = 4 * 60 / 97
    assert MF.tempo_fit(clicks(110, 8), SR, 8, bar_s, stretch=resample_stretch)[1]['action'] == 'regenerate'
    off = MF.tempo_fit(clicks(97, 8, start=0.1), SR, 8, bar_s, stretch=resample_stretch)[1]; assert off['action'] == 'repaint' and off['worst_ms'] > 40
    assert MF.tempo_fit(np.zeros(SR * 10, np.float32), SR, 4, bar_s)[1]['action'] == 'regenerate'


def test_the_fit_follows_the_planned_downbeats_not_an_even_grid():
    x = clicks(120, 4); marks = [0.0, 2.0, 4.0, 6.0, 8.0]
    assert MF.tempo_fit(x, SR, 4, 2.0, marks=marks, stretch=resample_stretch)[1]['action'] == 'as is'
    assert MF.tempo_fit(x, SR, 4, 2.0, marks=[0.0, 2.0, 4.1, 6.1, 8.1], stretchable=False)[1]['action'] == 'repaint'          # the last bars are planned 100 ms later than the take plays them (a section inside fixed bars cannot be stretched)


def test_loudness_is_matched_to_the_bars_around():
    rng = np.random.default_rng(0); ref = 0.1 * rng.standard_normal(SR).astype(np.float32); x = 0.25 * rng.standard_normal(SR).astype(np.float32)
    assert MF.rms(MF.gain_match(x, ref)) == pytest.approx(MF.rms(ref), rel=0.01)
    assert MF.rms(MF.gain_match(x, ref * 1000, limit=4)) == pytest.approx(4 * MF.rms(x), rel=0.01) and np.all(MF.gain_match(np.zeros(5), ref) == 0)


def test_a_splice_starts_on_the_downbeat_and_keeps_the_level():
    rng = np.random.default_rng(1); y = (0.2 * rng.standard_normal((SR * 6, 2))).astype(np.float32); x = (0.2 * rng.standard_normal((SR * 2, 2))).astype(np.float32)
    out = MF.splice(y, SR, x, 2.0, 0.25); a = 2 * SR
    assert out.shape == y.shape and np.allclose(out[:a], y[:a]) and np.allclose(out[a + SR // 2:a + SR], x[SR // 2:SR]) and np.allclose(out[a + 2 * SR:], y[a + 2 * SR:])
    assert out[a, 0] == pytest.approx(y[a, 0], abs=1e-6)                                                    # the downbeat is still the bar the listener hears
    fade = out[a:a + int(0.25 * SR)]; assert MF.rms(fade) == pytest.approx(0.2, rel=0.1)                     # equal power: no dip in the crossfade
    with pytest.raises(ValueError): MF.splice(y, SR, x, 5.0, 0.25)


def test_the_track_is_cut_or_padded_to_the_film():
    rng = np.random.default_rng(2); y = (0.3 * rng.standard_normal((SR * 10, 2))).astype(np.float32)
    cut, r = MF.fit_length(y, SR, 8.0); assert len(cut) == 8 * SR and r['ok'] and r['faded'] and r['trimmed_s'] == 2.0 and abs(cut[-1]).max() < 1e-3
    quiet = np.concatenate([y[:8 * SR], np.zeros((2 * SR, 2), np.float32)]); _, r = MF.fit_length(quiet, SR, 8.0); assert not r['faded']
    pad, r = MF.fit_length(y, SR, 11.0); assert len(pad) == 11 * SR and r['padded_s'] == 1.0 and r['ok'] and np.all(pad[10 * SR:] == 0)


def test_only_sections_whose_key_moved_are_stale():
    old = [dict(first=0, key='a'), dict(first=8, key='b')]; new = [dict(first=0, key='a'), dict(first=8, key='c'), dict(first=16, key='d')]
    assert [s['first'] for s in MF.stale(old, new)] == [8, 16] and len(MF.stale(None, new)) == 3


def test_singing_in_a_take_is_measured_against_the_take():
    x = np.ones(100, np.float32); assert MF.singing_db(x, 0.1 * x) == -20.0 and MF.singing_db(x, np.zeros(100)) == float('-inf')


def test_repair_tries_the_next_seed_for_only_the_takes_that_failed():
    bar_s = 2.0; calls = []
    def gen(items, seeds):
        calls.append(list(seeds)); return [clicks(120 if (s['first'] == 0 or seed == 1) else 140, 4) for (s, _), seed in zip(items, seeds)]
    items = [(dict(first=0, end=4, bar_s=bar_s), {}), (dict(first=4, end=8, bar_s=bar_s), {})]; notes = []
    res = MF.repair(items, gen, SR, stretch=resample_stretch, note=lambda s, seed, r: notes.append((s['first'], seed, r['action'])))
    assert calls == [[0, 0], [1]] and [r['ok'] for _, r in res] == [True, True] and res[1][1]['seed'] == 1 and len(res[1][1]['takes']) == 2
    assert [(f, seed) for f, seed, _ in notes] == [(0, 0), (4, 0), (4, 1)] and notes[0][2] == notes[2][2] == 'as is' and notes[1][2] in ('repaint', 'regenerate')        # either way the take is made again


def test_a_chosen_take_that_fails_is_not_replaced_and_nothing_made_is_reported():
    items = [(dict(first=0, end=4, bar_s=2.0, take=5), {})]
    res = MF.repair(items, lambda its, seeds: [clicks(140, 4)], SR, stretch=resample_stretch); assert res[0][0] is None and len(res[0][1]['takes']) == 1 and res[0][1]['takes'][0]['seed'] == 5
    res = MF.repair([(dict(first=0, end=4, bar_s=2.0), {})], lambda its, seeds: [None], SR, tries=2); assert res[0][0] is None and [t['action'] for t in res[0][1]['takes']] == ['failed', 'failed']


def test_the_build_is_judged_bar_by_bar_against_its_bar_of_the_original():
    x = clicks(120, 8); grid = [2.0 * k + 0.046 for k in range(8)]                                       # a grid 46 ms off what is heard, as the smoothed grid is at some bars
    assert not MF.grid_check(x, SR, grid, beat_s=0.5, end_s=16.0)['ok']                                    # against an ideal pulse on that grid it is off
    built = np.concatenate([x[int(4 * SR):int(8 * SR)], x[:int(4 * SR)]]); r = MF.grid_check(built, SR, [0.0, 2.0, 4.0, 6.0], ref=x, ref_marks=[4.0, 6.0, 0.0, 2.0], beat_s=0.5, end_s=8.0)
    assert r['ok'] and r['worst_ms'] < 15 and r['judged'] >= 3                                              # re-sequenced bars line up with their own bars of the original (the first click, at sample 0, has no onset)
    late = built.copy(); late[int(4 * SR):int(6 * SR)] = np.roll(built[int(4 * SR):int(6 * SR)], int(0.06 * SR)); r = MF.grid_check(late, SR, [0.0, 2.0, 4.0, 6.0], ref=x, ref_marks=[4.0, 6.0, 0.0, 2.0], beat_s=0.5, end_s=8.0)
    assert r['off_bars'] == [2] and 50 < r['offsets_ms'][2] < 70


def test_a_track_with_no_rhythm_has_a_flat_envelope():
    t = np.arange(SR * 4) / SR; assert MF.envelope((0.3 * np.sin(2 * np.pi * 220 * t)).astype(np.float32), SR).max() < 0.1 and MF.envelope(np.zeros(100), SR).tolist() == [0.0]


def test_a_lag_is_found_to_within_a_few_milliseconds():
    e = MF.envelope(clicks(120, 4), SR); late = MF.envelope(np.concatenate([np.zeros(int(0.023 * SR), np.float32), clicks(120, 4)]), SR)
    l, c = MF.lag(late, int(2.0 * MF.FPS), e, int(2.0 * MF.FPS), int(2.0 * MF.FPS), 20); assert l == pytest.approx(0.023, abs=0.004) and c > 0.8
    assert MF.lag(np.zeros(500), 0, e, 0, 100, 10) == (0.0, 0.0)


def test_a_repaint_is_judged_on_its_bars_inside_the_context_and_cut_to_them():
    bar_s = 4 * 60 / 97; ctx = clicks(97, 16); marks = [bar_s * k for k in range(4, 9)]
    y, r = MF.tempo_fit(ctx, SR, 4, bar_s, marks=marks, ref=ctx, stretchable=False); assert r['action'] == 'as is' and len(y) == int(round(marks[-1] * SR)) - int(round(marks[0] * SR))
    off = ctx.copy(); a, z = int(marks[0] * SR), int(marks[-1] * SR); off[a:z] = np.roll(ctx[a:z], int(0.08 * SR))  # the repainted bars 80 ms late
    assert MF.tempo_fit(off, SR, 4, bar_s, marks=marks, ref=ctx, stretchable=False)[1]['action'] == 'repaint'
    assert MF.tempo_fit(clicks(110, 16), SR, 4, bar_s, marks=marks, ref=ctx, stretchable=False)[1]['action'] == 'repaint'      # a repaint is never stretched: its bars around are fixed


def test_the_ideal_pulse_has_every_beat_and_a_stronger_downbeat():
    late = MF.MU.N_FFT / 2 / SR; e = MF.pulse(400, [1.0, 3.0], 4); peaks = [int(round((t - late) * MF.FPS)) for t in (1.0, 1.5, 2.0, 2.5)]
    assert e[peaks[0]] == pytest.approx(2.0) and all(e[p] == pytest.approx(1.0) for p in peaks[1:]) and e[int(round(2.75 * MF.FPS))] == 0
