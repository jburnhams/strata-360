"""audio/duck.py: the music's gain curve under speech."""
import numpy as np
from strata360.audio import duck

SR = 8000


def tone(a, b, n=6 * SR, hz=300.0, amp=0.3):
    t = np.arange(n) / SR; x = np.zeros(n, np.float32); m = (t >= a) & (t < b); x[m] = amp * np.sin(2 * np.pi * hz * t[m]); return x


def test_speech_spans_find_the_lines_bridge_short_pauses_and_ignore_clicks_and_silence():
    x = tone(1.0, 1.6) + tone(1.8, 2.5) + tone(4.0, 4.05)                                  # one line with a 0.2 s pause in it, then a 50 ms click
    s = duck.speech_spans(x, SR); assert len(s) == 1 and abs(s[0][0] - 0.95) < 0.05 and abs(s[0][1] - 2.55) < 0.05
    two = duck.speech_spans(tone(1.0, 1.6) + tone(3.0, 3.6), SR); assert len(two) == 2                                  # a long pause is the end of a line
    assert duck.speech_spans(np.zeros(SR, np.float32), SR) == [] and duck.speech_spans(np.zeros(3, np.float32), SR) == []


def test_the_envelope_is_one_outside_and_the_depth_inside_and_the_music_is_already_down_when_the_voice_starts():
    e = duck.envelope(6 * SR, SR, [(2.0, 3.0)], 12.0, attack_s=0.08, release_s=0.5); db = 20 * np.log10(e)
    assert e[: int(1.9 * SR)].min() == 1.0 and e[int(3.6 * SR):].min() == 1.0
    assert abs(db[int(2.0 * SR)] + 12.0) < 0.05 and abs(db[int(2.5 * SR)] + 12.0) < 0.05 and abs(db[int(3.0 * SR)] + 12.0) < 0.05          # at the first syllable and for the whole line: at depth
    assert -12 < db[int(1.96 * SR)] < 0 and -12 < db[int(3.25 * SR)] < 0 and (np.diff(db[int(1.9 * SR):int(2.0 * SR)]) <= 1e-6).all()      # a smooth ramp in, and out after the line


def test_overlapping_spans_take_the_deepest_and_combine_takes_the_lowest_curve():
    deep = duck.envelope(4 * SR, SR, [(1.0, 2.0)], 12.0); shallow = duck.envelope(4 * SR, SR, [(1.5, 3.0)], 6.0)
    both = duck.combine(shallow, deep); assert both[int(1.7 * SR)] == deep[int(1.7 * SR)] and abs(20 * np.log10(both[int(2.5 * SR)]) + 6.0) < 0.05 and (both <= shallow + 1e-9).all() and (both <= deep + 1e-9).all()
    assert duck.envelope(100, SR, [], 12.0).min() == 1.0 and duck.envelope(100, SR, [(50.0, 60.0)], 12.0).min() == 1.0                          # no spans, or spans beyond the end: untouched
