"""The talking shot (dialogue_hold) opens a clip's speaking and is then mixed with the other views of you: never twice in a row, and not the usual choice after the first shot."""
import numpy as np
import pytest

from strata360.edit import chrono as CH, optimise as O, techniques as TQ

LIB = TQ.load()


def cand(clip='c', **ft):
    f = dict(steady=0.9, protagonist=0.9, speech=0.9, you_close=0.9, you_far=0.9, canopy=0.2, clear_nadir=0.5, open_ground=0.5, subject=0.5, low_obstruction=0.8, resolution=0.8); f.update(ft)
    return CH.clip_candidates(dict(id=clip, candidates=[dict(id=f'{clip}#1', clip=clip, start_s=0.0, end_s=80.0, quality=0.6, energy=0.5, min_dur=1.0, max_dur=80.0, kind='span', features=f)]))[0]


def plan(spec, beats=8, seed=1, **ft):
    """Plan speech windows: `spec` is a list of clip names, one window of `beats` beats (120 bpm: 4 s) each, back to back within a clip. Returns the techniques."""
    cands = {}; clips = []; windows = []; pos = {}
    for name in spec:
        if name not in cands: cands[name] = cand(name, **ft); clips.append(dict(id=name, start_utc='2026-02-22T10:00:00Z', duration_s=80.0, candidates=[]))
        i = [c['id'] for c in clips].index(name); t = pos.get(name, 0.0); w = CH.Window(i, cands[name], t, beats, 0.6, False, speech=True); windows.append(w); pos[name] = t + beats * 0.5
    music = O.Music(bpm=120.0, beats=beats * len(windows), bar_beats=4, sections=[(0, 10 ** 9, 0.5)])
    segs = CH.assign_techniques(windows, clips, LIB, music, CH.Settings(seed=seed), np.random.default_rng(seed), [], B=beats * len(windows)); return [s.tech.id for s in segs]


def test_the_talking_shot_opens_the_speaking_of_each_clip():
    for seed in (1, 2, 3):
        t = plan(['a', 'a', 'a', 'b', 'b', 'b'], seed=seed); assert t[0] == 'dialogue_hold' and t[3] == 'dialogue_hold', t


def test_after_the_opening_shot_the_other_views_of_you_are_cut_in_and_it_is_never_used_twice_in_a_row():
    for seed in range(1, 8):
        t = plan(['a'] * 6, seed=seed); assert t[0] == 'dialogue_hold' and not any(a == b == 'dialogue_hold' for a, b in zip(t, t[1:])) and t.count('dialogue_hold') <= 2 and len(set(t)) >= 3, t


def test_it_is_still_used_when_it_is_the_only_shot_that_can_carry_the_speech():
    t = plan(['a'] * 4, protagonist=0.0, you_close=0.0, you_far=0.0); assert set(t) <= {'dialogue_hold', 'selfie_hold'} and 'dialogue_hold' in t          # someone else talking: no view of you fits, so the planner relaxes its limits rather than fail


def test_the_settings_for_the_mix_are_there():
    s = CH.Settings(); assert s.w_establish > 0 and s.pen_talk > 0 and s.share_caps['dialogue_hold'] <= 0.15
