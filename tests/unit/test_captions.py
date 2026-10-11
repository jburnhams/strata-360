"""The subtitle track (render/captions.py): cutting lines into cues, the .srt, and drawing a cue on a frame."""
import numpy as np
from strata360.render import captions as C


def test_a_long_line_is_cut_at_sentences_and_timed_by_length():
    cues = C.split_phrases('Legends 350. A 367-kilometer race. I decided to try and do the whole thing with no sleep.', 10.0, 20.0)
    assert [c[2] for c in cues] == ['Legends 350.', 'A 367-kilometer race.', 'I decided to try and do the whole thing with no sleep.']
    assert cues[0][0] == 10.0 and abs(cues[-1][1] - 20.0) < 0.01 and all(a < b for a, b, _ in cues) and cues[0][1] == cues[1][0]
    long = C.split_phrases('word ' * 40, 0.0, 8.0, max_chars=50); assert len(long) >= 4 and all(len(t) <= 50 for _, _, t in long)
    assert C.split_phrases('  ', 0.0, 1.0) == []


def test_the_srt_has_numbered_cues_with_comma_times(tmp_path):
    p = C.write_srt([dict(t0=1.5, t1=3.25, text='Hello', kind='vo'), dict(t0=3661.001, t1=3662.0, text='Later', kind='speech')], str(tmp_path / 'a.srt')); s = open(p, encoding='utf-8').read()
    assert s.startswith('1\n00:00:01,500 --> 00:00:03,250\nHello\n\n2\n01:01:01,001 --> 01:01:02,000\nLater\n')


def test_corrections_replace_or_remove_words():
    seg = dict(words=[dict(w='in', t0=0.0, t1=0.2), dict(w='the', t0=0.2, t1=0.3), dict(w='night', t0=0.3, t1=0.6), dict(w='um', t0=0.6, t1=0.8)])
    got = C.corrected_words(seg, {'3:0': dict(gemini=dict(text='from')), '3:3': dict(gemini=dict(text=''))}, 3)
    assert [w[2] for w in got] == ['from', 'the', 'night']


def test_a_cue_is_drawn_only_while_it_is_on_and_the_frame_is_otherwise_untouched():
    cap = C.Captions([dict(t0=1.0, t1=3.0, text='Four days across the Ardennes', kind='vo')], 640, 360, 25.0); img = np.full((360, 640, 3), 80, np.uint8)
    assert cap.apply(img, 10) is img and cap.apply(img, 100) is img                                              # before and after: the same array
    on = cap.apply(img, 50); assert on is not img and (on != img).any() and (on[:200] == img[:200]).all() and on[300:].max() > 200      # drawn along the bottom only, with light letters
    assert cap.apply(img, 50, bgr=True).shape == img.shape and not (C.Captions(cap.cues, 640, 360, 25.0, burn=False).apply(img, 50) != img).any()


def test_a_voice_over_and_a_speech_cue_at_once_are_stacked_with_the_voice_over_lower():
    cap = C.Captions([dict(t0=0, t1=5, text='Speech line', kind='speech'), dict(t0=0, t1=5, text='Voice over line', kind='vo')], 640, 360, 25.0); img = np.zeros((360, 640, 3), np.uint8); out = cap.apply(img, 50)
    rows = np.where(out.max(axis=(1, 2)) > 200)[0]; assert rows.max() > 300 and rows.min() < rows.max() - 20 and (np.diff(rows) > 1).any()       # two separate bands of text
