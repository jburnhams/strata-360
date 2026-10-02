"""Chronological planner: time order, every clip included, no overlaps, exact length, seeds. Run: .venv/bin/python tests/test_chrono.py"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'src'))
import numpy as np
from strata360.edit import techniques as T, optimise as O, chrono as C

LIB = T.load()


def music(bpm=120, seconds=60):
    beats = int(seconds * bpm / 60)
    return O.Music(bpm=bpm, beats=beats, bar_beats=4, sections=[(0, beats // 4, 0.3), (beats // 4, beats * 3 // 4, 0.8), (beats * 3 // 4, beats, 0.4)])


def make_clips(lengths, seed=1, speech_clip=None):
    rng = np.random.default_rng(seed); clips = []
    for i, L in enumerate(lengths):
        cands = []; t = 0.0; k = 0
        while t < L - 3:
            ln = float(min(rng.uniform(4, 20), L - t)); q = float(rng.uniform(0.35, 0.9)); sp = 1.0 if speech_clip == i and k == 0 else 0.0
            f = dict(steady=float(rng.uniform(0.3, 1)), clear_nadir=float(rng.uniform(0.5, 1)), open_ground=float(rng.uniform(0.2, 1)), canopy=float(rng.uniform(0, 1)), subject=float(rng.uniform(0.3, 1)),
                     speech=sp, protagonist=float(rng.uniform(0, 1)), low_obstruction=float(rng.uniform(0.4, 1)), resolution=0.8)
            if sp: f['steady'] = 0.8
            cands.append(dict(id=f'C{i:02d}#{k:02d}', clip=f'C{i:02d}', start_s=t, end_s=t + ln, quality=q, energy=float(rng.uniform(0.2, 0.9)), min_dur=3.0 if sp else 1.0, max_dur=ln, features=f))
            t += ln + float(rng.uniform(1, 5)); k += 1
        clips.append(dict(id=f'C{i:02d}', start_utc=f'2026-02-19T{10 + i:02d}:00:00Z', duration_s=L, candidates=cands, unusable=[]))
    return clips


def test_plan_is_chronological_complete_and_valid():
    clips = make_clips([30, 12, 90, 8, 25, 40, 15]); m = music(); p = C.plan(clips, LIB, m, C.Settings(seed=1))
    assert C.violations(p, LIB, m, clips) == [], C.violations(p, LIB, m, clips)
    assert {s.cand.clip for s in p} == {c['id'] for c in clips} and sum(s.beats for s in p) == m.beats
    per = {}
    for s in p: per[s.cand.clip] = per.get(s.cand.clip, 0) + 1
    assert per['C02'] >= 2, per                                                                   # the 90 s clip is long enough to give several adjacent selections
    print('    segments per clip:', per, ' techniques:', len({s.tech.id for s in p}))


def test_no_overlap_inside_a_clip_and_adjacent_windows_are_allowed():
    clips = make_clips([120, 10, 10, 10]); m = music(seconds=50); p = C.plan(clips, LIB, m, C.Settings(seed=2))
    big = [s for s in p if s.cand.clip == 'C00']; assert len(big) >= 3
    for a, b in zip(big, big[1:]): assert b.clip_start_s >= a.clip_start_s + a.beats * m.beat_s - 1e-6
    assert any(abs(b.clip_start_s - (a.clip_start_s + a.beats * m.beat_s)) < 1e-6 for a, b in zip(big, big[1:])), 'adjacent windows (touching) should occur inside a long clip'


def test_seeds_reproduce_and_differ_but_order_never_changes():
    clips = make_clips([30, 40, 50, 20, 60]); m = music()
    a, b = C.plan(clips, LIB, m, C.Settings(seed=5)), C.plan(clips, LIB, m, C.Settings(seed=5)); c = C.plan(clips, LIB, m, C.Settings(seed=6))
    sig = lambda p: [(s.cand.id, s.tech.id, s.beats, s.in_s) for s in p]
    assert sig(a) == sig(b) and [s.tech.id for s in a] != [s.tech.id for s in c]
    for p in (a, c): assert C.violations(p, LIB, m, clips) == []


def test_speech_windows_only_get_dialogue_safe_techniques():
    clips = make_clips([30, 30, 30], speech_clip=1); m = music(); p = C.plan(clips, LIB, m, C.Settings(seed=3))
    assert C.violations(p, LIB, m, clips) == []
    for s in p:
        if s.cand.speech: assert s.tech.dialogue_ok


def test_too_short_a_film_names_the_binding_constraint():
    clips = make_clips([30] * 12)
    try: C.plan(clips, LIB, music(seconds=10), C.Settings()); assert False
    except O.Infeasible as e: assert 'every clip' in str(e) and '12 clips' in str(e), str(e)
    try: C.plan(make_clips([6, 6]), LIB, music(seconds=120), C.Settings()); assert False
    except O.Infeasible as e: assert 'usable footage' in str(e), str(e)


def test_a_clip_with_no_usable_moment_still_contributes_its_best_unusable_stretch():
    clips = make_clips([30, 30, 30]); clips[1]['candidates'] = []; clips[1]['unusable'] = [dict(start_s=2.0, end_s=14.0, usable=False, reasons=['too shaky'], stats=dict(score=0.3))]
    m = music(); p = C.plan(clips, LIB, m, C.Settings(seed=1)); assert C.violations(p, LIB, m, clips) == [] and any(s.forced for s in p if s.cand.clip == 'C01')


def overlapping_clips():
    """Every clip: one long span with overlapping alternatives (best part, a person in view, you speaking): the same footage seen in several ways."""
    clips = make_clips([60, 60, 60, 60]); base = dict(features=None)
    for c in clips:
        whole = c['candidates'][0]; f = dict(whole['features']); f['speech'] = 0.0
        c['candidates'] = [dict(id=f"{c['id']}#00", clip=c['id'], kind='span', view='ahead', start_s=0.0, end_s=50.0, quality=0.6, energy=0.5, min_dur=1.0, max_dur=50.0, features=dict(f)),
                           dict(id=f"{c['id']}#01", clip=c['id'], kind='best', view='ahead', start_s=10.0, end_s=30.0, quality=0.85, energy=0.5, min_dur=1.0, max_dur=20.0, features=dict(f)),
                           dict(id=f"{c['id']}#02", clip=c['id'], kind='person', view='person', start_s=14.0, end_s=26.0, quality=0.8, energy=0.5, min_dur=1.0, max_dur=12.0, features=dict(f)),
                           dict(id=f"{c['id']}#03", clip=c['id'], kind='speech', view='speaker', start_s=40.0, end_s=48.0, quality=0.7, energy=0.4, min_dur=3.0, max_dur=8.0, features={**f, 'speech': 1.0, 'steady': 0.9})]
    return clips


def test_overlapping_candidates_never_give_overlapping_windows_and_speech_is_dialogue():
    clips = overlapping_clips(); m = music(seconds=90); p = C.plan(clips, LIB, m, C.Settings(seed=2)); assert C.violations(p, LIB, m, clips) == []
    for cid in {s.cand.clip for s in p}:
        ws = sorted([(s.clip_start_s, s.clip_start_s + s.beats * m.beat_s) for s in p if s.cand.clip == cid]); assert all(b[0] >= a[1] - 1e-6 for a, b in zip(ws, ws[1:])), ws
    kinds = {getattr(s.cand, 'kind', None) for s in p}; assert len(kinds) >= 2, kinds                      # more than one way of seeing the footage gets used
    for s in p:                                                                                          # anything cut from where you speak (40-48 s) is dialogue, whichever candidate it came from
        a, b = s.clip_start_s, s.clip_start_s + s.beats * m.beat_s
        if min(b, 48) - max(a, 40) >= 0.25 * (b - a): assert s.parts['speech'] and s.tech.dialogue_ok, (s.tech.id, a, b)


def test_skipping_a_window_blocks_that_footage_in_every_candidate():
    clips = overlapping_clips(); m = music(seconds=90); p = C.plan(clips, LIB, m, C.Settings(seed=2)); g = next(s for s in p if s.cand.clip == 'C01')
    a, b = g.clip_start_s, g.clip_start_s + g.beats * m.beat_s; q = C.plan(clips, LIB, m, C.Settings(seed=2, bans_cands=frozenset({f'win:C01@{a}@{b}'})))
    assert C.violations(q, LIB, m, clips) == [] and all(s.clip_start_s + s.beats * m.beat_s <= a + 1e-6 or s.clip_start_s >= b - 1e-6 for s in q if s.cand.clip == 'C01')


if __name__ == '__main__':
    fns = [v for k, v in sorted(globals().items()) if k.startswith('test_')]; bad = 0
    for f in fns:
        try: f(); print('ok  ', f.__name__)
        except (AssertionError, O.Infeasible) as e: bad += 1; print('FAIL', f.__name__, repr(e)[:300])
    print(f'{len(fns) - bad}/{len(fns)} passed'); sys.exit(bad)


def test_millisecond_rounding_of_back_to_back_windows_is_not_an_overlap():
    clips = make_clips([200, 40, 40, 40]); m = music(bpm=97, seconds=50); p = C.plan(clips, LIB, m, C.Settings(seed=2))
    pairs = [(a, b) for a, b in zip(p, p[1:]) if a.cand.clip == b.cand.clip]; assert pairs, 'need two windows from one clip'
    a, b = pairs[0]; end = a.clip_start_s + a.beats * m.beat_s
    b.clip_start_s = round(end - 0.0008, 3); assert C.violations(p, LIB, m, clips) == []                      # 0.8 ms: what rounding to the millisecond produces (seen on Legends at 97 bpm)
    b.clip_start_s = end - 0.02; assert any('overlap or disorder' in v for v in C.violations(p, LIB, m, clips))   # a real overlap is still caught
